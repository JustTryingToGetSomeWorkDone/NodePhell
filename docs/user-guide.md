<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell user guide

NodePhell runs Python projects from a locked interpreter and package set without
per-project virtual environments. Missing items go into shared storage, then
the `python`, `python3`, and installed package launchers select the right
combination whenever the project runs.

## Install the launchers

Clone NodePhell and install its launchers directly from the source checkout:

```console
git clone https://github.com/JustTryingToGetSomeWorkDone/NodePhell.git
cd NodePhell
./bin/nodephell launcher install
nodephell --version
```

The optional FreeCAD adapter is included in the checkout. Register it with:

```console
nodephell plugin add ./plugins/freecad
```

Keep the checkout because the installed commands run its source directly.
Update from that directory with `git pull --ff-only`, then rerun
`./bin/nodephell launcher install`.

The command reports when `~/.local/bin` is missing from `PATH` or loses to
another command directory. On Bash, it offers to put that directory first in
`~/.bashrc`. Accepting this change does not alter the terminal that is already
open: close it and open a new terminal before using `python`, `python3`, or
`nodephell`. People who prefer to refresh the current terminal can instead run
the two commands printed by the installer.

Automatic shell setup currently supports Bash. Use `--configure-shell` to
request it without a prompt or `--no-configure-shell` to leave shell startup
untouched. The two Python launchers are identical. Launchers point at the
checkout and should be reinstalled after moving it.

`nodephell launcher uninstall` removes core, package-command, and application
launchers marked as installed by NodePhell, along with the marked PATH block it
added to `.bashrc`. It leaves every other part of that file plus application
records, runtimes, hosts, packages, project records, and the source checkout
untouched. Run `nodephell app refresh NAME` to restore
an application launcher later. Installation and removal refuse to overwrite or
delete an unrelated command with the same name.

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
the runtime, resolves the complete package set, creates the project lock, and
installs missing items. It refuses to replace an existing `pyproject.toml`.

For downloaded code without a declaration, run `nodephell discover` to review
its imports and generate one; see the discovery section below. You can also
create or edit `pyproject.toml` directly. A minimal
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
`requests==2.32.5`, specify a range, or include a standard PEP 508 environment
marker. Credential-free HTTPS direct references are also accepted. Markers are
evaluated by stock pip running under the selected project Python, not by
NodePhell's management interpreter. Prepare the project with:

```console
nodephell sync
```

Projects may also declare `dynamic = ["dependencies"]` in `[project]`. When the
project has a name and `[build-system]`, NodePhell asks that build backend for
the dependency metadata and locks the resulting exact closure. Because a
backend may derive this metadata from arbitrary files or code, every `sync`
refreshes a dynamic dependency lock before installing it. `install` continues
to reproduce the existing lock without resolving it again.

NodePhell must inspect the Python requirement and available options before it
invokes a backend. Declare `requires-python` and `optional-dependencies`
statically; dynamic forms of those fields stop with an explicit error.

### Discover dependencies in an existing project

If you have Python code but no `pyproject.toml`, open a terminal in its folder:

```console
nodephell discover
```

NodePhell scans `.py` files without importing or executing them. It filters out
the standard library and local modules, including conventional `src/` layouts,
then shows the remaining imports with their file locations. It labels imports
in functions, conditional branches, import-error fallbacks, and tests,
examples, or documentation.

For each import, review the proposed distribution name. Some differ from the
import: `PIL` suggests `Pillow`, and `yaml` suggests `PyYAML`. Unknown imports
use a clearly marked same-name guess, which you should check against upstream
instructions. Ambiguous mappings such as `cv2` list alternatives for you to
choose. These are suggestions, not a lookup against a package index.
Ordinary same-name imports use the generic fallback; they need no individual
entry in the mapping data.

Press Enter to accept the displayed choice, type a different distribution
name, or enter `-` to skip. Imports found only in optional or conditional code,
tests/examples/docs, or modules listed for the selected application default to skip;
enter the distribution name if you want them included. These defaults do not
establish that an import is unnecessary. A dependency used in a function still
defaults to inclusion when it has no other review-only context. Repeated import
names that map to the same distribution are deduplicated.

The next prompt accepts a version number, a constraint such as `>=2,<3`, or a
blank answer for normal resolution. Refer to the project's documentation for
compatibility requirements. You can add dependencies missed by the scan before
reviewing the complete proposed TOML. The command writes a dependency-only
`pyproject.toml` after confirmation; it does not add a build system or install a
source package. Then run `nodephell sync` to generate the lock and install it.

If requirements files already exist at the project root or directly under
`requirements/`, discovery offers them before scanning. Choosing one creates
the project identity and Python requirement while leaving dependencies in
that existing file. Follow the printed `nodephell sync --requirements FILE`
command for the first synchronization. Stock pip parses the requirements file;
it is not translated into a second dependency list. The resulting lock retains
the profile selection for subsequent synchronization.

If `pyproject.toml` already exists, discovery only reports potential omissions;
it never overwrites or edits the file. Suggestions may already be covered by
extras, dependency groups, or application-owned modules.

Use repeated exclusions for generated or vendored code:

```console
nodephell discover /work/example --exclude 'vendor/**' --exclude '*_generated.py'
```

Hidden directories, virtual-environment directories, `node_modules`, build
outputs, installed `site-packages`, and symlinks are skipped automatically.
Syntax or encoding failures and common dynamic-import calls produce review messages.
Discovery cannot infer all dynamic imports, plugins, native/system libraries,
or supported dependency versions. Standard-library filtering uses the Python
running NodePhell, so check for differences if you select another target Python.

#### Maintain import mappings separately

Discovery reads `assets/import-mappings.toml` in the NodePhell checkout.
This data file contains import-name exceptions and ambiguous alternatives.
It can be updated without editing the Python scripts. Names such as `numpy`,
`scipy`, and `pandas` need no entries: discovery already offers the import name
as the default distribution name.

You can keep additions or overrides outside the checkout:

```console
nodephell discover --mappings /path/to/my-import-mappings.toml
```

The external file uses the same format:

```toml
[imports]
custom_import = ["actual-distribution"]
cv2 = ["opencv-python-headless"]

[applications]
mycad = ["CADCore", "CADGui"]
```

External entries override matching bundled entries and leave other entries
intact. Lists contain names only; enter versions at the interactive prompt.
Malformed files stop with an error identifying the mapping file, before any
project metadata is written. The file is reread on each discovery run, so no
script changes or reinstall are needed when you update it.

Application-module hints apply only when the project's existing
`[tool.nodephell.host]` identifies that application, or you explicitly select
one for the review:

```console
nodephell discover --application freecad
nodephell discover --mappings /path/to/my-import-mappings.toml --application mycad
```

Without that context, a name such as `Part` is treated like any other import.
Selecting an application here only controls discovery suggestions; it does not
register a host or load application or adapter code. The mapping files are
hints for human review, not proof that a package or application supplies a module.

### Requirements-file profiles

Some projects publish separate pip requirements files for mutually exclusive
platform stacks such as CUDA, ROCm, or XPU. Select one for locking and
synchronization with:

```console
nodephell sync --requirements requirements-rocm-linux.txt
```

The pip requirements-file format is a tool convention rather than a Python
interoperability standard. NodePhell accepts it as a locking input, but does not
interpret installation prose or repair an incomplete project declaration. It
prints a warning that the selected file must explicitly contain the complete
dependency set, including any prerequisite command, platform-specific package,
or local project that should be part of the lock.

`-r` is the short form and may be repeated to combine files. A selected profile
replaces `[project].dependencies`, optional features, and dependency groups; it
does not merge incompatible platform stacks. Stock pip parses the files, so
ordinary requirements, environment markers, `--index-url`,
`--extra-index-url`, secure direct archive references, constraints, and nested
`-r` files retain their pip behavior.

The generated lock stores project-relative profile names and fingerprints
their contents plus every project-contained requirements or constraints file
they include. Editing any of those files makes the lock stale. Includes that
escape the project are rejected so the recorded definition remains portable.
The exact resolved artifacts and hashes still go into the lock; launching and
installation never need to reinterpret the requirements files.

Some package indexes provide a resolved artifact URL without a hash. NodePhell
does not weaken the lock in that case. It asks stock pip to download the exact
credential-free HTTPS artifact, computes SHA-256 locally, and records the
result before installation. This can add one download during the first lock;
pip's cache can satisfy the later store installation without another network
transfer.

The same options are available on `lock` and `update`. A later `sync` or
`update` preserves the selected profile. Return to the dependencies in
`pyproject.toml` with:

```console
nodephell sync --project-dependencies
```

If upstream installation instructions install a package in a separate pip
command, put that command's requirement and index directive in a small wrapper
requirements file which includes the upstream file. NodePhell does not infer
active dependencies from comments or prose documentation.

The preferred shareable result is a standard PEP 751 lock. PEP 751 permits
named files such as `pylock.rocm-linux.toml` and records exact artifacts,
hashes, local directories, markers, and originating indexes without requiring
resolution at installation time. NodePhell currently reads its bounded
single-environment `pylock.toml` subset; selecting among named PEP 751 locks is
planned as the standards-based replacement for publishing ad hoc platform
installation instructions.

### uv indexes and sources

NodePhell recognizes credential-free HTTPS `[[tool.uv.index]]` entries and
`[tool.uv.sources]` mappings to those named indexes. It forwards the declared
indexes to stock pip during resolution. This compatibility layer does not
reimplement uv's index-priority algorithm; stock pip's index selection rules
apply, so projects that depend on uv-specific priority behavior should use a
requirements-file profile with explicit pins.

A uv source may also name an editable, project-contained directory containing
its own `pyproject.toml`:

```toml
[tool.uv.sources]
nano-vllm = { path = "vendor/nano-vllm" }
```

The local project participates in dependency resolution, but its live source
checkout is prepared centrally under `~/.python/source-projects` and injected
only for the owning locked project. Non-editable paths, paths outside the
project, Git sources, credential-bearing URLs, and uv default-index replacement
are rejected explicitly.

NodePhell also recognizes the common Poetry-era layout when a standard
`[project]` table is absent:

```toml
[tool.poetry.dependencies]
python = "^3.8"
textual = "==0.53.1"
httpx = "^0.24.1"
```

Main, non-optional dependencies participate in the runtime lock. Poetry
development groups use the same option screen as standard dependency groups:

```toml
[tool.poetry.group.test.dependencies]
pytest = "^8.0"

[tool.poetry.group.dev]
include-groups = ["test"]

[tool.poetry.group.dev.dependencies]
ruff = "^0.14"
```

The older `[tool.poetry.dev-dependencies]` form is recognized as the `dev`
group. Standard and Poetry groups with the same name are combined. NodePhell
shows every development group as an explicit choice rather than automatically
enabling Poetry's non-optional groups.

Basic exact, comparison, caret, tilde, wildcard, and unversioned constraints
are translated into the same requirements passed to stock pip.

### Poetry compatibility and limits

NodePhell currently supports ordinary Poetry runtime dependencies, modern and
legacy development groups, group inclusion, and dependency extras. It does not
yet support:

- custom Poetry package sources;
- Poetry marker fields or Python/platform-specific Poetry constraint tables;
- Git, local path, or direct URL dependencies;
- multiple constraint tables or prerelease opt-in;
- Poetry's legacy optional-dependency extras as project options; or
- importing an existing `poetry.lock` instead of generating a NodePhell lock.

Unsupported declarations stop with an explicit error instead of producing an
incomplete lock.

`sync` creates or updates the generated lock only when needed, then installs its
exact state. Keep that file with the project when another machine should
reproduce the same selection; do not edit its package list manually.

### Lock filenames and interoperability

NodePhell uses one of two lock filenames:

- `pylock.toml` is the standard PEP 751 filename. NodePhell writes it only when
  the complete lock remains standards-conforming. It pins the selected Python
  version through the standard `requires-python` field.
- `nodephell.lock.toml` is used when exact interpreter or embedded-host
  artifacts add installation data that PEP 751 does not define.

Both forms contain exact package artifacts and hashes. NodePhell discovers and
installs either one, but refuses to guess when both are present. A `sync` of an
older NodePhell-generated `pylock.toml` automatically moves proprietary data to
the NodePhell filename.

NodePhell can also install the supported single-environment subset of a
standard `pylock.toml` written by another tool: every selected package must
name exactly one wheel or sdist with a secure hash. Package markers,
multi-environment locks, multiple artifact choices, and VCS, directory, or
generic archive sources currently stop with an explicit unsupported-feature
error. Running `sync` resolves from `pyproject.toml` and writes the appropriate
current lock form.

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

Extra and dependency-group names use standard normalization: case is ignored
and runs of `.`, `_`, or `-` compare as `-`. Declarations that collide after
normalization stop with an explicit error. Dependency-group includes preserve
their declared expansion, including repeated requirements, for PEP 735
compatibility.

The numbered terminal checklist shows the current project selection. Enter one
or more numbers and press Enter to toggle pending checkboxes. Enter `A` and
press Enter to apply them, or `Q` and Enter to quit without applying pending
changes. Escape cancels pending changes immediately, without requiring Enter.
After an apply, the updated menu remains open so more changes can be made.
NodePhell records applied names in the project lock, resolves their ordinary
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
nodephell discover [PROJECT] [--exclude GLOB]... [--mappings FILE] [--application NAME]
nodephell manage
nodephell sync [PROJECT] [-r FILE]... [--project-dependencies]
nodephell options [PROJECT]
nodephell troubleshoot [PROJECT] [-- COMMAND...]
nodephell lock [PROJECT] [-r FILE]... [--project-dependencies]
nodephell install [-v] [PROJECT]
nodephell update [PROJECT] [-r FILE]... [--project-dependencies]
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
nodephell sync -r requirements-rocm-linux.txt /work/example
```

`init` interactively creates `pyproject.toml` and immediately synchronizes the
new project. `discover` reviews imports and writes a declaration without
synchronizing; with existing metadata, it produces a report only. `sync`
compares the relevant definition inputs with the identity
recorded in the generated lock. It creates a missing lock, updates a stale lock, or
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

### Troubleshoot a failing project command

Use the guided diagnostic after `sync` succeeds but an import, command, or
application smoke test still fails:

```console
nodephell troubleshoot
nodephell troubleshoot /work/example -- example-command --help
```

Without a command, NodePhell reads standard `[project.scripts]` and Poetry
`[tool.poetry.scripts]` entries. It suggests the sole command or presents a
numbered list; any complete command can also be entered at the prompt.

The diagnostic first runs the command with the current lock. If it fails and
the project declares a Python range with a major-and-minor lower bound,
NodePhell generates and installs a trial lock for the latest available patch on
that earliest minor line. For example, `>=3.8,<4` is tried as
`>=3.8,<4,<3.9`. The declaration in `pyproject.toml` is not edited.

Before changing the lock, NodePhell appends
`.nodephell-troubleshoot-backup` to its current filename. A failed or declined
trial restores the original filename and selection. A successful trial is kept
only after an explicit `y` or `yes`. If the process is forcibly stopped and
leaves the backup behind, inspect the filenames and restore, for example, with:

```console
mv nodephell.lock.toml.nodephell-troubleshoot-backup nodephell.lock.toml
nodephell install
```

The command reports status 1 when both runtime selections reproduce the
failure. Its final message names the metadata or command to check next.

### Lock, install, and update

`PROJECT` is optional and defaults to the current directory.

```console
nodephell lock
nodephell install
nodephell update /work/example
nodephell update -r requirements-rocm-linux.txt /work/example
```

`lock` creates the appropriate standard or NodePhell lock from `pyproject.toml`
and refuses to replace an existing lock. `install` requires that lock, follows it exactly, and reuses
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
The command refuses the move unless the lock under `NEW` has the same filename
and fingerprint as the registered lock, protecting package ownership from
accidental reassignment.

`nodephell project remove [PROJECT]` removes only that project registration.
It defaults to the current directory and leaves the project, lock, runtimes,
and packages untouched. The released package references become eligible for
the normal `store clean` preview and `store clean --apply` workflow.

### Interactive management

Run `nodephell manage` for one menu covering runtimes, package releases,
registered projects, embedded hosts, integrity checks, and cleanup.

Interactive terminals use cyan option numbers and action keys, blue headings,
yellow problem statuses, and green success messages. Inventory paths wrap on
separate indented lines. `NO_COLOR`, `TERM=dumb`, and redirected output disable
color; the labels and spacing remain usable without it.

Select entries with numbers such as `1,3-5`, or type `all`. Enter goes back
without selecting anything. Every modifying action shows its target paths
and asks `Proceed? [y/N]`; a blank answer leaves them alone. The menu refreshes
its inventory when you open a section again. Individual CLI commands remain
available for scripting or direct use.

For a runtime you deleted manually, choose **Runtimes**, select the missing
entries, and choose **Unregister only**. This removes their stale registrations
while keeping any remaining files. The same operation works for missing hosts.
The list distinguishes managed from external installations and shows missing
executables or library directories. Present executables are labelled as not
yet probed; the **Probe** action checks selected runtimes or hosts through the
normal inspection functions.

**Delete managed files** removes an unused NodePhell-managed runtime or host
and its registration. External installations are not deleted. Project-use
checks run again before deletion. Unregistering a healthy runtime or host
keeps its files, but projects may need it registered again afterward.

**Package releases** reads metadata without hashing every installed file.
It first shows an alphabetical list of package names, 15 per page. Press the
left or right arrow to change pages, or a letter to jump to the first package
beginning with that letter; neither needs Enter in an interactive terminal.
All letters are available for jumping, including `n`, `p`, `b`, and `q`.
Type a package number and press Enter to browse its versions
and builds, including structural problems, reference counts, and full paths.
Enter returns to the package-name list; Enter there returns to the main menu.
With redirected input, enter `left`/`right` (or `previous`/`next`), a letter,
or a package number as a line. Normal terminal input mode is restored when
leaving the browser or cancelling a prompt.
Different artifacts and Python-specific source builds remain individually
selectable. Presence in this list is not an integrity guarantee. Removing
selected releases uses
the guarded unused-release operation and retains releases still referenced by
projects, including damaged ones. Unused generated views of removed releases
may also be discarded. **Registered projects** removes registrations only,
leaving project source, locks, and shared packages in place.

**Check shared package integrity** performs the full checks used by
`nodephell store check`. **Clean broken or unused store entries** previews the
candidates from `nodephell store clean`, lets you select a subset, and rechecks
their eligibility under the maintenance lock before applying that selection.
As with the existing cleanup command, damaged entries may be removed even if
referenced; `nodephell install` restores them for affected projects afterward.
Healthy referenced releases remain protected. Full checks and cleanup can
take time for a large store; browsing runtimes does not trigger them.

Malformed registry data is reported rather than rewritten automatically. A
bad runtime registry does not prevent returning to the menu to inspect other
sections. Invalid project records prevent claims that package releases are
unused until those records are resolved.

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
FreeCAD reference implementation is included under
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
- **Command fails after sync:** run `nodephell troubleshoot` with that command.
- **Native source build fails:** install the named development library or set
  the requested compiler environment variable, then rerun `nodephell sync`.
- **Possible store damage:** run `store check`, then preview `store clean`.

The `remove` commands unregister projects, runtimes, and hosts without deleting
their files. Do not delete pieces of `~/.python` casually; use the store
commands for package data.

For native source builds, NodePhell keeps explicit `CC`, `CXX`, and `AR`
settings. If a managed interpreter names a build tool that is unavailable on
the current machine, NodePhell selects the corresponding host tool when one is
on `PATH`. Project-specific C libraries and headers remain operating-system
prerequisites; build failures identify common missing tools and dependencies
with a concrete next step.

## Current limits

- Automatic interpreter downloads currently target supported Linux systems.
- Direct URL or path requirements are not yet supported.
- Standard `pylock.toml` import currently supports one resolved environment and
  one exact wheel or sdist per package.
- Standard PEP 508 markers are supported; Poetry-specific marker fields remain
  subject to the limits above.
- Poetry support has the limits listed under "Poetry compatibility and limits"
  above.
- FreeCAD is currently the only embedded application with a reference plugin
  in this repository.

The [roadmap](roadmap.md) describes planned work. The
[architecture document](architecture.md) explains the design in more detail.
Real-project results are recorded in
[project compatibility evidence](project-compatibility.md).
Adapter developers should start with the [human authoring guide](host-adapters.md)
or the [AI implementation brief](adapter-authoring-ai.md).
