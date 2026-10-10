<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell release record and roadmap

NodePhell `0.1.0` is the first public release. Its core workflow, packaging,
documentation, and initial compatibility validation are complete. This file
records that release boundary and keeps later ideas from becoming implicit
requirements for the finished initial release.

## Release objective

A project with a committed standard or NodePhell lock should run through ordinary Python and
package commands without environment activation. A second machine should be
able to provision the same locked runtime and package downloads, and compatible
projects should reuse immutable stored releases safely.

Embedded-Python applications participate through independently distributed
adapter plugins. The same package selection and ownership rules apply to stock
Python and embedded hosts.

## Maintainer adoption path

NodePhell should be useful before an application makes deep architectural
changes. Maintainers can adopt it in three practical stages:

1. **Keep the existing embedded Python.** Ship the compiled application with a
   `pyproject.toml`, `nodephell.lock.toml`, and a small adapter plugin. One
   `nodephell install` command should register the application, provide its
   locked packages, and create its ordinary launcher.
2. **Let NodePhell supply Python.** Stop bundling a separate Python runtime and
   let the application accept the interpreter selected by NodePhell. The
   adapter then becomes much smaller because it no longer needs to describe an
   application-owned Python installation.
3. **Support the standard NodePhell launch contract.** Applications that can
   identify and start themselves through the common contract should need only
   declarative project metadata, with no application-specific plugin.

Stage one is implemented through bundled and independently installed adapters.
Stages two and three remain possible future simplifications; they should reduce
maintainer work rather than move application-specific behavior into NodePhell
core.

## Implemented feature set

### Project workflow

- Discover `pyproject.toml`, standard `pylock.toml`, and
  `nodephell.lock.toml` from a working directory or script.
- Read and write the supported single-environment PEP 751 lock profile, while
  isolating exact runtime and host artifacts in the NodePhell lock format.
- Create and prepare a project interactively with `nodephell init`.
- Accept unversioned, exact, and ranged direct package requirements.
- Synchronize a changed definition and install it with `nodephell sync`.
- Detect a stale lock from its normalized definition fingerprint.
- Create a lock with `nodephell lock`.
- Follow an existing lock with `nodephell install`.
- Re-resolve deliberately with `nodephell update`.
- Launch through identical `python` and `python3` shims.
- Expose locked `console_scripts` commands without activation.
- Prepare projects with a standard build system as editable source installs,
  including their distribution metadata and console commands.
- Select and deselect standard optional features and dependency groups through
  an interactive terminal checklist, then synchronize their locked packages.
- Explain runtime, package, and host selection as JSON.

### Runtime and package storage

- Select registered CPython interpreters by requirement, ABI, and platform.
- Download, verify, and register supported python-build-standalone artifacts.
- Store exact wheels by normalized name, version, filename, and SHA-256.
- Separate source builds by target Python line and ABI.
- Share compatible releases across projects and Python versions.
- Compose distributions that contribute to the same import tree.
- Reuse exact packages from the selected runtime with user-site isolation.
- Reuse exact external distributions from verified `METADATA` and `RECORD`
  files without taking ownership of them.

### Integrity and lifecycle

- Commit package and host installations atomically.
- Serialize concurrent writes to the same release or composition.
- Record installed file fingerprints for explicit store checks.
- Detect invalid releases, broken compositions, and abandoned staging work.
- Preview cleanup before applying it.
- Protect releases referenced by current, changed, or unavailable projects.
- Keep deselected releases by default and remove only explicitly confirmed,
  rechecked releases that no registered project uses.
- Move and remove project registrations explicitly.
- Unregister runtimes and hosts independently from deleting managed downloads.
- Diagnose launchers, adapters, registries, projects, and storage with
  `nodephell doctor`.

### Embedded hosts

- Discover adapter plugins through `nodephell.adapters` entry points and
  application/user drop-ins.
- Probe and register existing applications.
- Lock, download, verify, extract, and register adapter-provided artifacts.
- Match application version, embedded Python ABI, platform, and provenance.
- Launch console, GUI, and package commands through the selected host.
- Discover project-local application builds through adapter-declared patterns.
- Configure and refresh bound application launchers through `nodephell app`.
- Link and validate local adapter projects through `nodephell plugin add`.
- Bootstrap applications and bundled, explicitly declared plugins through
  ordinary `nodephell install` and `nodephell sync` commands.
- Keep application-owned package directories read-only.
- Reject duplicate adapter and command providers explicitly.

The FreeCAD plugin is the reference adapter and is packaged separately under
`plugins/freecad`.

## Validation completed

Automated coverage includes:

- runtime and host registry round trips and removal;
- verified runtime and host artifact installation;
- concurrent installers requesting one missing package release;
- interrupted or invalid package staging cleanup;
- exact wheel reuse across Python versions;
- runtime-specific source builds and native wheels;
- pure-Python dependencies, NumPy, and conflicting versions;
- PySide6 family composition;
- external distribution identity and change detection;
- current, changed, moved, and unavailable project references;
- managed package-command shims and duplicate-provider rejection;
- interactive project initialization and create/update/reuse synchronization;
- standard PEP 621 static and backend-supplied dynamic dependencies, plus
  Poetry runtime and development-group declarations;
- PEP 685 option-name normalization and PEP 735 dependency-group includes;
- project-owned editable metadata and command discovery;
- optional-feature and dependency-group selection, persistence, and cleanup;
- adapter entry-point and drop-in discovery;
- bounded application discovery, binding, launcher ownership, and refresh;
- local adapter plugin linking and removal; and
- FreeCAD console and offscreen GUI environment construction.

Manual development testing has used downloaded CPython 3.12, 3.13, and 3.15
builds, multi-package locked compositions, compiled wheels, native editable
projects, and FreeCAD console and GUI launches. Real-project findings for
MNE-Python, Frogmouth, Flask, Black, Pillow, ir_datasets, and orjson are tracked
in the [project compatibility evidence](project-compatibility.md) ledger.

## 0.1.0 release acceptance

The release boundary is accepted with:

- clean project initialization, locking, installation, launch, repeated reuse,
  diagnostics, and removal workflows;
- atomic store writes, abandoned-stage detection, integrity checks, and
  conservative cleanup under concurrent and interrupted operations;
- documented and versioned lock, runtime, host, store, project-reference, and
  application-registry formats;
- independent NodePhell and FreeCAD distribution builds, packaged adapter
  discovery, and installed-distribution launchers;
- real-project evidence across pure-Python packages, compiled wheels, native
  source builds, dynamic build metadata, Poetry metadata, and conflicting
  versions; and
- passing automated coverage for all implemented subsystems.

Release validation was performed on Linux x86-64. The implementation recognizes
Linux AArch64 runtime and FreeCAD artifacts, but equivalent hardware validation
is deferred until that platform is available. This is a declared support limit,
not unfinished `0.1.0` work.

## Post-0.1 candidates

These are later ideas that require separate design work:

- Windows and macOS support;
- direct-reference dependency declarations and richer Poetry marker variants;
- additional embedded-host adapters;
- a standard handoff for applications that use a NodePhell-supplied Python;
- a declarative launch contract that removes the need for custom adapters;
- explicit project commands that create user-owned launchers bound to the
  project's locked Python and packages, allowing small programs to run by name
  from any directory without activation, executable bits, or manual `PATH`
  work; command creation must remain opt-in, refuse collisions and shadowing,
  and never require `sudo`;
- deeper cross-wheel file deduplication;
- native-library or non-Python package integration; and
- alternatives to stock pip or upstream CPython distributions.
