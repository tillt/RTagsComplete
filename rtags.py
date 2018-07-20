# -*- coding: utf-8 -*-

"""RTagsComplete plugin for Sublime Text 3.

Provides completion suggestions and much more for C/C++ languages
based on RTags.

Original code by Sergei Turukin.
Hacked with plenty of new features by Till Toenshoff.
Some code lifted from EasyClangComplete by Igor Bogoslavskyi.

TODO(tillt): The current tests are broken and need to get redone.
"""

import collections
import logging
import html
import re
import sublime
import sublime_plugin
import json

from datetime import datetime
from os import path
from functools import partial

from .plugin import completion
from .plugin import fixits
from .plugin import idle
from .plugin import indicator
from .plugin import jobs
from .plugin import settings
from .plugin import tools


log = logging.getLogger("RTags")
log.setLevel(logging.DEBUG)
log.propagate = False

formatter_default = logging.Formatter(
    '%(name)s:%(levelname)s: %(message)s')
formatter_verbose = logging.Formatter(
    '%(name)s:%(levelname)s: %(asctime)-15s %(filename)s::%(funcName)s'
    ' [%(threadName)s]: %(message)s')

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter_default)
if not log.hasHandlers():
    log.addHandler(ch)


def get_view_text(view):
    return bytes(view.substr(sublime.Region(0, view.size())), "utf-8")


def supported_view(view):
    if not view:
        return False

    file_types = settings.SettingsManager.get('file_types', ["source.c", "source.c++"])
    if not view.scope_name(view.sel()[0].a).split()[0] in file_types:
        return False

    if not view.file_name():
        return False

    if view.is_scratch():
        return False

    if view.buffer_id() == 0:
        return False

    if not path.exists(view.file_name()):
        return False

    return True


class NavigationHelper(object):
    NAVIGATION_REQUESTED = 1
    NAVIGATION_DONE = 2

    def __init__(self):
        # navigation indicator, possible values are:
        # - NAVIGATION_REQUESTED
        # - NAVIGATION_DONE
        self.flag = NavigationHelper.NAVIGATION_DONE
        # rc utility switches to use for callback
        self.switches = []
        # File contents that has been passed to reindexer last time.
        self.data = ''
        # History of navigations.
        # Elements are tuples (filename, line, col).
        self.history = collections.deque()


class RtagsBaseCommand(sublime_plugin.TextCommand):
    FILE_INFO_REG = r'(\S+):(\d+):(\d+):(.*)'

    def command_done(self, future, **kwargs):
        log.debug("Command done callback hit {}".format(future))

        if not future.done():
            log.warning("Command future failed")
            return

        if future.cancelled():
            log.warning(("Command future aborted"))
            return

        (job_id, out, error) = future.result()

        location = -1
        if 'col' in kwargs:
            location = self.view.text_point(kwargs['row'], kwargs['col'])

        fixits_controller.signal_status(view=self.view, error=error)

        if error:
            log.error("Command task failed: {}".format(error.message))

            rendered = settings.SettingsManager.template_as_html("error","popup", error.message)

            self.view.show_popup(
                rendered,
                sublime.HIDE_ON_MOUSE_MOVE_AWAY,
                max_width=self.MAX_POPUP_WIDTH,
                max_height=self.MAX_POPUP_HEIGHT,
                location=location)
            return

        log.debug("Finished Command job {}".format(job_id))

        # We never needed this - maybe it got fixed in RTags?
        #
        # Dirty hack.
        # TODO figure out why rdm responds with 'Project loading'
        # for now just repeat query.
        #if error and error.code == jobs.JobError.PROJECT_LOADING:
        #    def rerun():
        #        self.view.run_command('rtags_location', {'switches': switches})
        #    sublime.set_timeout_async(rerun, 500)
        #    return

        # Drop the flag, we are going to navigate.
        navigation_helper.flag = NavigationHelper.NAVIGATION_DONE
        navigation_helper.switches = []

        self._action(out, **kwargs)

    def run(self, edit, switches, *args, **kwargs):
        # Do nothing if not called from supported code.
        if not supported_view(self.view):
            return
        # File should be reindexed only when
        # 1. file buffer is dirty (modified)
        # 2. there is no pending reindexation (navigation_helper flag)
        # 3. current text is different from previous one
        # It takes ~40-50 ms to reindex 2.5K C file and
        # miserable amount of time to check text difference.
        if (navigation_helper.flag == NavigationHelper.NAVIGATION_DONE and
                self.view.is_dirty() and
                navigation_helper.data != get_view_text(self.view)):
            navigation_helper.switches = switches
            navigation_helper.data = get_view_text(self.view)
            navigation_helper.flag = NavigationHelper.NAVIGATION_REQUESTED
            fixits_controller.reindex(view=self.view, saved=False)
            # Never go further.
            return

        job_args = kwargs
        job_args.update({'view': self.view})

        jobs.JobController.run_async(
            jobs.RTagsJob(
                "RTBaseCommand" + jobs.JobController.next_id(),
                switches + [self._query(*args, **kwargs)],
                **job_args),
            partial(self.command_done, **kwargs),
            progress_indicator)

    def on_select(self, res):
        if res == -1:
            return

        (row, col) = self.view.rowcol(self.view.sel()[0].a)

        navigation_helper.history.append(
            (self.view.file_name(), row + 1, col + 1))

        (file, line, col, _) = re.findall(
            RtagsBaseCommand.FILE_INFO_REG,
            self.last_references[res])[0]

        if len(navigation_helper.history) > int(settings.SettingsManager.get('jump_limit', 10)):
            navigation_helper.history.popleft()

        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)

    def on_highlight(self, res):
        if res == -1:
            return

        (file, line, col, _) = re.findall(
            RtagsBaseCommand.FILE_INFO_REG,
            self.last_references[res])[0]

        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION | sublime.TRANSIENT)

    def _query(self, *args, **kwargs):
        return ''

    def _action(self, out, **kwargs):

        # Pretty format the results.
        items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
        self.last_references = items

        def out_to_items(item):
            (file, line, _, usage) = re.findall(RtagsBaseCommand.FILE_INFO_REG, item)[0]
            return [usage.strip(), "{}:{}".format(file.split('/')[-1], line)]

        items = list(map(out_to_items, items))

        # If there is only one result no need to show it to user
        # just do navigation directly.
        if len(items) == 1:
            self.on_select(0)
            return

        self.view.window().show_quick_panel(
            items,
            self.on_select,
            sublime.MONOSPACE_FONT,
            -1,
            self.on_highlight)


class RtagsShowFixitsCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        if not supported_view(self.view):
            return
        fixits_controller.show_selector(self.view)


class RtagsFixitCommand(RtagsBaseCommand):

    def run(self, edit, **args):
        fixits_controller.update(args['filename'], args['issues'])


class RtagsGoBackwardCommand(sublime_plugin.TextCommand):

    def run(self, edit):
        try:
            file, line, col = navigation_helper.history.pop()
            view = self.view.window().open_file(
                '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)
        except IndexError:
            pass


class RtagsLocationCommand(RtagsBaseCommand):

    def _query(self, *args, **kwargs):
        if 'col' in kwargs:
            col = kwargs['col']
            row = kwargs['row']
        else:
            row, col = self.view.rowcol(self.view.sel()[0].a)
        return '{}:{}:{}'.format(self.view.file_name(),
                                 row + 1, col + 1)


class RtagsSymbolInfoCommand(RtagsLocationCommand):
    MAX_POPUP_WIDTH = 1800
    MAX_POPUP_HEIGHT = 900

    # Not useful for our users, we hereby decide.
    FILTER_TITLES=[
        'arguments',
        'baseClasses',
        'cf',
        'cfl',
        'cflcontext',
        'context',
        'endLine',
        'endColumn',
        'functionArgumentCursor',
        'functionArgumentLength',
        'functionArgumentLocation',
        'functionArgumentLocationContext',
        'invocation',
        'invocationContext',
        'invokedFunction',
        'location',
        'parent',
        'range',
        'startLine',
        'startColumn',
        'symbolLength',
        'usr',
        'xmlComment'
    ]

    # Camelcase doesn't look so nice on interfaces.
    MAP_TITLES={
        'argumentIndex':            'argument index',
        'briefComment':             'brief comment',
        'constmethod':              'const method',
        'purevirtual':              'pure virtual',
        'macroexpansion':           'macro expansion',
        'templatespecialization':   'template specialization',
        'templatereference':        'template reference',
        'staticmethod':             'static method',
        'stackCost':                'size on stack',
        'symbolName':               'name'
    }

    # Prefixed positions.
    POSITION_TITLES={
        'symbolName':   '0',
        'briefComment': '1',
        'type':         '2',
        'kind':         '3',
        'linkage':      '4',
        'sizeof':       '5'
    }

    # Kind extensions.
    # TODO(tillt): Find a complete list of possible boolean kind extensions.
    KIND_EXTENSION_BOOL_TYPES=[
        'auto',
        'virtual',
        'container',
        'definition',
        'reference'
    ]

    # Human readable type descriptions of clang's cursor kind types.
    # Extracted from https://raw.githubusercontent.com/llvm-mirror/clang/master/include/clang-c/Index.h
    MAP_KINDS={
        'UnexposedDecl': 'A declaration whose specific kind is not exposed via this interface.',
        'StructDecl': 'A C or C++ struct.',
        'UnionDecl': 'A C or C++ union.',
        'ClassDecl': 'A C++ class.',
        'EnumDecl': 'An enumeration.',
        'FieldDecl': 'A field (in C) or non-static data member (in C++) in a struct, union, or C++ class.',
        'EnumConstantDecl': 'An enumerator constant.',
        'FunctionDecl': 'A function.',
        'VarDecl': 'A variable.',
        'ParmDecl': 'A function or method parameter.',
        'ObjCInterfaceDecl': 'An Objective-C @interface.',
        'ObjCCategoryDecl': 'An Objective-C @interface for a category.',
        'ObjCProtocolDecl': 'An Objective-C @protocol declaration.',
        'ObjCPropertyDecl': 'An Objective-C @property declaration.',
        'ObjCIvarDecl': 'An Objective-C instance variable.',
        'ObjCInstanceMethodDecl': 'An Objective-C instance method.',
        'ObjCClassMethodDecl': 'An Objective-C class method.',
        'ObjCImplementationDecl': 'An Objective-C @implementation.',
        'ObjCCategoryImplDecl': 'An Objective-C @implementation for a category.',
        'TypedefDecl': 'A typedef.',
        'CXXMethod': 'A C++ class method.',
        'Namespace': 'A C++ namespace.',
        'LinkageSpec': 'A linkage specification, e.g. \'extern \"C\"\'.',
        'Constructor': 'A C++ constructor.',
        'Destructor': 'A C++ destructor.',
        'ConversionFunction': 'A C++ conversion function.',
        'TemplateTypeParameter': 'A C++ template type parameter.',
        'NonTypeTemplateParameter': 'A C++ non-type template parameter.',
        'TemplateTemplateParameter': 'A C++ template template parameter.',
        'FunctionTemplate': 'A C++ function template.',
        'ClassTemplate': 'A C++ class template.',
        'ClassTemplatePartialSpecialization': 'A C++ class template partial specialization.',
        'NamespaceAlias': 'A C++ namespace alias declaration.',
        'UsingDirective': 'A C++ using directive.',
        'UsingDeclaration': 'A C++ using declaration.',
        'TypeAliasDecl': 'A C++ alias declaration',
        'ObjCSynthesizeDecl': 'An Objective-C @synthesize definition.',
        'ObjCDynamicDecl': 'An Objective-C @dynamic definition.',
        'CXXAccessSpecifier': 'An access specifier.',
        'TypeRef': 'A reference to a type declaration.',
        'TemplateRef': 'A reference to a class template, function template, template template parameter, or class template partial specialization.',
        'NamespaceRef': 'A reference to a namespace or namespace alias.',
        'MemberRef': 'A reference to a member of a struct, union, or class that occurs in some non-expression context, e.g., a designated initializer.',
        'LabelRef': 'A reference to a labeled statement.',
        'OverloadedDeclRef': 'A reference to a set of overloaded functions or function templates that has not yet been resolved to a specific function or function template.',
        'VariableRef': 'A reference to a variable that occurs in some non-expression context, e.g., a C++ lambda capture list.',
        'UnexposedExpr': 'An expression whose specific kind is not exposed via this interface.',
        'DeclRefExpr': 'An expression that refers to some value declaration, such as a function, variable, or enumerator.',
        'MemberRefExpr': 'An expression that refers to a member of a struct, union, class, Objective-C class, etc.',
        'CallExpr': 'An expression that calls a function.',
        'ObjCMessageExpr': 'An expression that sends a message to an Objective-C object or class.',
        'BlockExpr': 'An expression that represents a block literal.',
        'IntegerLiteral': 'An integer literal.',
        'FloatingLiteral': 'A floating point number literal.',
        'ImaginaryLiteral': 'An imaginary number literal.',
        'StringLiteral': 'A string literal.',
        'CharacterLiteral': 'A character literal.',
        'ParenExpr': 'A parenthesized expression, e.g. \"(1)\".',
        'UnaryOperator': 'This represents the unary-expression\'s (except sizeof and alignof).',
        'ArraySubscriptExpr': '[C99 6.5.2.1] Array Subscripting.',
        'BinaryOperator': 'A builtin binary operation expression such as "x + y" or "x <= y".',
        'CompoundAssignOperator': 'Compound assignment such as "+=".',
        'ConditionalOperator': 'The ?: ternary operator.',
        'CStyleCastExpr': 'An explicit cast in C (C99 6.5.4) or a C-style cast in C++ (C++ [expr.cast]), which uses the syntax (Type)expr.',
        'CompoundLiteralExpr': '[C99 6.5.2.5]',
        'InitListExpr': 'Describes an C or C++ initializer list.',
        'AddrLabelExpr': 'The GNU address of label extension, representing &&label.',
        'StmtExpr': 'This is the GNU Statement Expression extension: ({int X=4; X;}).',
        'GenericSelectionExpr': 'Represents a C11 generic selection.',
        'GNUNullExpr': 'Implements the GNU __null extension, which is a name for a null pointer constant that has integral type (e.g., int or long) and is the same size and alignment as a pointer.',
        'CXXStaticCastExpr': 'C++\'s static_cast<> expression.',
        'CXXDynamicCastExpr': 'C++\'s dynamic_cast<> expression.',
        'CXXReinterpretCastExpr': 'C++\'s reinterpret_cast<> expression.',
        'CXXConstCastExpr': 'C++\'s const_cast<> expression.',
        'CXXFunctionalCastExpr': 'Represents an explicit C++ type conversion that uses \"functional\" notion (C++ [expr.type.conv]).',
        'CXXTypeidExpr': 'A C++ typeid expression (C++ [expr.typeid]).',
        'CXXBoolLiteralExpr': '[C++ 2.13.5] C++ Boolean Literal.',
        'CXXNullPtrLiteralExpr': '[C++0x 2.14.7] C++ Pointer Literal.',
        'CXXThisExpr': 'Represents the "this" expression in C++',
        'CXXThrowExpr': '[C++ 15] C++ Throw Expression.',
        'CXXNewExpr': 'A new expression for memory allocation and constructor calls, e.g: \"new CXXNewExpr(foo)\".',
        'CXXDeleteExpr': 'A delete expression for memory deallocation and destructor calls, e.g. \"delete[] pArray\".',
        'UnaryExpr': 'A unary expression. (noexcept, sizeof, or other traits)',
        'ObjCStringLiteral': 'An Objective-C string literal i.e. "foo".',
        'ObjCEncodeExpr': 'An Objective-C @encode expression.',
        'ObjCSelectorExpr': 'An Objective-C @selector expression.',
        'ObjCProtocolExpr': 'An Objective-C @protocol expression.',
        'ObjCBridgedCastExpr': 'An Objective-C "bridged" cast expression, which casts between Objective-C pointers and C pointers, transferring ownership in the process.',
        'PackExpansionExpr': 'Represents a C++0x pack expansion that produces a sequence of expressions.',
        'SizeOfPackExpr': 'Represents an expression that computes the length of a parameter pack.',
        'ObjCBoolLiteralExpr': 'Objective-c Boolean Literal.',
        'ObjCSelfExpr': 'Represents the "self" expression in an Objective-C method.',
        'OMPArraySectionExpr': 'OpenMP 4.0 [2.4, Array Section].',
        'ObjCAvailabilityCheckExpr': 'Represents an (...) check.',
        'FixedPointLiteral': 'Fixed point literal.',
        'UnexposedStmt': 'A statement whose specific kind is not exposed via this interface.',
        'LabelStmt': 'A labelled statement in a function.',
        'CompoundStmt': 'A group of statements like { stmt stmt }.',
        'CaseStmt': 'A case statement.',
        'DefaultStmt': 'A default statement.',
        'IfStmt': 'An if statement',
        'SwitchStmt': 'A switch statement.',
        'WhileStmt': 'A while statement.',
        'DoStmt': 'A do statement.',
        'ForStmt': 'A for statement.',
        'GotoStmt': 'A goto statement.',
        'IndirectGotoStmt': 'An indirect goto statement.',
        'ContinueStmt': 'A continue statement.',
        'BreakStmt': 'A break statement.',
        'ReturnStmt': 'A return statement.',
        'GCCAsmStmt': 'A GCC inline assembly statement extension.',
        'ObjCAtTryStmt': 'Objective-C\'s overall @try-@catch-@finally statement.',
        'ObjCAtCatchStmt': 'Objective-C\'s @catch statement.',
        'ObjCAtFinallyStmt': 'Objective-C\'s @finally statement.',
        'ObjCAtThrowStmt': 'Objective-C\'s @throw statement.',
        'ObjCAtSynchronizedStmt': 'Objective-C\'s @synchronized statement.',
        'ObjCAutoreleasePoolStmt': 'Objective-C\'s autorelease pool statement.',
        'ObjCForCollectionStmt': 'Objective-C\'s collection statement.',
        'CXXCatchStmt': 'C++\'s catch statement.',
        'CXXTryStmt': 'C++\'s try statement.',
        'CXXForRangeStmt': 'C++\'s for (* : *) statement.',
        'SEHTryStmt': 'Windows Structured Exception Handling\'s try statement.',
        'SEHExceptStmt': 'Windows Structured Exception Handling\'s except statement.',
        'SEHFinallyStmt': 'Windows Structured Exception Handling\'s finally statement.',
        'MSAsmStmt': 'A MS inline assembly statement extension.',
        'NullStmt': 'The null statement ";": C99 6.8.3p3.',
        'DeclStmt': 'Adaptor class for mixing declarations with statements and expressions.',
        'OMPParallelDirective': 'OpenMP parallel directive.',
        'OMPSimdDirective': 'OpenMP SIMD directive.',
        'OMPForDirective': 'OpenMP for directive.',
        'OMPSectionsDirective': 'OpenMP sections directive.',
        'OMPSectionDirective': 'OpenMP section directive.',
        'OMPSingleDirective': 'OpenMP single directive.',
        'OMPParallelForDirective': 'OpenMP parallel for directive.',
        'OMPParallelSectionsDirective': 'OpenMP parallel sections directive.',
        'OMPTaskDirective': 'OpenMP task directive.',
        'OMPMasterDirective': 'OpenMP master directive.',
        'OMPCriticalDirective': 'OpenMP critical directive.',
        'OMPTaskyieldDirective': 'OpenMP taskyield directive.',
        'OMPBarrierDirective': 'OpenMP barrier directive.',
        'OMPTaskwaitDirective': 'OpenMP taskwait directive.',
        'OMPFlushDirective': 'OpenMP flush directive.',
        'SEHLeaveStmt': 'Windows Structured Exception Handling\'s leave statement.',
        'OMPOrderedDirective': 'OpenMP ordered directive.',
        'OMPAtomicDirective': 'OpenMP atomic directive.',
        'OMPForSimdDirective': 'OpenMP for SIMD directive.',
        'OMPParallelForSimdDirective': 'OpenMP parallel for SIMD directive.',
        'OMPTargetDirective': 'OpenMP target directive.',
        'OMPTeamsDirective': 'OpenMP teams directive.',
        'OMPTaskgroupDirective': 'OpenMP taskgroup directive.',
        'OMPCancellationPointDirective': 'OpenMP cancellation point directive.',
        'OMPCancelDirective': 'OpenMP cancel directive.',
        'OMPTargetDataDirective': 'OpenMP target data directive.',
        'OMPTaskLoopDirective': 'OpenMP taskloop directive.',
        'OMPTaskLoopSimdDirective': 'OpenMP taskloop simd directive.',
        'OMPDistributeDirective': 'OpenMP distribute directive.',
        'OMPTargetEnterDataDirective': 'OpenMP target enter data directive.',
        'OMPTargetExitDataDirective': 'OpenMP target exit data directive.',
        'OMPTargetParallelDirective': 'OpenMP target parallel directive.',
        'OMPTargetParallelForDirective': 'OpenMP target parallel for directive.',
        'OMPTargetUpdateDirective': 'OpenMP target update directive.',
        'OMPDistributeParallelForDirective': 'OpenMP distribute parallel for directive.',
        'OMPDistributeParallelForSimdDirective': 'OpenMP distribute parallel for simd directive.',
        'OMPDistributeSimdDirective': 'OpenMP distribute simd directive.',
        'OMPTargetParallelForSimdDirective': 'OpenMP target parallel for simd directive.',
        'OMPTargetSimdDirective': 'OpenMP target simd directive.',
        'OMPTeamsDistributeDirective': 'OpenMP teams distribute directive.',
        'OMPTeamsDistributeSimdDirective': 'OpenMP teams distribute simd directive.',
        'OMPTeamsDistributeParallelForSimdDirective': 'OpenMP teams distribute parallel for simd directive.',
        'OMPTeamsDistributeParallelForDirective': 'OpenMP teams distribute parallel for directive.',
        'OMPTargetTeamsDirective': 'OpenMP target teams directive.',
        'OMPTargetTeamsDistributeDirective': 'OpenMP target teams distribute directive.',
        'OMPTargetTeamsDistributeParallelForDirective': 'OpenMP target teams distribute parallel for directive.',
        'OMPTargetTeamsDistributeParallelForSimdDirective': 'OpenMP target teams distribute parallel for simd directive.',
        'OMPTargetTeamsDistributeSimdDirective': 'OpenMP target teams distribute simd directive.',
        'TranslationUnit': 'Cursor that represents the translation unit itself.',
        'UnexposedAttr': 'An attribute whose specific kind is not exposed via this interface.',
        'ModuleImportDecl': 'A module import declaration.',
        'StaticAssert': 'A static_assert or _Static_assert node.',
        'FriendDecl': 'A friend declaration.',
        'OverloadCandidate': 'A code completion overload candidate.',

        #
        # Aliases or unexpexted but received results.
        # Aliases apparently change over time in clang's internal usage.
        #

        # Alias of "Constructor".
        'CXXConstructor': 'A C++ constructor.',
        # Alias of "Destructor".
        'CXXDestructor': 'A C++ destructor.',
        # Super confusing result - none of the clang-c cursor kind type
        # definitions or RTags sources show this string result. Instead we
        # would have expected a key similarly named - see title mappings
        # above. What is the deal here?
        "macro expansion": "A macro expansion.",
        "macro definition": "A macro definition.",
        "inclusion directive": "An inclusion directive."
    }

    def display_items(self, item):
        return "<div class=\"info\"><span class=\"header\">{}</span><br /><span class=\"info\">{}</span></div>".format(
            html.escape(item[0], quote=False),
            html.escape(item[1], quote=False))

    def symbol_location_callback(self, future, displayed_items, oldrow, oldcol, oldfile):
        log.debug("Symbol location callback hit {}".format(future))
        if not future.done():
            log.warning("Symbol location failed")
            return
        if future.cancelled():
            log.warning(("Symbol location aborted"))
            return

        (job_id, out, error) = future.result()

        fixits_controller.signal_status(view=self.view, error=error)

        if error:
            log.error("Command task failed: {}".format(error.message))
            return

        log.debug("Finished Command job {}".format(job_id))

        # It should be a single line of output.
        items = list(map(lambda x: x.decode('utf-8'), out.splitlines()))
        if not items:
            log.debug("Failed to get a location result for this symbol.")
            return

        (file, row, col, _) = re.findall(
            RtagsBaseCommand.FILE_INFO_REG,
            items[0])[0]

        link = "{}:{}:{}:{}:{}:{}".format(oldfile, oldrow, oldcol, file, row, col)

        log.debug("Symbol location resulted in {}".format(link))

        info = "<div class=\"info\"><span class=\"header\">{}</span><br /><a href=\"{}\">{}</a></div>\n".format(
            html.escape(displayed_items[0][0], quote=False),
            html.escape(link, quote=False),
            html.escape(displayed_items[0][1], quote=False))

        displayed_html_items = list(map(self.display_items, displayed_items[1:]))

        info += '\n'.join(displayed_html_items)

        rendered = settings.SettingsManager.template_as_html("info", "popup", info)

        self.view.update_popup(rendered)

    def on_navigate(self, href):
        (oldfile, oldline, oldcol, file, line, col) = re.findall(
            r'(\S+):(\d+):(\d+):(\S+):(\d+):(\d+)',
            href)[0]

        self.last_references = ["{}:{}:{}".format(oldfile, oldline, oldcol)]

        navigation_helper.history.append((oldfile, int(oldline) + 1, int(oldcol) + 1))

        if len(navigation_helper.history) > int(settings.SettingsManager.get('jump_limit', 10)):
            navigation_helper.history.popleft()

        view = self.view.window().open_file(
            '%s:%s:%s' % (file, line, col), sublime.ENCODED_POSITION)

    def _action(self, out, **kwargs):
        output_json = json.loads(out.decode("utf-8"))

        # Naive filtering, translation and sorting.
        priority_lane = {}
        alphabetic_keys = []
        kind_extension_keys = []
        for key in output_json.keys():
            if not key in RtagsSymbolInfoCommand.FILTER_TITLES:
                # Check if bookean types does well as a kind extension.
                if key in RtagsSymbolInfoCommand.KIND_EXTENSION_BOOL_TYPES:
                    if output_json[key]:
                        kind_extension_keys.append(key)
                else:
                    if key in RtagsSymbolInfoCommand.POSITION_TITLES.keys():
                        priority_lane[RtagsSymbolInfoCommand.POSITION_TITLES[key]]=key
                    else:
                        alphabetic_keys.append(key)

        priorized_keys = []
        for index in sorted(priority_lane.keys()):
            priorized_keys.append(priority_lane[index])

        alphabetic_keys = sorted(alphabetic_keys)

        sorted_keys = []
        sorted_keys.extend(priorized_keys)
        sorted_keys.extend(alphabetic_keys)

        displayed_items = []

        for key in sorted_keys:
            title = key
            info = str(output_json[key])

            if key in RtagsSymbolInfoCommand.MAP_TITLES:
                title = RtagsSymbolInfoCommand.MAP_TITLES[key]

            if key == "kind":
                if len(kind_extension_keys):
                    title += "  (" + ", ".join(kind_extension_keys) + ")"

            if output_json[key] in RtagsSymbolInfoCommand.MAP_KINDS:
                info = RtagsSymbolInfoCommand.MAP_KINDS[output_json[key]]

            displayed_items.append([title.strip(), info.strip()])

        displayed_html_items = list(map(self.display_items, displayed_items))

        info = '\n'.join(displayed_html_items)

        rendered = settings.SettingsManager.template_as_html("info", "popup", info)

        location = -1
        row = 0
        col = 0

        if 'col' in kwargs:
            row = kwargs['row']
            col = kwargs['col']
            location = self.view.text_point(kwargs['row'], kwargs['col'])

        file = self.view.file_name()

        self.view.show_popup(
            rendered,
            sublime.HIDE_ON_MOUSE_MOVE_AWAY,
            max_width=self.MAX_POPUP_WIDTH,
            max_height=self.MAX_POPUP_HEIGHT,
            location=location,
            on_navigate=self.on_navigate)

        jobs.JobController.run_async(
            jobs.RTagsJob(
                "RTFollowSymbolJob" + jobs.JobController.next_id(),
                [
                    '--absolute-path',
                    '-f',
                    '{}:{}:{}'.format(file, row + 1, col + 1)
                ]
            ),
            callback=partial(
                self.symbol_location_callback,
                displayed_items=displayed_items,
                oldrow=row,
                oldcol=col,
                oldfile=file))


class RtagsHoverInfo(sublime_plugin.EventListener):

    def on_hover(self, view, point, hover_zone):
        if hover_zone != sublime.HOVER_TEXT:
            return

        if not settings.SettingsManager.get("hover"):
            return

        (row, col) = view.rowcol(point)
        view.run_command(
            'rtags_symbol_info',
            {
                'switches': [
                    '--absolute-path',
                    '--json',
                    '--symbol-info'
                ],
                'col': col,
                'row': row
            })


class RtagsNavigationListener(sublime_plugin.EventListener):

    def cursor_pos(self, view, pos=None):
        if not pos:
            pos = view.sel()
            if len(pos) < 1:
                # something is wrong
                return None
            # we care about the first position
            pos = pos[0].a
        return view.rowcol(pos)

    def on_modified(self, view):
        if not supported_view(view):
            log.debug("Unsupported view")
            return
        fixits_controller.clear(view)
        idle_controller.trigger(view)

#    def on_selection_modified(self, view):
#        (row, col) = self.cursor_pos(view)
#        region = fixits_controller.cursor_region(view, row, col)
#        if region:
#            fixits_controller.show_fixit(view, region)

    def on_post_save(self, view):
        log.debug("Post save triggered")
        # Do nothing if not called from supported code.
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        # Do nothing if we dont want to support fixits.
        if not fixits_controller.supported:
            logging.debug("Fixits are disabled")
            # Run rc --check-reindex to reindex just saved files.
            # We do this manually even though rtags SHOULD watch
            # all our files and reindex accordingly. However on macOS
            # this feature is broken.
            # See https://github.com/Andersbakken/rtags/issues/1052
            jobs.JobsController.run_async(jobs.ReindexJob(
                "RTPostSaveReindex" + jobs.JobController.next_id(),
                view.file_name(),
                b'',
                view))
            return

        # For some bizarre reason, we need to delay our re-indexing task
        # by substantial amounts of time until we may relatively risk-
        # free will truly be attached to the lifetime of a
        # fully functioning `rc -V ... --wait`. `rc ... --wait` appears to
        # prevent concurrent instances by aborting the old "wait" when new
        # "wait"-request comes in.
        #sublime.set_timeout(lambda self=self,view=view: self._save(view), 400)

        #log.debug("Bizarrely delayed save scheduled")

        idle_controller.sleep()
        fixits_controller.reindex(view=view, saved=True)


    def on_post_text_command(self, view, command_name, args):
        # Do nothing if not called from supported code.
        if not supported_view(view):
            log.debug("Unsupported view")
            return

        # If view get 'clean' after undo check if we need reindex.
        if command_name == 'undo' and not view.is_dirty():

            if not fixits_controller.supported:
                logging.debug("Fixits are disabled")
                # Run rc --check-reindex to reindex just saved files.
                # We do this manually even though rtags SHOULD watch
                # all our files and reindex accordingly. However on macOS
                # this feature is broken.
                # See https://github.com/Andersbakken/rtags/issues/1052
                jobs.JobController.run_async(jobs.ReindexJob(
                    "RTPostUndoReindex" + jobs.JobController.next_id(),
                    view.file_name(),
                    b'',
                    view))
                return

            idle_controller.sleep()
            fixits_controller.reindex(view=view, saved=True)


class RtagsCompleteListener(sublime_plugin.EventListener):

    def __init__(self):
        self.suggestions = []
        self.completion_job_id = None
        self.view = None
        self.trigger_position = None

    def completion_done(self, future):
        log.debug("Completion done callback hit {}".format(future))

        if not future.done():
            log.warning("Completion failed")
            return

        if future.cancelled():
            log.warning(("Completion aborted"))
            return

        (completion_job_id, suggestions, error, view) = future.result()

        fixits_controller.signal_status(view=self.view, error=error)

        if error:
            log.debug("Completion job {} failed: {}".format(completion_job_id, error.message))
            return

        log.debug("Finished completion job {} for view {}".format(completion_job_id, view))

        if view != self.view:
            log.debug("Completion done for different view")
            return

        # Did we have a different completion in mind?
        if completion_job_id != self.completion_job_id:
            log.debug("Completion done for unexpected completion")
            return

        active_view = sublime.active_window().active_view()

        # Has the view changed since triggering completion?
        if view != active_view:
            log.debug("Completion done for inactive view")
            return

        # We accept both current position and position to the left of the
        # current word as valid as we don't know how much user already typed
        # after the trigger.
        current_position = view.sel()[0].a
        valid_positions = [current_position, view.word(current_position).a]

        if self.trigger_position not in valid_positions:
            log.debug("Trigger position {} does not match valid positions {}".format(
                valid_positions,
                self.trigger_position))
            return

        self.suggestions = suggestions

        #log.debug("suggestiongs: {}".format(suggestions))

        # Hide the completion we might currently see as those are sublime's
        # own completions which are not that useful to us C++ coders.
        #
        # This neat trick was borrowed from EasyClangComplete.
        view.run_command('hide_auto_complete')

        # Trigger a new completion event to show the freshly acquired ones.
        view.run_command('auto_complete', {
            'disable_auto_insert': True,
            'api_completions_only': False,
            'next_competion_if_showing': False})

    def on_query_completions(self, view, prefix, locations):
        # Check if autocompletion was disabled for this plugin.
        if not settings.SettingsManager.get('auto_complete', True):
            return []

        # Do nothing if not called from supported code.
        if not supported_view(view):
            return []

        log.debug("Completion prefix: {}".format(prefix))

        # libclang does auto-complete _only_ at whitespace and punctuation chars
        # so "rewind" location to that character
        trigger_position = locations[0] - len(prefix)

        pos_status = completion.position_status(trigger_position, view)

        if pos_status == completion.PositionStatus.WRONG_TRIGGER:
            # We are at a wrong trigger, remove all completions from the list.
            log.debug("Wrong trigger - hiding default completions")
            return ([], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)

        if pos_status == completion.PositionStatus.COMPLETION_NOT_NEEDED:
            log.debug("Completion not needed - showing default completions")
            return None

        # Render some unique identifier for us to match a completion request
        # to its original query.
        completion_job_id = "RTCompletionJob{}".format(trigger_position)

        # If we already have a completion for this position, show that.
        if self.completion_job_id == completion_job_id:
            log.debug("We already got a completion for this position available")
            return self.suggestions, sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS

        # Cancel a completion that might be in flight.
        if self.completion_job_id:
            jobs.JobController.stop(self.completion_job_id)

        # We do need to trigger a new completion.
        log.debug("Completion job {} triggered on view {}".format(completion_job_id, view))

        self.view = view
        self.completion_job_id = completion_job_id
        self.trigger_position = trigger_position
        row, col = view.rowcol(trigger_position)

        jobs.JobController.run_async(
            jobs.CompletionJob(
                completion_job_id,
                view.file_name(),
                get_view_text(view),
                view.size(),
                row,
                col,
                view),
            self.completion_done,
            progress_indicator)

        return ([], sublime.INHIBIT_WORD_COMPLETIONS | sublime.INHIBIT_EXPLICIT_COMPLETIONS)


def update_settings():
    settings.SettingsManager.update()

    if settings.SettingsManager.get('verbose_log', True):
        log.info("Enabled verbose logging")
        ch.setFormatter(formatter_verbose)
        ch.setLevel(logging.DEBUG)
    else:
        log.info("Enabled normal logging")
        ch.setFormatter(formatter_default)
        ch.setLevel(logging.INFO)

    # Initialize settings with their defaults.
    settings.SettingsManager.get('rc_timeout', 0.5)
    settings.SettingsManager.get('rc_path', "/usr/local/bin/rc")
    settings.SettingsManager.get('fixits', False)
    settings.SettingsManager.get('hover', False)
    settings.SettingsManager.get('auto_reindex', False)
    settings.SettingsManager.get('auto_reindex_threshold', 30)

    settings.SettingsManager.get('results_key', 'rtags_result_indicator')
    settings.SettingsManager.get('status_key', 'rtags_status_indicator')
    settings.SettingsManager.get('progress_key', 'rtags_progress_indicator')

    settings.SettingsManager.add_on_change('rc_timeout')
    settings.SettingsManager.add_on_change('rc_path')
    settings.SettingsManager.add_on_change('auto_complete')

    settings.SettingsManager.add_on_change('results_key')
    settings.SettingsManager.add_on_change('status_key')
    settings.SettingsManager.add_on_change('progress_key')

    # TODO(tillt): Allow "fixits" setting to get live-updated.
    #settings.add_on_change('fixits', update_settings)

    # TODO(tillt): Allow "verbose_log" settings to get live-updated.
    #settings.add_on_change('verbose_log', update_settings)

    log.info("Settings updated")


def init():
    update_settings()

    globals()['navigation_helper'] = NavigationHelper()
    globals()['progress_indicator'] = indicator.ProgressIndicator()
    globals()['fixits_controller'] = fixits.Controller(
        settings.SettingsManager.get('fixits'),
        progress_indicator)
    globals()['idle_controller'] = idle.Controller(
        settings.SettingsManager.get('auto_reindex'),
        settings.SettingsManager.get('auto_reindex_threshold'),
        partial(fixits.Controller.reindex, self=fixits_controller, saved=False))

def plugin_loaded():
    tools.Reloader.reload_all()
    sublime.set_timeout(init, 200)

def plugin_unloaded():
    jobs.JobController.stop_all()
