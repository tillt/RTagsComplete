
# About

Sublime Text 3 C/C++ code completion, navigation plugin. It is based on [rtags](https://github.com/Andersbakken/rtags).

# Installation

Make sure you Install `rtags`:

    git clone https://github.com/Andersbakken/rtags
    cd rtags
    mkdir build && cd build && cmake ..
    make install

### Via Package Control

* Install [Package Control](https://sublime.wbond.net/installation)
* Run “Package Control: Install Package”
* Install "RtagsComplete"

### Manually

    cd <sublime-text-Packages-dir>
    git clone https://github.com/rampage644/sublime-rtags

# Features

* Symbol navigation (Goto definition/declaration)
* Find usages (Find symbol references, Find virtual function re-implementations)
* Symbol information
* Code completion
* File compilation results after save - shows errors and fixits

# Usage

It is an unstable plugin. There are a number of limitations:

* You have to run `rdm` daemon manually. Better run it before Sublime starts, because plugin creates persistent connection to daemon
* There is no `rdm`'s project management yet. So it's your responsibility to setup project, pass compilation commands (with `rc --compile gcc main.c` or `rc -J`). For more info see [LLVM codebase](http://clang.llvm.org/docs/JSONCompilationDatabase.html), [rtags README](https://github.com/Andersbakken/rtags/blob/master/README.org), [Bear project](https://github.com/rizsotto/Bear/blob/master/README.md).
* It is recommended to install [rtags via homebrew](http://braumeister.org/repos/Homebrew/homebrew-core/formula/rtags) and then follow the instructions on how to run rdm

So, the typical workflow is:

 1. Start `rdm` (unless already started via launchd or brew services)
 2. Supply it with _JSON compilation codebase_ via `rc -J` or several `rc -c` calls.
 3. Start _Sublime Text 3_

# Default keybindings

Keybindings inspired by `Qt Creator`.

+ Symbol navigation - `F2`
+ Find usages - `Ctrl+Shift+u`
+ Find virtual function re-implementations - `Ctrl+Shift+x`
+ Symbol information - `Ctrl+Shift+i`
+ Use `Alt+/` explicitly for auto-completion
+ Mouse _button8_ to go backwards (mouse wheel left)

# Customization

### Keybindings

Customize your own keybindings via "Preferences - Package Settings - SublimeRtags - Key Bindings - User"

```
[
  {"keys": ["ctrl+shift+u"], "command": "rtags_location", "args": {"switches": ["--absolute-path", "-r"]} },
  {"keys": ["ctrl+shift+x"], "command": "rtags_location", "args": {"switches": ["--absolute-path", "-k", "-r"]} },
  {"keys": ["ctrl+shift+i"], "command": "rtags_symbol_info", "args": {"switches": ["--absolute-path", "--symbol-info"]} },
  {"keys": ["f2"], "command": "rtags_location", "args": {"switches": ["--absolute-path", "-f"]} },
  {"keys": ["ctrl+shift+b"], "command": "rtags_go_backward" },
]
```

### Settings

Customize settings via "Preferences - Package Settings - SublimeRtags - Settings - User"

```
{
  /* Path to rc utility if not found in $PATH */
  "rc_path": "/home/ramp/mnt/git/rtags/build/bin/rc",

  /* Seconds for rc utility communication timeout default */
  "rc_timeout": 0.5,

  /* Max number of jump steps */
  "jump_limit": 10,

  /* Supported source file types */
  "file_types": ["source.c", "source.c++", "source.c++.11"],

  /* Statusbar indicator key - sorting is done alphabetically */
  "status_key": "rtags_status_indicator"
}
```

If you need auto-completion to trigger upon `.`, `->` or `::` add following to "Preferences - Settings - User"

```
  "auto_complete_triggers":
  [
    {
      "characters": ".>:",
      "selector": "text, source, meta, string, punctuation, constant"
    }
  ]
```

# Further reading

For a typical setup of a larger codebase built via autotools, check out [Simplify development by adding RTags to your text editor](https://mesosphere.com/blog/simplify-development-by-adding-rtags-to-your-text-editor/).

