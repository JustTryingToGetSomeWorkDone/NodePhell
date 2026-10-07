<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Roadmap

NodePhell aims to make Python projects dependable without creating a separate
virtual environment for every project. A project states which Python and
packages it needs. NodePhell installs anything missing into shared storage, then
the ordinary `python` or `python3` command selects the right combination.

FreeCAD is one of our real-world test projects because it combines Python,
compiled packages, and an application with an embedded Python interpreter. It
is not part of NodePhell, and NodePhell should not become a FreeCAD installer or
contain FreeCAD-specific policy in its core design.

## What works today

The source prototype can:

- find a project's `pyproject.toml` or `pylock.toml`;
- select a registered Python interpreter;
- download a stock CPython build on supported Linux systems;
- ask stock pip to resolve a project's complete package list;
- install exact package versions into shared storage;
- store one exact wheel once and reuse it across compatible Python versions;
- distinguish different builds by their download filename and SHA-256;
- keep source-built packages separate when they target different Python binary
  interfaces;
- detect changed stored files through `nodephell store check`;
- serialize simultaneous installs of the same release;
- preview cleanup by default and require `--apply` before removing anything;
- remove unusable releases, broken combined views, and abandoned installation
  work;
- record the releases used by each successfully installed project;
- register a project on its first successful launch when every locked item is
  already available;
- keep releases when a registered project's lock changed but has not yet been
  reinstalled;
- identify healthy releases that no registered project uses;
- combine related distributions, such as the PySide6 family, into a normal
  import layout; and
- ignore the generic Python user site while preserving the package paths chosen
  for the project; and
- run a project with the selected Python and packages without activation.

The prototype now has a generic embedded-host adapter boundary with FreeCAD as
its first separately packaged reference implementation. Application probing,
acquisition, and launch syntax are separated from the core registry, ABI
matching, package composition, and execution flow. Additional applications
remain future work.

## Shared package storage achieved

Package storage is no longer divided into copies under every `pythonXY`
directory. Exact wheels now live in one machine-wide, readable store:

```text
~/.python/packages/NAME/VERSION/DOWNLOAD_FILENAME/SHA256/root/
```

The package name and version remain easy to find. The filename and hash appear
only where they are needed to prove that two projects selected the same wheel.
Compatible projects share one physical copy. Different wheels remain separate,
and source builds add the Python version line and binary interface they target.

## Project-aware cleanup achieved

Each successful install records its project path, lock fingerprint, and exact
shared releases. A first launch can create the same record without an install
when all locked items are already present. Cleanup retains anything named by a
current project record. A changed lock retains its previous releases until a
successful launch or install refreshes it. An unavailable project or lock keeps
its record and releases protected, allowing removable drives to be disconnected
without looking like project deletion.

`nodephell store clean` explains every candidate without changing it. Only
`nodephell store clean --apply` removes those entries. `nodephell project list`
shows current, changed, and unavailable project records. `nodephell project
move OLD NEW` safely migrates a registration when the lock fingerprint still
matches; `nodephell project remove` is the explicit signal that a deleted
project's references may be released.

Projects, runtimes, and embedded hosts can now be explicitly removed from their
registries. These commands leave project files, interpreters, applications, and
shared packages untouched. Removing a project record makes its unreferenced
packages eligible for the existing preview-first cleanup process.
An explicit `--delete` can also remove a NodePhell-downloaded runtime or host,
but only after ownership is proven and no live project record still uses it.
External interpreters and applications are never deletion targets.

## Everyday commands achieved

A user should not need paths into a source checkout.

- Install `nodephell`, `python`, and `python3` launchers under `~/.local/bin`.
- Make `python` and `python3` behave the same way.
- Keep `/usr/bin/python3` available as a direct route to the operating system's
  Python.
- Avoid launcher loops when NodePhell starts Python.
- Provide a launcher uninstall command that keeps stored interpreters and
  packages.
- Give a plain explanation when `PATH` ordering prevents the launchers from
  being used.

The intended daily workflow is then simply:

```console
nodephell lock
nodephell install
python app.py
```

`nodephell install` is provisioning, not activation, and does not need to run in
every terminal.

## Deliberate lock commands achieved

A user should know when NodePhell is creating a lock, following one, or changing
one.

`lock` creates but never replaces a lock, `install` follows an existing lock
without resolving, and `update` deliberately re-resolves from project metadata.
The existing lock remains in place if resolution fails. Safe cleanup for stored
items no project uses is also available.

## Diagnostics achieved

`nodephell doctor` checks launcher PATH setup, adapter discovery, runtime and
host registries, project records, and shared-store integrity in one pass.
`nodephell resolve` identifies why a runtime was selected and whether each
package comes from the managed store, selected runtime, or embedded host.
`nodephell host resolve` adds the selected application and its package roots
without launching it.

## Installed package commands achieved

Projects often depend on commands as well as importable modules. Those commands
now work without activating an environment. Installation discovers executable
entry points declared by exact locked distributions and creates small shared
launchers. Verified external distributions are supported through their pinned
metadata without trusting nearby executable files. Each invocation selects the
calling project's Python, package composition, and embedded host when required.
Two locked packages providing the same command are rejected rather than
silently ordered, and the selected environment remains fixed while the command
runs.

## Prove the design with real projects

Use several projects to test the general design, including a small pure-Python
project, packages with compiled extensions, the PySide6 package family, and
FreeCAD as an embedded-Python stress test.

Initial isolated testing has covered downloaded stock Python 3.12 and 3.13,
transitive pure-Python dependencies, NumPy, different versions of one package,
sharing compatible downloads across Python versions, and two processes asking
for the same missing release at once. It has also covered the split PySide6
family under both Python versions and supplied a 20-package locked composition
to a local FreeCAD build in console and offscreen GUI modes. Testing a stock
packaged embedded host and more applications remains future work.

The host interface can also report application-owned package directories.
NodePhell can reuse exact locked releases from them read-only, while its own
selected view takes priority during FreeCAD startup. Real-world testing of this
path and its recovery behavior is the next step.

For FreeCAD, the important question is whether NodePhell can supply the correct
Python packages without modifying FreeCAD or CPython. Downloading and managing
FreeCAD itself is not a core project goal. Any application-specific support
should live behind a small, replaceable adapter rather than in the package and
runtime selection code.

Adapters are distributable independently through the standard
`nodephell.adapters` Python entry-point group or as application-supplied
drop-ins under the user's data directory. NodePhell core contains no
application adapters, allowing a vendor to ship compatibility updates with the
application while duplicate providers fail explicitly.

## Prepare a first dependable release

- Test clean installation and repeat installation on supported Linux systems.
- Test two processes installing or reading the same stored package at once.
- Recover cleanly from interrupted downloads and installs.
- Improve network error messages.
- Settle the initial lock format before the first public release.
- Add automated checks for the supported Python versions.
- Document backup, cleanup, recovery, and release procedures.

## Later work

These may be valuable, but they should not distract from the basic workflow:

- Windows and macOS support;
- broader forms of Python dependency declarations;
- support for more embedded applications;
- file-by-file deduplication between different wheels, but only if it provides
  a meaningful benefit without making the store difficult to understand;
- system-library and non-Python package management; and
- replacing stock pip or maintaining a CPython fork.
