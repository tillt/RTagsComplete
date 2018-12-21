# -*- coding: utf-8 -*-

"""Symbol Info handling.

.

"""

import sublime

import html
import json
import logging
import re

from functools import partial

from . import jobs
from . import settings
from . import vc_manager

log = logging.getLogger("RTags")


class Category:
    WARNING = "warning"
    ERROR = "error"


class Controller:
    MAX_POPUP_WIDTH = 1800
    MAX_POPUP_HEIGHT = 900

    CATEGORIES = [Category.WARNING, Category.ERROR]

    CATEGORY_FLAGS = {
        Category.WARNING: sublime.DRAW_NO_FILL,
        Category.ERROR: sublime.DRAW_NO_FILL
    }

    PHANTOMS_TAG = "rtags_phantoms"

    # Camelcase doesn't look so nice on interfaces.
    MAP_TITLES = {
        'argumentIndex':            'argument index',
        'briefComment':             'brief comment',
        'constmethod':              'const method',
        'fieldOffset':              'field offset',
        'purevirtual':              'pure virtual',
        'macroexpansion':           'macro expansion',
        'templatespecialization':   'template specialization',
        'templatereference':        'template reference',
        'staticmethod':             'static method',
        'stackCost':                'size on stack',
        'symbolName':               'name'
    }

    # Prefixed positions.
    POSITION_TITLES = {
        'symbolName':   '0',
        'briefComment': '1',
        'type':         '2',
        'kind':         '3',
        'linkage':      '4',
        'sizeof':       '5'
    }

    # Kind extensions.
    # TODO(tillt): Find a complete list of possible boolean kind extensions.
    KIND_EXTENSION_BOOL_TYPES = [
        'auto',
        'virtual',
        'container',
        'definition',
        'reference',
        'staticmethod',
        'templatereference'
    ]

    # Human readable type descriptions of clang's cursor linkage types.
    # Extracted from
    # https://raw.githubusercontent.com/llvm-mirror/clang/master/include/clang-c/Index.h
    MAP_LINKAGES = {
        'NoLinkage': 'Variables, parameters, and so on that have automatic'
        ' storage.',
        'Internal': 'Static variables and static functions.',
        'UniqueExternal': 'External linkage that live in C++ anonymous'
        ' namespaces.',
        'External': 'True, external linkage.',
        # 'Invalid' just means that there is no information available -
        # skip this entry when displaying.
        'Invalid': ''
    }

    # Human readable type descriptions of clang's cursor kind types.
    # Extracted from https://raw.githubusercontent.com/llvm-mirror/clang/master/include/clang-c/Index.h
    MAP_KINDS = {
        'UnexposedDecl': 'A declaration whose specific kind is not'
        ' exposed via this interface.',
        'StructDecl': 'A C or C++ struct.',
        'UnionDecl': 'A C or C++ union.',
        'ClassDecl': 'A C++ class.',
        'EnumDecl': 'An enumeration.',
        'FieldDecl': 'A field (in C) or non-static data member (in C++)'
        ' in a struct, union, or C++ class.',
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
        'ObjCCategoryImplDecl': 'An Objective-C @implementation for a'
        ' category.',
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
        'ClassTemplatePartialSpecialization': 'A C++ class template partial'
        ' specialization.',
        'NamespaceAlias': 'A C++ namespace alias declaration.',
        'UsingDirective': 'A C++ using directive.',
        'UsingDeclaration': 'A C++ using declaration.',
        'TypeAliasDecl': 'A C++ alias declaration',
        'ObjCSynthesizeDecl': 'An Objective-C @synthesize definition.',
        'ObjCDynamicDecl': 'An Objective-C @dynamic definition.',
        'CXXAccessSpecifier': 'An access specifier.',
        'TypeRef': 'A reference to a type declaration.',
        'TemplateRef': 'A reference to a class template, function'
        ' template, template template parameter, or class template'
        ' partial specialization.',
        'NamespaceRef': 'A reference to a namespace or namespace alias.',
        'MemberRef': 'A reference to a member of a struct, union, or'
        ' class that occurs in some non-expression context, e.g., a'
        ' designated initializer.',
        'LabelRef': 'A reference to a labeled statement.',
        'OverloadedDeclRef': 'A reference to a set of overloaded functions'
        ' or function templates that has not yet been resolved to a'
        ' specific function or function template.',
        'VariableRef': 'A reference to a variable that occurs in some'
        ' non-expression context, e.g., a C++ lambda capture list.',
        'UnexposedExpr': 'An expression whose specific kind is not'
        ' exposed via this interface.',
        'DeclRefExpr': 'An expression that refers to some value'
        ' declaration, such as a function, variable, or enumerator.',
        'MemberRefExpr': 'An expression that refers to a member of a'
        ' struct, union, class, Objective-C class, etc.',
        'CallExpr': 'An expression that calls a function.',
        'ObjCMessageExpr': 'An expression that sends a message to an'
        ' Objective-C object or class.',
        'BlockExpr': 'An expression that represents a block literal.',
        'IntegerLiteral': 'An integer literal.',
        'FloatingLiteral': 'A floating point number literal.',
        'ImaginaryLiteral': 'An imaginary number literal.',
        'StringLiteral': 'A string literal.',
        'CharacterLiteral': 'A character literal.',
        'ParenExpr': 'A parenthesized expression, e.g. \"(1)\".',
        'UnaryOperator': 'This represents the unary-expression\'s (except'
        ' sizeof and alignof).',
        'ArraySubscriptExpr': '[C99 6.5.2.1] Array Subscripting.',
        'BinaryOperator': 'A builtin binary operation expression such'
        ' as "x + y" or "x <= y".',
        'CompoundAssignOperator': 'Compound assignment such as "+=".',
        'ConditionalOperator': 'The ?: ternary operator.',
        'CStyleCastExpr': 'An explicit cast in C (C99 6.5.4) or a C-style'
        ' cast in C++ (C++ [expr.cast]), which uses the syntax (Type)expr.',
        'CompoundLiteralExpr': '[C99 6.5.2.5]',
        'InitListExpr': 'Describes an C or C++ initializer list.',
        'AddrLabelExpr': 'The GNU address of label extension, representing'
        ' &&label.',
        'StmtExpr': 'This is the GNU Statement Expression extension:'
        ' ({int X=4; X;}).',
        'GenericSelectionExpr': 'Represents a C11 generic selection.',
        'GNUNullExpr': 'Implements the GNU __null extension, which is a'
        ' name for a null pointer constant that has integral type (e.g.,'
        ' int or long) and is the same size and alignment as a pointer.',
        'CXXStaticCastExpr': 'C++\'s static_cast<> expression.',
        'CXXDynamicCastExpr': 'C++\'s dynamic_cast<> expression.',
        'CXXReinterpretCastExpr': 'C++\'s reinterpret_cast<> expression.',
        'CXXConstCastExpr': 'C++\'s const_cast<> expression.',
        'CXXFunctionalCastExpr': 'Represents an explicit C++ type'
        ' conversion that uses \"functional\" notion (C++ [expr.type.conv]).',
        'CXXTypeidExpr': 'A C++ typeid expression (C++ [expr.typeid]).',
        'CXXBoolLiteralExpr': '[C++ 2.13.5] C++ Boolean Literal.',
        'CXXNullPtrLiteralExpr': '[C++0x 2.14.7] C++ Pointer Literal.',
        'CXXThisExpr': 'Represents the "this" expression in C++',
        'CXXThrowExpr': '[C++ 15] C++ Throw Expression.',
        'CXXNewExpr': 'A new expression for memory allocation and'
        ' constructor calls, e.g: \"new CXXNewExpr(foo)\".',
        'CXXDeleteExpr': 'A delete expression for memory deallocation'
        ' and destructor calls, e.g. \"delete[] pArray\".',
        'UnaryExpr': 'A unary expression. (noexcept, sizeof, or other traits)',
        'ObjCStringLiteral': 'An Objective-C string literal i.e. "foo".',
        'ObjCEncodeExpr': 'An Objective-C @encode expression.',
        'ObjCSelectorExpr': 'An Objective-C @selector expression.',
        'ObjCProtocolExpr': 'An Objective-C @protocol expression.',
        'ObjCBridgedCastExpr': 'An Objective-C "bridged" cast expression,'
        ' which casts between Objective-C pointers and C pointers,'
        ' transferring ownership in the process.',
        'PackExpansionExpr': 'Represents a C++0x pack expansion that'
        ' produces a sequence of expressions.',
        'SizeOfPackExpr': 'Represents an expression that computes the'
        ' length of a parameter pack.',
        'ObjCBoolLiteralExpr': 'Objective-c Boolean Literal.',
        'ObjCSelfExpr': 'Represents the "self" expression in an'
        ' Objective-C method.',
        'OMPArraySectionExpr': 'OpenMP 4.0 [2.4, Array Section].',
        'ObjCAvailabilityCheckExpr': 'Represents an (...) check.',
        'FixedPointLiteral': 'Fixed point literal.',
        'UnexposedStmt': 'A statement whose specific kind is not exposed'
        ' via this interface.',
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
        'ObjCAtTryStmt': 'Objective-C\'s overall @try-@catch-@finally'
        ' statement.',
        'ObjCAtCatchStmt': 'Objective-C\'s @catch statement.',
        'ObjCAtFinallyStmt': 'Objective-C\'s @finally statement.',
        'ObjCAtThrowStmt': 'Objective-C\'s @throw statement.',
        'ObjCAtSynchronizedStmt': 'Objective-C\'s @synchronized statement.',
        'ObjCAutoreleasePoolStmt': 'Objective-C\'s autorelease pool'
        ' statement.',
        'ObjCForCollectionStmt': 'Objective-C\'s collection statement.',
        'CXXCatchStmt': 'C++\'s catch statement.',
        'CXXTryStmt': 'C++\'s try statement.',
        'CXXForRangeStmt': 'C++\'s for (* : *) statement.',
        'SEHTryStmt': 'Windows Structured Exception Handling\'s try'
        ' statement.',
        'SEHExceptStmt': 'Windows Structured Exception Handling\'s except'
        ' statement.',
        'SEHFinallyStmt': 'Windows Structured Exception Handling\'s'
        ' finally statement.',
        'MSAsmStmt': 'A MS inline assembly statement extension.',
        'NullStmt': 'The null statement ";": C99 6.8.3p3.',
        'DeclStmt': 'Adaptor class for mixing declarations with statements'
        ' and expressions.',
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
        'SEHLeaveStmt': 'Windows Structured Exception Handling\'s leave'
        ' statement.',
        'OMPOrderedDirective': 'OpenMP ordered directive.',
        'OMPAtomicDirective': 'OpenMP atomic directive.',
        'OMPForSimdDirective': 'OpenMP for SIMD directive.',
        'OMPParallelForSimdDirective': 'OpenMP parallel for SIMD directive.',
        'OMPTargetDirective': 'OpenMP target directive.',
        'OMPTeamsDirective': 'OpenMP teams directive.',
        'OMPTaskgroupDirective': 'OpenMP taskgroup directive.',
        'OMPCancellationPointDirective': 'OpenMP cancellation point'
        ' directive.',
        'OMPCancelDirective': 'OpenMP cancel directive.',
        'OMPTargetDataDirective': 'OpenMP target data directive.',
        'OMPTaskLoopDirective': 'OpenMP taskloop directive.',
        'OMPTaskLoopSimdDirective': 'OpenMP taskloop simd directive.',
        'OMPDistributeDirective': 'OpenMP distribute directive.',
        'OMPTargetEnterDataDirective': 'OpenMP target enter data directive.',
        'OMPTargetExitDataDirective': 'OpenMP target exit data directive.',
        'OMPTargetParallelDirective': 'OpenMP target parallel directive.',
        'OMPTargetParallelForDirective': 'OpenMP target parallel for'
        ' directive.',
        'OMPTargetUpdateDirective': 'OpenMP target update directive.',
        'OMPDistributeParallelForDirective': 'OpenMP distribute parallel'
        ' for directive.',
        'OMPDistributeParallelForSimdDirective': 'OpenMP distribute'
        ' parallel for simd directive.',
        'OMPDistributeSimdDirective': 'OpenMP distribute simd directive.',
        'OMPTargetParallelForSimdDirective': 'OpenMP target parallel for'
        ' simd directive.',
        'OMPTargetSimdDirective': 'OpenMP target simd directive.',
        'OMPTeamsDistributeDirective': 'OpenMP teams distribute directive.',
        'OMPTeamsDistributeSimdDirective': 'OpenMP teams distribute simd'
        ' directive.',
        'OMPTeamsDistributeParallelForSimdDirective': 'OpenMP teams'
        ' distribute parallel for simd directive.',
        'OMPTeamsDistributeParallelForDirective': 'OpenMP teams distribute'
        ' parallel for directive.',
        'OMPTargetTeamsDirective': 'OpenMP target teams directive.',
        'OMPTargetTeamsDistributeDirective': 'OpenMP target teams'
        ' distribute directive.',
        'OMPTargetTeamsDistributeParallelForDirective': 'OpenMP target'
        ' teams distribute parallel for directive.',
        'OMPTargetTeamsDistributeParallelForSimdDirective': 'OpenMP'
        ' target teams distribute parallel for simd directive.',
        'OMPTargetTeamsDistributeSimdDirective': 'OpenMP target teams'
        ' distribute simd directive.',
        'TranslationUnit': 'Cursor that represents the translation unit'
        ' itself.',
        'UnexposedAttr': 'An attribute whose specific kind is not exposed'
        ' via this interface.',
        'ModuleImportDecl': 'A module import declaration.',
        'StaticAssert': 'A static_assert or _Static_assert node.',
        'FriendDecl': 'A friend declaration.',
        'OverloadCandidate': 'A code completion overload candidate.',

        #
        # Aliases or unexpexted but received results.
        # Aliases apparently change over time in clang's internal usage.
        #

        # This one should in theory come back from RTags on auto->build-in.
        # See https://github.com/Andersbakken/rtags/commit/3b8b9d51cec478e566b86d74659c78ac2b73ae4f.
        'NoDeclFound': 'Build-in type probably.',

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

    @staticmethod
    def display_items(item):
        return "<div class=\"info\"><span class=\"header\">{}</span>" \
               "<br /><span class=\"info\">{}</span></div>".format(
                    html.escape(item[0], quote=False),
                    html.escape(item[1], quote=False))

    @staticmethod
    def symbol_location_callback(
            future,
            view,
            displayed_items,
            oldrow,
            oldcol,
            oldfile):
        log.debug("Symbol location callback hit {}".format(future))
        if not future.done():
            log.warning("Symbol location failed")
            return
        if future.cancelled():
            log.warning(("Symbol location aborted"))
            return

        (job_id, out, error) = future.result()

        vc_manager.view_controller(view).status.update_status(error=error)

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
            r'(\S+):(\d+):(\d+):(.*)',
            items[0])[0]

        link = "{}:{}:{}:{}:{}:{}".format(
            oldfile,
            oldrow,
            oldcol,
            file,
            row,
            col)

        log.debug("Symbol location resulted in {}".format(link))

        info = "<div class=\"info\"><span class=\"header\">{}</span>" \
               "<br /><a href=\"{}\">{}</a></div>\n".format(
                    html.escape(displayed_items[0][0], quote=False),
                    html.escape(link, quote=False),
                    html.escape(displayed_items[0][1], quote=False))

        displayed_html_items = list(map(
            Controller.display_items,
            displayed_items[1:]))

        info += '\n'.join(displayed_html_items)

        rendered = settings.template_as_html(
            "info",
            "popup",
            info)

        view.update_popup(rendered)

    @staticmethod
    def action(view, row, col, out):
        output_json = json.loads(out.decode("utf-8"))

        # Naive filtering, translation and sorting.
        priority_lane = {}
        alphabetic_keys = []
        kind_extension_keys = []

        filtered_kind = settings.get(
            "filtered_clang_cursor_kind",
            [])

        for key in output_json.keys():
            # Do not include filtered cursor kind keys.
            if key not in filtered_kind:
                # Check if boolean type does well as a kind extension.
                if key in Controller.KIND_EXTENSION_BOOL_TYPES:
                    if output_json[key]:
                        title = key
                        if key in Controller.MAP_TITLES:
                            title = Controller.MAP_TITLES[key]
                        kind_extension_keys.append(title)
                else:
                    if key in Controller.POSITION_TITLES.keys():
                        priority_lane[Controller.POSITION_TITLES[key]]=key
                    else:
                        alphabetic_keys.append(key)

        # Render a list of keys in the order we want to see;
        # 1st: All the priorized keys, in their exact order.
        # 2nd: All remaining keys, in alphabetic order.
        sorted_keys = []

        for index in sorted(priority_lane.keys()):
            sorted_keys.append(priority_lane[index])

        sorted_keys.extend(sorted(alphabetic_keys))

        if len(kind_extension_keys) > 1:
            kind_extension_keys = sorted(kind_extension_keys)

        displayed_items = []

        for key in sorted_keys:
            title = key
            info = str(output_json[key])

            if key in Controller.MAP_TITLES:
                title = Controller.MAP_TITLES[key]

            if key == "kind":
                if len(kind_extension_keys):
                    title += "  (" + ", ".join(kind_extension_keys) + ")"

                if output_json[key] in Controller.MAP_KINDS:
                    info = Controller.MAP_KINDS[output_json[key]]
            elif key == "linkage":
                if output_json[key] in Controller.MAP_LINKAGES:
                    info = Controller.MAP_LINKAGES[output_json[key]]
                if not len(info):
                    continue
            displayed_items.append([title.strip(), info.strip()])

        displayed_html_items = list(map(
            Controller.display_items,
            displayed_items))

        info = '\n'.join(displayed_html_items)

        rendered = settings.template_as_html(
            "info",
            "popup",
            info)

        location = view.text_point(row, col)

        file = view.file_name()

        def on_navigate(href):
            (oldfile, oldline, oldcol, file, line, col) = re.findall(
                r'(\S+):(\d+):(\d+):(\S+):(\d+):(\d+)',
                href)[0]

            vc_manager.navigate(
                view,
                oldfile,
                oldline,
                oldcol,
                file,
                line,
                col)

        view.show_popup(
            rendered,
            sublime.HIDE_ON_MOUSE_MOVE_AWAY,
            max_width=Controller.MAX_POPUP_WIDTH,
            max_height=Controller.MAX_POPUP_HEIGHT,
            location=location,
            on_navigate=on_navigate)

        jobs.JobController.run_async(
            jobs.RTagsJob(
                "RTFollowSymbolJob" + jobs.JobController.next_id(),
                [
                    '--absolute-path',
                    '-f',
                    '{}:{}:{}'.format(file, row + 1, col + 1),
                ],
                **{'view': view}
            ),
            partial(
                Controller.symbol_location_callback,
                view=view,
                displayed_items=displayed_items,
                oldrow=row,
                oldcol=col,
                oldfile=file),
            vc_manager.view_controller(view).status.progress)
