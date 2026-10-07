<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell user guide

NodePhell is an early prototype for running Python projects without virtual
environments. A project says which Python and packages it needs. NodePhell puts
missing items in shared storage, then its `python` and `python3` launchers choose
the right ones whenever that project runs.

## Install the launchers

From a checkout, install `nodephell`, `python`, and `python3` into the standard
per-user command directory:

```console
/path/to/NodePhell/bin/nodephell launcher install
```

The command reports when `~/.local/bin` is missing from `PATH` or loses to
another command directory. The two Python launchers are identical. They point
at the checkout that installed them, so reinstall after moving that checkout.

`nodephell launcher uninstall` removes only launchers marked as installed by
NodePhell. It leaves runtimes, hosts, packages, project records, and the source
checkout untouched. Installation and removal refuse to overwrite or delete an
unrelated command with the same name.

## Prepare a project

NodePhell looks for `pylock.toml` or `pyproject.toml`. A minimal
`pyproject.toml` looks like this:

```toml
[project]
name = "example"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
    "lark==1.3.1",
    "requests==2.32.5",
]
```

Direct dependencies must currently have exact versions. From the project
directory, create the lock and provision it once:

```console
nodephell lock
nodephell install
```

`lock` chooses an exact Python build, asks stock pip for the complete dependency
list, and writes `pylock.toml`. `install` follows that lock and downloads
anything missing. Keep the lock with the project if another machine should
select the same downloads.

After that, use Python normally:

```console
python app.py
python3 -m unittest
python -c 'import requests; print(requests.__version__)'
```

There is no activation command and nothing needs to be repeated in each new
terminal. After changing project requirements, run `nodephell update` and then
`nodephell install`.

## What the launcher does

Inside a project, `python` and `python3`:

1. find the project by looking upward from the working directory or script;
2. select the exact locked interpreter and package downloads;
3. start that interpreter with only the selected shared package view.

An inherited `PYTHONPATH` and Python's generic user-site directory are ignored
for project launches. This prevents unrelated user-installed packages from
leaking into the project. NodePhell's explicitly selected package directories
remain available.

Outside a recognized project, the launcher passes control to the operating
system Python without changing it. `/usr/bin/python3` is always a direct bypass
on systems where it is provided there.

## Command reference

Run `nodephell --help` (or `-h`) for the short command list, or add `--help`
after a command group such as `nodephell runtime --help`. `nodephell --version`
(or `-V`) prints the NodePhell version.

```text
nodephell install [PROJECT]
nodephell lock [PROJECT]
nodephell update [PROJECT]
nodephell run [--] PYTHON-ARGS
nodephell resolve [--] PYTHON-ARGS
nodephell launcher install
nodephell launcher uninstall
nodephell runtime add PYTHON [--library-path DIRECTORY]...
nodephell runtime install SPEC
nodephell runtime remove [--delete] PYTHON
nodephell runtime list
nodephell project list
nodephell project move OLD NEW
nodephell project remove [PROJECT]
nodephell store check
nodephell store clean [--apply]
nodephell host add [--kind KIND] EXECUTABLE
nodephell host remove [--delete] EXECUTABLE
nodephell host list
nodephell host adapters
nodephell host run [--] HOST-ARGS
nodephell host gui [--] HOST-ARGS
```

### `python` and `python3`

These are identical NodePhell launchers. They accept normal Python arguments:

```console
python app.py input.txt
python3 -m unittest
python -c 'import requests; print(requests.__version__)'
python -i app.py
```

Within a project they use its locked runtime and packages. Outside a project
they delegate to the system Python. They do not install missing items; if a
locked item is unavailable, run `nodephell install`.

### Lock, install, and update

`PROJECT` is optional and defaults to the current directory.

```console
nodephell lock
nodephell install
nodephell update /work/example
```

`lock` creates `pylock.toml` from `pyproject.toml` and refuses to replace an
existing lock. `install` requires that lock, follows it exactly, and reuses
already available items. `update` requires both files and deliberately
re-resolves from `pyproject.toml`; it replaces the lock only after resolution
succeeds. Run `install` afterward to supply the updated lock state.

### `nodephell run [--] PYTHON-ARGS`

Run Python through NodePhell. This is the explicit form of the `python` shim.

```console
nodephell run app.py
nodephell run -- -c 'print("hello")'
```

The optional `--` clearly separates NodePhell arguments from Python arguments
that begin with a dash.

### `nodephell resolve [--] PYTHON-ARGS`

Show the selection as JSON without starting Python:

```console
nodephell resolve
nodephell resolve app.py
nodephell resolve -- -m unittest
```

The result names the discovered project and metadata file, selected Python,
runtime artifact, library paths, combined package view, and any packages reused
from the selected interpreter. `system_fallback: true` means no project was
found and the system Python would be used.

### Runtime commands

`nodephell runtime list` shows the Python running NodePhell as `bootstrap`, then
every separately registered interpreter.

`nodephell runtime install SPEC` downloads, verifies, and registers a matching
stock CPython build. Quote requirements containing shell punctuation:

```console
nodephell runtime install '>=3.13,<3.14'
nodephell runtime list
```

`nodephell runtime add PYTHON` probes and registers an interpreter already on
the machine:

```console
nodephell runtime add /opt/python/bin/python3.13
```

Some locally built interpreters need a shared-library directory to start. Add
it with `--library-path`; repeat the option when more than one is needed:

```console
nodephell runtime add /opt/python/bin/python3.13 \
  --library-path /opt/python/lib \
  --library-path /opt/other/lib
```

Register the installed interpreter, not its source or compiler build
directory. NodePhell verifies its identity by running it.

`nodephell runtime remove PYTHON` removes an interpreter from NodePhell's
registry. It does not delete the interpreter or any of its files. The command
also works for a stale registration after the executable has disappeared.
Add `--delete` to delete the interpreter directory when it was downloaded and
is owned by NodePhell. Deletion is refused for external interpreters and for a
runtime still named by a live project record.

### `nodephell project list`

List projects known to NodePhell:

```console
nodephell project list
```

`current` means the recorded lock is unchanged. `changed` means the lock was
edited and the project should be installed or launched successfully again.
`unavailable` means the project location or lock cannot currently be reached;
its shared releases remain protected from cleanup. The release count is the
number of NodePhell-owned shared releases retained for that project.

`nodephell project move OLD NEW` updates a registration after moving a project.
The command refuses the move unless `NEW/pylock.toml` has the same fingerprint
as the registered lock, protecting package ownership from accidental
reassignment.

`nodephell project remove [PROJECT]` removes only that project registration.
It defaults to the current directory and leaves the project, lock, runtimes,
and packages untouched. The released package references become eligible for
the normal `store clean` preview and `store clean --apply` workflow.

### Store commands

`nodephell store check` reads the managed store and reports damaged releases,
broken combined views, and changed externally owned files:

```console
nodephell store check
```

Cleanup is deliberately two-step. The first command is a dry run; only the
second changes files:

```console
nodephell store clean
nodephell store clean --apply
```

Cleanup removes only paths NodePhell owns and identifies as safe candidates.
It never removes packages from an application-owned external directory.
Releases used by current projects are kept. If a lock changed, its previous
releases are kept until a successful launch or install refreshes the record.

### Embedded-host commands

These commands operate through installed adapter plugins. The repository's
FreeCAD reference implementation is packaged separately under
`plugins/freecad`.

`nodephell host add [--kind KIND] EXECUTABLE` probes and registers a
command-line host. NodePhell infers the adapter from a recognized executable
name when possible; use `--kind` to select it explicitly:

```console
nodephell host add /path/to/FreeCADCmd
nodephell host add --kind freecad /path/to/custom-freecad-command
```

Run this again after changing the host or its application-managed package
location. `nodephell host list` shows registered hosts and their embedded Python
versions.
`nodephell host adapters` shows the plugins NodePhell currently discovers.

`nodephell host remove EXECUTABLE` removes a host from NodePhell's registry.
Without `--delete`, it never deletes the application and can remove a stale
registration whose executable is already missing.
Add `--delete` to delete a NodePhell-downloaded host after its project
references have been removed. External application installations cannot be
deleted by NodePhell.

`nodephell host run [--] HOST-ARGS` runs a script or other command-line request
through the host selected by the project:

```console
nodephell host run script.py
nodephell host run -- script.py --script-option
```

The script should be inside the project tree so NodePhell can discover its
lock. `nodephell host gui [--] HOST-ARGS` starts the graphical sibling of the
registered command-line host:

```console
cd /work/freecad-project
nodephell host gui
nodephell host gui -- model.FCStd
```

Host commands require `[tool.nodephell.host]` in the project metadata and a
registered host with a compatible embedded Python binary interface.

## FreeCAD reference plugin

FreeCAD is being used as a demanding embedded-Python test. Declare it in the
project's `pyproject.toml` before installing:

```toml
[tool.nodephell.host]
kind = "freecad"
requires = "==27.1.0"
```

Use the version reported by your FreeCAD build. After the project is installed,
use the `host run` or `host gui` commands documented above. The embedded Python
must have the same binary interface as the Python selected for the project.
NodePhell gives its selected package view priority during the FreeCAD launch.
For this launch only, the generic Python user site is redirected to an unused
location so it cannot contaminate the project. This does not change FreeCAD's
saved setting or remove its own addon, module, macro, preference, or package
paths.

You can register an existing build with `host add`. If no registered host
matches a newly locked project, the current Linux prototype can select,
download, verify, and register a matching FreeCAD AppImage during
`nodephell install`.

When the registered host reports an application-managed package directory,
NodePhell may reuse an exact locked version from it instead of downloading a
duplicate. The application keeps ownership: NodePhell only reads those files
and links them into its generated view. If they disappear or change, the next
install supplies NodePhell's own copy.

## Where files live

NodePhell keeps managed files below `~/.python`:

```text
~/.python/
├── hosts/
├── locks/
├── packages/NAME/VERSION/DOWNLOAD_FILENAME/SHA256/root/
├── projects/PROJECT_NAME-PATH_HASH.json
├── runtimes/registry.json
└── pythonXY/
    ├── interpreter/FULL_VERSION/PYTHON_ABI/DOWNLOAD_SHA256/
    └── compositions/
```

`packages` contains the physical package files. Compatible projects and Python
versions reuse them. `compositions` contains generated links that present each
project's selected packages as a normal import directory. `projects` records
which shared releases are still in use, and `hosts` contains embedded-host
registrations. The small files under `locks` prevent simultaneous processes
from changing the same managed item.

Do not move individual directories inside this tree by hand. The names and
versions are visible for inspection, while NodePhell relies on the deeper
download and hash directories to distinguish incompatible files safely.

These are shared data and bookkeeping, not project environments.

## Results and errors

Successful commands return status 0. A NodePhell selection or installation
error returns status 2 and starts its message with `nodephell:`. Store checks
return status 1 when they find a problem. A cleanup preview may also return 1
when it has findings; that does not mean the preview changed anything.

Common remedies are:

- **Locked item unavailable:** run `nodephell install` in the project.
- **No project found:** run from the project tree, or pass a script inside it.
- **No compatible runtime:** use `runtime install` or `runtime add`.
- **No compatible host:** use `host add` with its command-line executable.
- **Unexpected selection:** inspect `nodephell resolve` and `runtime list`.
- **Possible store damage:** run `store check`, then preview `store clean`.

The `remove` commands unregister projects, runtimes, and hosts without deleting
their files. Do not delete pieces of `~/.python` casually; use the store
commands for package data.

## Current limits

- Automatic interpreter downloads currently target supported Linux systems.
- Commands supplied by installed packages do not have NodePhell launchers yet.
- FreeCAD is currently the only embedded application with a reference plugin
  in this repository.

The [roadmap](roadmap.md) describes planned work. The
[architecture document](architecture.md) explains the design in more detail.
