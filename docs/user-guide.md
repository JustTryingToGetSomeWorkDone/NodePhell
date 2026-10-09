<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell user guide

NodePhell runs Python projects from a locked interpreter and package set without
per-project virtual environments. Missing items go into shared storage, then
the `python`, `python3`, and installed package launchers select the right
combination whenever the project runs.

## Install the launchers

From a checkout, install `nodephell`, `python`, and `python3` into the standard
per-user command directory:

```console
/path/to/NodePhell/bin/nodephell launcher install
```

The command reports when `~/.local/bin` is missing from `PATH` or loses to
another command directory. On Bash, it offers to put that directory first in
`~/.bashrc`. Accepting this change does not alter the terminal that is already
open: close it and open a new terminal before using `python`, `python3`, or
`nodephell`. People who prefer to refresh the current terminal can instead run
the two commands printed by the installer.

Automatic shell setup currently supports Bash. Use `--configure-shell` to
request it without a prompt or `--no-configure-shell` to leave shell startup
untouched. The two Python launchers are identical. They point at the checkout
that installed them, so reinstall after moving that checkout.

`nodephell launcher uninstall` removes core, package-command, and application
launchers marked as installed by NodePhell, along with the marked PATH block it
added to `.bashrc`. It leaves every other part of that file plus application
records, runtimes, hosts, packages, project records, and the source checkout
untouched. Run `nodephell app refresh NAME` to restore an application launcher
later. Installation and removal refuse to overwrite or delete an unrelated
command with the same name.

## Prepare a project

For a new project, run this inside its directory:

```console
nodephell init
```

The interactive questionnaire asks for:

1. the project name, defaulting to the directory name;
2. the project version, defaulting to `0.1.0`;
3. the target Python, defaulting to NodePhell's current Python major/minor;
4. dependency names and optional version requirements; and
5. confirmation before anything is written.

Press Enter to accept a displayed default. A blank dependency version means
the newest release compatible with the target interpreter and the other
requirements. A blank response to `Add dependency` ends the dependency list.

`init` creates `pyproject.toml` and then performs a synchronization: it selects
the runtime, resolves the complete package set, creates `pylock.toml`, and
installs missing items. It refuses to replace an existing `pyproject.toml`.

For an existing project, create or edit `pyproject.toml` directly. A minimal
definition looks like this:

```toml
[project]
name = "example"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
    "lark",
    "requests>=2.32,<3",
]
```

The filename is exactly `pyproject.toml`. It is the human-maintained project
definition. Dependencies may omit a version, use an exact version such as
`requests==2.32.5`, or specify a range. Prepare it with:

```console
nodephell sync
```

NodePhell also recognizes the common Poetry-era layout when a standard
`[project]` table is absent:

```toml
[tool.poetry.dependencies]
python = "^3.8"
textual = "==0.53.1"
httpx = "^0.24.1"
```

Main, non-optional dependencies participate in the runtime lock. Poetry
development groups do not. Basic exact, comparison, caret, tilde, wildcard,
and unversioned constraints are translated into the same requirements passed
to stock pip. Unsupported sources, markers, and platform-specific dependency
tables stop with an explicit error rather than producing an incomplete lock.

`sync` creates or updates the generated `pylock.toml` only when needed, then
installs its exact state. The lock records the selected Python build, complete
dependency closure, artifact locations, and hashes. Keep it with the project
when another machine should reproduce the same selection; do not edit its
package list manually.

When `pyproject.toml` declares a standard `[build-system]`, `sync` also asks
stock pip to connect the source project to the selected Python in editable
form. Python continues to use live code from the checkout, while the project
can report its installed name and version and provide its declared commands.
This makes calls such as
`importlib.metadata.version("project-name")` work without copying the project
into a virtual environment. NodePhell keeps the small editable installation in
`~/.python/source-projects`, separate from immutable interpreters and downloaded
packages. Projects without `[build-system]`, including dependency-only
application definitions, are not treated as installable Python packages.

### Select optional project features

Standard `[project.optional-dependencies]` features and top-level
`[dependency-groups]` are available through:

```console
nodephell options
```

The numbered terminal checklist shows the current project selection. Enter one
or more numbers and press Enter to toggle pending checkboxes. Enter `A` and
press Enter to apply them, or `Q` and Enter to quit without applying pending
changes. Escape cancels pending changes immediately, without requiring Enter.
After an apply, the updated menu remains open so more changes can be made.
NodePhell records applied names in `pylock.toml`, resolves their ordinary
dependencies, and performs the same installation work as `sync`; the user does
not invoke pip directly.

If resolution fails, no pending choice is applied and the previous lock remains
in place. The error is shown without routine pip download chatter. When a
Python package reports a missing external program, NodePhell explains that it
is separate system software and how to retry or deselect the responsible
option. The screen pauses before returning to the still-pending selection so
the explanation is not immediately pushed out of view.

Deselecting an option removes its unneeded dependencies from this project's
package view. It does not delete their immutable releases from the shared
store. NodePhell reports releases still used by other registered projects. If
a release is provably unused, NodePhell offers a separate removal prompt whose
default is No, then repeats the reference check immediately before any
confirmed deletion. Overlapping dependencies remain selected whenever the
project's core requirements or another selected option still needs them.

When choosing Python for a new lock, NodePhell reuses the newest compatible
managed runtime that has an exact download identity. If none is available, it
downloads a compatible stable release. A prerelease is selected only when the
project's Python requirement explicitly names one.

After that, use Python normally:

```console
python app.py
python3 -m unittest
python -c 'import requests; print(requests.__version__)'
```

There is no activation command and nothing needs to be repeated in each new
terminal. After changing the project definition, run `nodephell sync` again.

## What the launcher does

Inside a project, `python` and `python3`:

1. find the project by looking upward from the working directory or script;
2. select the exact locked interpreter and package downloads;
3. add the project's editable source view when it declares a build system; and
4. start that interpreter with only those explicitly selected paths.

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

Errors are explicitly labelled and use bold red in an interactive terminal.
Warnings and actionable `What this means` guidance use yellow, while important
filenames use cyan. Color is never the only distinction. Redirecting the
output, using `TERM=dumb`, or setting `NO_COLOR` disables terminal color.

```text
nodephell init [PROJECT]
nodephell sync [PROJECT]
nodephell options [PROJECT]
nodephell lock [PROJECT]
nodephell install [-v] [PROJECT]
nodephell update [PROJECT]
nodephell run [--] PYTHON-ARGS
nodephell resolve [--] PYTHON-ARGS
nodephell launcher install [--configure-shell | --no-configure-shell]
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
nodephell host resolve [--] HOST-ARGS
nodephell host run [--] HOST-ARGS
nodephell host gui [--] HOST-ARGS
nodephell app add [EXECUTABLE] [--project PATH] [--name NAME] [-y]
nodephell app list
nodephell app refresh NAME
nodephell app remove NAME
nodephell plugin add PATH
nodephell plugin scan [DIRECTORY]
nodephell plugin list
nodephell plugin remove KIND
nodephell doctor
```

`nodephell install` summarizes package-command launcher changes. Add
`--verbose` to list every installed or preserved command name. Interactive
output highlights those names, while labels preserve the same distinction
when color is disabled.

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

### Initialize and synchronize

`PROJECT` is optional and defaults to the current directory.

```console
nodephell init
nodephell sync /work/example
```

`init` interactively creates `pyproject.toml` and immediately synchronizes the
new project. `sync` compares the relevant definition inputs with the identity
recorded in `pylock.toml`. It creates a missing lock, updates a stale lock, or
reuses a current lock, then installs missing items. Reordering dependencies
alone does not make the lock stale.

Use `nodephell options [PROJECT]` to change standard optional features and
dependency groups. Applying the checklist re-resolves and installs the new
locked selection. Deselecting an option never deletes shared releases without
the separate confirmation described above.

When a generated lock exists and the Python requirement, dependencies, or host
requirement changes, ordinary launching stops with a request to run
`nodephell sync`. This prevents a changed definition from silently running the
old package selection.

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
succeeds. Run `install` afterward to supply the updated lock state. These are
the separate operations composed by `sync`.

For each command declared in an exact locked package's `console_scripts`
metadata, `install` creates a small launcher under `~/.local/bin`. Running that
command from a project resolves the project's locked runtime and packages
first, with no activation step. External package commands are eligible only
when their exact distribution metadata and `RECORD` have passed NodePhell's
read-only reuse checks. Packages reused from the selected runtime are queried
through that runtime's isolated distribution metadata. Unrelated executable
files are ignored. NodePhell refuses to install a project when two locked
packages provide the same command name, and it never replaces an unrelated
command already in `~/.local/bin`.

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
runtime artifact, why that runtime was selected, combined package view, and the
provider chosen for every package. Providers are `managed-store`,
`selected-runtime`, or `external-host`. `system_fallback: true` means no project
was found and the system Python would be used.

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

### `nodephell doctor`

Run the main read-only health checks together:

```console
nodephell doctor
```

Doctor verifies that `nodephell`, `python`, and `python3` all resolve to the
installed NodePhell launchers. It also checks adapter discovery, runtime, host,
and application registries, project records, and every committed package
release. It prints a problem for each area that needs attention and returns
status 1 when it finds one or more problems.

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

For normal application setup, prefer `nodephell app add`. The `host` commands
below are the lower-level inspection and recovery interface.

These commands operate through installed adapter plugins. The repository's
FreeCAD reference implementation is packaged separately under
`plugins/freecad`. See [Author an embedded-host adapter](host-adapters.md) for
plugin installation and development.

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

### Application commands

An application binding combines an embedded host, a NodePhell project, and an
ordinary command under `~/.local/bin`. From a project directory, the simplest
setup is:

```console
nodephell app add
```

Prepared application distributions can make even that separate step
unnecessary. They declare a bundled plugin in `pyproject.toml`:

```toml
[tool.nodephell.application]
adapter = "nodephell-plugins/freecad"
```

The adapter path must remain inside the project. NodePhell uses the adapter's
bounded search patterns to find the executable. If more than one match is
possible, the project can identify it explicitly:

```toml
[tool.nodephell.application]
adapter = "nodephell-plugins/freecad"
executable = "build/release/bin/FreeCADCmd"
name = "FreeCAD" # optional override of the plugin's launcher name
```

`nodephell install` then installs the declared plugin, registers the already
locked host, installs the packages, and creates the application launcher. It
never changes the project or lock; if the bundled executable does not match
the declared host, it directs the user to `nodephell sync`. The sync command
performs the same bootstrap while deliberately updating an absent or stale
host requirement and lock.

```console
cd /path/to/extracted/application
nodephell install
FreeCAD
```

Installed adapters provide bounded project-relative search patterns. If one
entry executable is found, NodePhell displays it in the setup plan. If several
are found, it presents a numbered terminal selection. If none are found, it
asks for the path. The path can always be supplied directly:

```console
nodephell app add ./build/release/bin/ExampleCmd
```

Before making changes, NodePhell reports the detected application and embedded
Python, project, entry executable, and proposed launcher. After confirmation it
registers the host, writes the exact host requirement, synchronizes the lock,
records the application binding, and creates the launcher. Project and lock
edits are restored if synchronization fails. `--yes` accepts a single detected
candidate or an explicit path without prompting; it refuses to guess when
several candidates exist.

The adapter supplies the default launcher name. Override it when keeping more
than one configured copy:

```console
nodephell app add /opt/example/bin/ExampleCmd --name Example-stable
```

The launcher remembers both its project and entry executable. It therefore
works outside the project and may be used as the `Exec` command of a desktop
icon. Arguments are passed to the application unchanged.

`nodephell app list` shows configured bindings. After rebuilding, replacing,
or upgrading an application, run `nodephell app refresh NAME` to probe it again
and synchronize any changed version requirement. `nodephell app remove NAME`
removes only the binding and launcher; it leaves the project, application,
registered host, and shared packages untouched.

### Plugin commands

During local development, install an adapter without manually creating a
symlink:

```console
cd /directory/containing/plugins
nodephell plugin add freecad-adapter
nodephell plugin list
```

`plugin add` accepts a Python adapter module, package directory, `src`
directory, or a project containing one adapter package. It creates a link in
the user adapter directory and validates the plugin immediately. It refuses an
ambiguous source or an occupied plugin name. `nodephell plugin remove KIND`
removes only a link created in that directory and never deletes plugin source.

Several plugin projects can instead be dropped into
`~/.local/share/nodephell/plugins`, then installed together:

```console
nodephell plugin scan
```

Pass another directory to scan that location instead. Scanning examines only
its immediate children, installs plugins that are not already installed, and
reports broken or conflicting plugins without hiding successful ones. The
installed links are the authoritative plugin list; there is no second registry
to keep synchronized. Installing published plugins by catalog name is planned
separately.

Host commands require `[tool.nodephell.host]` in the project metadata and a
registered host with a compatible embedded Python binary interface.

`nodephell host resolve [--] HOST-ARGS` performs the same host, runtime, and
package selection without launching the application. Its JSON output includes
the selected host executable and identifies packages reused from the host as
`external-host`.

## FreeCAD reference plugin

The FreeCAD reference plugin connects NodePhell to `FreeCADCmd` and the FreeCAD
GUI. Register an existing build, then declare the reported version in the
project's `pyproject.toml` before synchronizing:

```toml
[tool.nodephell.host]
kind = "freecad"
requires = "==1.1.3"
```

The version above is an example; use the value from `nodephell host list` or an
appropriate supported range. After the project is installed, use the `host
run` or `host gui` commands documented above. The embedded Python must have the
same binary interface as the Python selected for the project.
NodePhell gives its selected package view priority during the FreeCAD launch.
For this launch only, the generic Python user site is redirected to an unused
location so it cannot contaminate the project. This does not change FreeCAD's
saved setting or remove its own addon, module, macro, preference, or package
paths.

You can register an existing build with `host add`. If no registered host
matches a newly locked project, the plugin can select, download, verify, and
register a matching Linux FreeCAD AppImage during `nodephell sync` or
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
├── applications/registry.json
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
which shared releases are still in use. `hosts` contains the host registry and
any NodePhell-downloaded applications. `applications/registry.json` binds each
application launcher to its project, adapter, and entry executable. The small
files under `locks` prevent simultaneous processes from changing the same
managed item.

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

- **Missing or stale lock:** run `nodephell sync` in the project.
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
- Dependency markers and direct URL or path requirements are not yet supported.
- Legacy Poetry metadata support covers ordinary runtime dependencies, not
  Poetry development groups, sources, markers, or platform-specific variants.
- FreeCAD is currently the only embedded application with a reference plugin
  in this repository.

The [roadmap](roadmap.md) describes planned work. The
[architecture document](architecture.md) explains the design in more detail.
Adapter developers should start with the [human authoring guide](host-adapters.md)
or the [AI implementation brief](adapter-authoring-ai.md).
