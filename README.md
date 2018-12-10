
```
      ___       ___          ___          ___          ___
     /\  \     /\  \        /\  \        /\  \        /\  \
    /::\  \    \:\  \      /::\  \      /::\  \      /::\  \
   /:/\:\  \    \:\  \    /:/\:\  \    /:/\:\  \    /:/\ \  \
  /::\~\:\  \   /::\  \  /::\~\:\  \  /:/  \:\  \  _\:\~\ \  \
 /:/\:\ \:\__\ /:/\:\__\/:/\:\ \:\__\/:/__/_\:\__\/\ \:\ \ \__\
 \/_|::\/:/  //:/  \/__/\/__\:\/:/  /\:\  /\ \/__/\:\ \:\ \/__/
    |:|::/  //:/  /          \::/  /  \:\ \:\__\   \:\ \:\__\
    |:|\/__/ \/__/           /:/  /    \:\/:/  /    \:\/:/  /
    |:|  |                  /:/  /      \::/  /      \::/  /
     \|__|                  \/__/        \/__/        \/__/
      ___          ___          ___          ___                    ___                 ___
     /\__\        /\  \        /\  \        /\  \                  /\__\               /\__\
    /:/  /       /::\  \      |::\  \      /::\  \                /:/ _/_       ___   /:/ _/_
   /:/  /       /:/\:\  \     |:|:\  \    /:/\:\__\              /:/ /\__\     /\__\ /:/ /\__\
  /:/  /  ___  /:/  \:\  \  __|:|\:\  \  /:/ /:/  /___     ___  /:/ /:/ _/_   /:/  //:/ /:/ _/_
 /:/__/  /\__\/:/__/ \:\__\/::::|_\:\__\/:/_/:/  //\  \   /\__\/:/_/:/ /\__\ /:/__//:/_/:/ /\__\
 \:\  \ /:/  /\:\  \ /:/  /\:\~~\  \/__/\:\/:/  / \:\  \ /:/  /\:\/:/ /:/  //::\  \\:\/:/ /:/  /
  \:\  /:/  /  \:\  /:/  /  \:\  \       \::/__/   \:\  /:/  /  \::/_/:/  //:/\:\  \\::/_/:/  /
   \:\/:/  /    \:\/:/  /    \:\  \       \:\  \    \:\/:/  /    \:\/:/  / \/__\:\  \\:\/:/  /
    \::/  /      \::/  /      \:\__\       \:\__\    \::/  /      \::/  /       \:\__\\::/  /
     \/__/        \/__/        \/__/        \/__/     \/__/        \/__/         \/__/ \/__/
```

Master [![Build Status](https://travis-ci.org/tillt/RTagsComplete.svg?branch=master)](https://travis-ci.org/tillt/RTagsComplete) Staging [![Build Status](https://travis-ci.org/tillt/RTagsComplete.svg?branch=staging)](https://travis-ci.org/tillt/RTagsComplete)

# About

Sublime Text 3 C/C++ code completion, navigation plugin based on [RTags](https://github.com/Andersbakken/rtags).

This is a fork of the original [sublime-rtags](https://github.com/rampage644/sublime-rtags) by Sergei Turukin. New features have been added and merging those back into the original sublime-rtags has become a bottleneck this fork avoids.

# Installation

Make sure you installed RTags - for all of the latest features, version 2.19 is the oldest we support. You will however get most functionality with RTags version 2.0 already.

### Via Package Control

- Install [Package Control](https://sublime.wbond.net/installation)
- Run “Package Control: Install Package”
- Install "RTagsComplete"

### Manually

    cd <sublime-text-Packages-dir>
    git clone https://github.com/tillt/RTagsComplete

# Features

## Symbol navigation (Goto definition/declaration)

Jump to the definition or declaration of a symbol.

## Find usages (Find symbol references, Find virtual function re-implementations)

Shows all references of the symbol under the cursor.

## Find unused functions

Finds and displays dead functions.

## Rename symbol

Allows to refactor symbols. Select a symbol with your cursor, activate the function and enter the new name.

## Find include

Finds the include file for the symbol under the cursor. If any are found, shows a quick panel that copies the selected include into the clipboard when hitting return.

## Symbol information

Shows a popup containing information about the symbol under the cursor.

![Symbol Info Example](site/images/symbol_info.png)

## Code completion

![Completion Example](site/images/completion.png)

## Code validation

Validates your current code and shows errors and warnings inline.

![Fixits Example](site/images/fixits.png)

# Usage

## Typical work-flow

- [Make sure `rdm` is active](https://github.com/tillt/RTagsComplete/wiki/Make-sure-rdm-is-active).
- [Obtain compile_commands.json from the build chain of your project/s](https://github.com/tillt/RTagsComplete/wiki/Obtaining-compile_commands.json).
- [Supply rdm with compile_commands.json of your project/s](https://github.com/tillt/RTagsComplete/wiki/Supply-rdm-with-compile_commands.json).
- That's it - ready to code with ease.

# Default key bindings

Key bindings were originally inspired by Qt Creator.

+ Symbol navigation - `F2`
+ Find usages - `Ctrl+Shift+u`
+ Rename symbol - `Ctrl+Shift+Alt+u`
+ Find virtual function re-implementations - `Ctrl+Shift+x`
+ Symbol information - `Ctrl+Shift+i`
+ Use `Alt+/` explicitly for auto-completion
+ Mouse _button8_ to go backwards (mouse wheel left)
+ Error, fixit and warning navigation - `Ctrl-Shift-e`
+ Find unused functions - `Alt-Super-Shift-d`
+ Find include file for symbol - `Ctrl+i`
+ Show navigation history - `Ctrl+Shift+h`

# Customization

### Keybindings

Customize your own key bindings via *Preferences* > *Package Settings* > *RTagsComplete* > *Key Bindings* > *User*

```python
[
  # Find usages
  {"keys": ["ctrl+shift+u"], "command": "rtags_location", "args": {"switches": ["--absolute-path", "-r"]} },

  # Rename symbol
  {"keys": ["ctrl+shift+alt+u"], "command": "rtags_symbol_rename", "args": {"switches": ["--absolute-path", "--rename", "-e", "-r"]} },

  # Find virtual function re-implementations
  {"keys": ["ctrl+shift+x"], "command": "rtags_location", "args": {"switches": ["--absolute-path", "-k", "-r"]} },

  # Symbol information - needs RTags version 2.5 or higher.
  {"keys": ["ctrl+shift+i"], "command": "rtags_symbol_info", "args": {"switches": ["--absolute-path", "--json", "--symbol-info"]} },

  # Get include file.
  { "keys": ["ctrl+i"], "command": "rtags_get_include" },

  # Jump to definition
  {"keys": ["f2"], "command": "rtags_location", "args": {"switches": ["--absolute-path", "-f"]} },

  # Backwards in history
  {"keys": ["ctrl+shift+b"], "command": "rtags_go_backward" },

  # Show navigation history
  {"keys": ["ctrl+shift+h"], "command": "rtags_show_history" },

  # Show errors, warnings and fixits
  {"keys": ["ctrl+shift+e"], "command": "rtags_show_fixits" },

  # Find unused / dead functions - needs RTags version 2.19 or higher.
  {"keys": ["alt+super+shift+d"], "command": "rtags_file", "args": {"switches": ["--absolute-path", "--find-dead-functions"]} }
]
```

### Settings

Customize settings via *Preferences* > *Package Settings* > *RTagsComplete* > *Settings* > *User*

```python
{
  # Path to rc utility if not found in $PATH.
  "rc_path": "/usr/local/bin/rc",

  # Seconds for rc utility communication timeout default.
  "rc_timeout": 0.5,

  # max number of jump steps.
  "jump_limit": 10,

  # Supported source file types.
  "file_types": ["source.c", "source.c++", "source.c++.11"],

  # Statusbar status key - sorting is done alphabetically.
  "status_key": "000000_rtags_status",

  # Statusbar results key - sorting is done alphabetically.
  "results_key": "000001_rtags_status",

  # Statusbar progress indicator key - sorting is done alphabetically.
  "progress_key": "000002_rtags_status",

  # Enable auto-completion.
  "auto_complete": true,

  # Auto-completion triggers internal to RTagsComplete.
  "triggers" : [ ".", "->", "::", " ", "  ", "(", "[" ],

  # Enable displaying fixits, warnings and errors.
  "fixits": true,

  # Enable hover symbol info - needs at least RTags V2.5.
  "hover": true,

  # Enable enhanced, rather verbose logging for troubleshooting.
  "verbose_log": true,

  # Enable auto-reindex unsaved file.
  "auto_reindex": true,

  # Seconds of idle-time before auto-reindex is triggered.
  "auto_reindex_threshold": 30,

  # clang cursor kind as returned by RTags not adding value to the
  # symbol information popup.
  "filtered_clang_cursor_kind": [
    "arguments",
    "baseClasses",
    "cf",
    "cfl",
    "cflcontext",
    "context",
    "endLine",
    "endColumn",
    "functionArgumentCursor",
    "functionArgumentLength",
    "functionArgumentLocation",
    "functionArgumentLocationContext",
    "invocation",
    "invocationContext",
    "invokedFunction",
    "location",
    "parent",
    "range",
    "startLine",
    "startColumn",
    "symbolLength",
    "usr",
    "xmlComment"
  ]
}
```

If you need auto-completion add following to *Preferences* > *Settings* > *User*

```json
"auto_complete_triggers":
[
  {
    "characters": "<",
    "selector": "text.html"
  },{
    "characters": ".>: ",
    "selector": "source.c++.11, source.c++, source.c - string - comment - constant.numeric"
  }
]
```

# Further reading

For a typical setup of a larger codebase built via autotools, check out [Simplify development by adding RTags to your text editor](https://mesosphere.com/blog/simplify-development-by-adding-rtags-to-your-text-editor/).

# Credits

Original code by Sergei Turukin.
Hacked with plenty of new features by [Till Toenshoff](https://twitter.com/ttoenshoff).
Some code lifted from EasyClangComplete by Igor Bogoslavskyi.

On that thought, I would like to mention that EasyClangComplete is an excellent plugin, far more complex and in many ways superior to RTagsComplete. However, the approach taken by EasyClangComplete is arguably not so great for larger projects. EasyClangComplete aims to make things conveniently easy while RTagsComplete is attempting to offer plenty of features with highest possible performance at scale.
Maybe some day EasyClangComplete will be based on `clangd` and that is likely the day I stop tinkering with RTagsComplete.
