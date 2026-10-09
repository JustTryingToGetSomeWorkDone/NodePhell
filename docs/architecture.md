<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell architecture

NodePhell resolves a project to one CPython runtime, one exact package set, and
an optional embedded application. Immutable downloads are shared across
projects, while launch-time selection keeps each project's imports isolated.

The embedded-application boundary is specified in
[Author an embedded-host adapter](host-adapters.md). The
[AI adapter implementation brief](adapter-authoring-ai.md) provides the same
contract as a compact implementation task.

## The user experience

Inside a project, the ordinary commands select the Python and packages recorded
for that project:

```console
nodephell init
python app.py
```

For an existing `pyproject.toml`, `nodephell sync` creates or refreshes the lock
when needed and installs its state. There is no environment to create,
activate, or remember. Outside a recognized project, NodePhell's `python`
launcher hands control to the operating system's Python without changing its
environment. `/usr/bin/python3` remains a direct bypass to the
operating-system interpreter.

`nodephell` is the management command. It installs missing items, manages locks,
and reports problems. `python` and `python3` are identical everyday launchers.
`nodephell launcher install` writes marked commands under `~/.local/bin` that
point at the installing checkout. It refuses command-name conflicts. Launcher
uninstall removes only those marked files and does not alter shared data.

For an embedded application, `nodephell app add` binds an adapter-recognized
entry executable to a project and creates an ordinary named launcher. The
launcher resolves that recorded project directly instead of depending on the
desktop process's working directory. The application registry is generic;
executable discovery and launch behavior remain adapter responsibilities.

A distributable application may declare a project-local adapter under
`[tool.nodephell.application]`. The normal install and sync commands then
perform the same binding automatically. Declared adapter and executable paths
must be relative and contained by the project, keeping extracted bundles
relocatable and preventing implicit scans of unrelated source directories.

## What happens when Python starts

1. NodePhell looks upward from the project or script for `pylock.toml` or
   `pyproject.toml`.
2. If no project is found, it starts the system Python normally.
3. If only a project definition exists, it requests `nodephell sync`.
4. If the definition changed since the lock was generated, it also requests
   synchronization instead of silently running the old selection.
5. It reads the exact Python and package list from the current lock.
6. It selects the matching stored interpreter and package releases.
7. It builds one package search path and starts Python.
8. That selection stays unchanged until the process exits.

NodePhell removes an inherited `PYTHONPATH` and disables Python's generic user
site for project launches so unrelated packages cannot silently override the
project's selection. Its explicitly selected shared package view is still added.

## Shared, readable storage

Interpreters and packages are shared between projects rather than copied into a
directory inside every project. The directory names should remain useful to a
person inspecting them:

```text
~/.python/
  packages/
    package-name/
      exact-version/
        download-filename/
          download-hash/
            root/
  python313/
    interpreter/3.13.15/cpython-313-x86_64-linux-gnu/DOWNLOAD_HASH/
    compositions/
  source-projects/
    PROJECT-PATH-HASH/python313/PYTHON-ABI-HASH/
  runtimes/
    registry.json
  applications/
    registry.json
```

The exact downloaded wheel is the unit NodePhell shares. A pure-Python or
stable-interface wheel can therefore be stored once and used by several Python
versions. Different native wheels naturally have different filenames or hashes
and remain separate.

For example, projects using Python 3.13 and Python 3.16 may both select the same
`lark-1.3.1-py3-none-any.whl`. Both point to one stored release rather than
installing two copies. NumPy wheels built separately for Python 3.13 and 3.16
have different filenames and hashes, so they remain separate automatically.

A package built from a source archive also includes the target Python version
line and binary interface below the download hash. Building the same source
under two Python versions can produce different files, so those results must not
be merged. A Python binary interface (often called an ABI) is the set of details
that compiled packages depend on.

Each stored package release must look like a normal installation. NodePhell does
not split one distribution into separate import directories. When several
distributions contribute files to the same import package, as PySide6 does,
NodePhell builds a combined view made from links. It does not copy those files
for every project.

If two distributions instead provide different versions of the same ordinary
import package or module, the first one recorded in the lock has normal Python
search-path precedence. A later distribution can still supply its other import
names. Packages with matching initializers and namespace packages continue to
combine, which preserves deliberately split distributions without making an
accidental mixture from two different implementations.

A source checkout with a standard `[build-system]` is different from an
immutable downloaded release. NodePhell asks stock pip and the declared build
backend to create an editable installation under `source-projects`. Each
project has separate support files for the Python version and binary interface
that created them, while its metadata and import hook point back to the live
checkout. This project-owned view is never presented as a shared immutable
package release, and dependency-only or embedded-application projects without
a build system do not receive one.

Native builds preserve explicit compiler environment settings. When a selected
interpreter records a compiler or archiver that is absent on the current host,
NodePhell supplies an available `CC`, `CXX`, or `AR` default from `PATH` to both
editable and package builds. System library headers remain external project
prerequisites and are reported as such when the backend identifies them.

Console commands declared by exact matching `.dist-info/entry_points.txt`
metadata—including commands belonging to an editable source project—are
exposed by small managed launchers in `~/.local/bin`. Managed
metadata is protected by the release content fingerprint. External metadata is
eligible only when it came through the existing `METADATA` and `RECORD`
validation and remains pinned by the composition's external identity. Packages
reused from the selected runtime are inspected by that interpreter with user
site packages disabled and accepted only at the exact locked version. The
launcher contains no project or version choice: at invocation time it discovers
the calling project, resolves that project's exact runtime and package
composition, and invokes the declared Python module and callable. Commands from
an embedded application's packages run through that host's adapter and
environment. Duplicate providers are rejected, and arbitrary neighboring
executables are never used.

Selection diagnostics use the same resolution paths as execution.
`nodephell resolve` labels runtime and package providers in its JSON output;
`nodephell host resolve` additionally resolves the embedded application and
external package roots without starting it.

## Locks and installation

`pyproject.toml` is the human-maintained definition. Its direct dependencies
may omit a version, select an exact version, or provide a range. For a new or
changed definition, stock pip runs under the selected interpreter and chooses
the newest mutually compatible dependency closure. NodePhell records the exact
Python, packages, downloaded files, and hashes in generated `pylock.toml`.
Installation then uses stock pip to place each package release in temporary
storage before moving it into the shared store.

Standard PEP 508 dependency markers remain part of the human-maintained
definition and its fingerprint. Stock pip evaluates them under the exact
selected runtime during resolution. The generated lock records only the
resulting applicable package releases, so launch and installation do not need
to reevaluate markers.

When a user selects standard optional features or dependency groups,
`pylock.toml` also records their names. They become resolution inputs, while
the resulting dependencies remain ordinary exact releases in the shared store.

Runtime selection first reuses the newest compatible managed interpreter whose
exact download artifact is known. If none is stored, NodePhell obtains a
compatible stable CPython build. Broad requirements do not opt into alpha,
beta, or release-candidate interpreters; the requirement must explicitly name
a prerelease version.

The lock also records a normalized fingerprint of the resolution inputs:
Python requirement, direct dependencies, and embedded-host requirement.
Formatting changes and dependency reordering do not invalidate it. A semantic
change makes the lock stale until synchronization completes.

A lock should mean that another installation selects the same inputs. New
shared-store entries record the package name, version, download filename, and
SHA-256 hash. They also record a fingerprint of the files pip installed.
NodePhell checks the short identity record during normal startup and checks the
full file fingerprint when the user runs `nodephell store check`. This keeps
normal launches quick while still making manual damage detectable. The version
remains easy to find in the directory tree, while the filename and hash prevent
two different builds from contaminating one another.

Installing a release and creating a combined package view are protected by
machine-local locks. If two NodePhell processes request the same item, one does
the work and the other reuses the completed result. A crash releases the lock
automatically. Cleanup can then recognize and remove the abandoned temporary
directory. Installs share a broader maintenance guard, while cleanup takes it
exclusively, so cleanup cannot remove a newly installed release before its
project record is written.

`nodephell store clean` reports what it would remove without changing anything.
`nodephell store clean --apply` removes entries that cannot be used, such as a
damaged release or broken combined view. A successful `nodephell install` also
records the project path, a fingerprint of its lock, and the exact shared
releases it uses under `~/.python/projects/`. Cleanup uses those records to find
healthy releases that no installed project uses.

Deselecting a project option updates the lock and project record before
considering cleanup. Releases removed from that one project remain stored by
default. An interactive confirmation is limited to those newly unused
releases, and deletion repeats the complete reference check while holding the
store maintenance lock. A release referenced by another project is never
removed.

Most `python` launches remain read-only. When an unregistered or changed project
already has every exact locked item available, its first successful launch
refreshes the small project record without downloading anything. If anything is
missing, the launch still stops and asks for `nodephell install`. Until either
action succeeds, the previous record conservatively retains its releases. If a
project location or lock is unavailable, cleanup retains the record and its
releases until the project returns, its registration is moved, or the user
explicitly removes it. `nodephell project list` shows each record as current,
changed, or unavailable.

The command behavior is explicit:

- `init` creates a project definition interactively, then synchronizes it;
- `sync` creates or updates a lock when needed, then installs it;
- `lock` chooses versions and writes a lock;
- `install` follows the existing lock and supplies anything missing; and
- `update` deliberately chooses newer versions and changes the lock.

`lock` refuses to overwrite an existing lock, `install` refuses to operate
without one, and `update` resolves from `pyproject.toml` rather than treating
the old lock as input. These lower-level commands let automation separate
resolution from provisioning without complicating the everyday workflow.

## Python interpreters

NodePhell can use a registered stock CPython interpreter. On supported Linux
systems, it can also download a stock build, verify its hash, inspect it, and
store it under a path that includes its version, binary interface, and download
hash.

Interpreter acquisition is part of NodePhell's purpose: projects may require
different Python versions. Source trees and compiler build directories are not
part of the managed store and can be removed without deleting an installed
interpreter.

## Packages from the selected runtime

NodePhell may use a package installed alongside the selected interpreter when
its name and version exactly match the project lock. The generic per-user site
is excluded from inspection and launch. `nodephell resolve` labels this provider
as `selected-runtime`.

This provider proves installed name and version, not the original download
artifact. A package in NodePhell's managed store has the stronger identity of
filename, SHA-256, and installed-content fingerprint and is reported as
`managed-store`.

## Embedded applications

Some applications include their own Python interpreter. They can use external
packages only when those packages are compatible with that embedded Python.
NodePhell uses a small general interface for discovering the embedded Python
identity, acquiring optional application artifacts, and starting the
application with the chosen packages. The contract and ownership boundary are
documented in [Author an embedded-host adapter](host-adapters.md).

The FreeCAD reference plugin contains its probe, artifact discovery and
extraction, executable layout, and launch syntax. Core retains the host
registry, artifact verification, ABI matching, package composition, and
execution flow. Other applications use the same protocol through their own
plugins.

Adapters also declare entry-executable basenames, a suggested launcher name,
bounded project-relative search patterns, and whether their normal launcher is
graphical or console-based. Core presents candidates, confirms the complete
plan, updates the project atomically, and owns the resulting launcher and
application registry record. A direct executable path always bypasses search.

The FreeCAD adapter uses the application's supported `--python-path` and
`--module-path` options because an embedded interpreter may ignore
`PYTHONPATH`. The second option gives the selected package view priority before
FreeCAD loads workbenches. For that child process, NodePhell also points the
generic Python user base at an unused location. FreeCAD's separately configured
addon, module, macro, preference, and package directories remain available.

A host adapter may report package directories owned by its application. The
general package code can reuse an exact locked name and version from one of those
directories when NodePhell's own store does not have it. It reads standard
installed-package metadata and includes only files belonging to that release.
NodePhell records the external links in its generated view, detects missing or
changed files, and never changes or cleans the application's directory.
This proves that the same installed files are still present; it cannot prove
that another application's installation came from the download named in the
NodePhell lock. A NodePhell-owned stored copy remains the stronger choice and
takes priority when one exists.

Application-specific details live behind adapters. The package store, locks,
resolver, and Python launcher use only the generic host records and protocol.

## Scope boundaries

The initial release guarantees these boundaries:

- use upstream CPython and stock pip;
- leave distribution-managed Python and PEP 668 protections untouched;
- share unchanged, compatible package releases between projects;
- keep the storage layout understandable; and
- report selections and failures with an actionable remedy;
- treat external runtimes, applications, and package roots as read-only; and
- keep application behavior inside independently distributed adapters.

The initial release scope excludes:

- virtual-environment creation or activation;
- modification of the operating system's Python installation;
- general native-library and operating-system package management;
- application-specific policy in the package resolver; and
- maintained forks of CPython or pip.

See the [release roadmap](roadmap.md) for validation and hardening work.
