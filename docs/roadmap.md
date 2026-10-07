<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell release roadmap

NodePhell's initial feature scope is frozen. The core workflow is implemented;
work toward `0.1.0` is focused on validation, recovery, compatibility,
documentation, and release engineering.

## Release objective

A project with a committed `pylock.toml` should run through ordinary Python and
package commands without environment activation. A second machine should be
able to provision the same locked runtime and package downloads, and compatible
projects should reuse immutable stored releases safely.

Embedded-Python applications participate through independently distributed
adapter plugins. The same package selection and ownership rules apply to stock
Python and embedded hosts.

## Implemented feature set

### Project workflow

- Discover `pyproject.toml` and `pylock.toml` from a working directory or script.
- Create a lock with `nodephell lock`.
- Follow an existing lock with `nodephell install`.
- Re-resolve deliberately with `nodephell update`.
- Launch through identical `python` and `python3` shims.
- Expose locked `console_scripts` commands without activation.
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
- adapter entry-point and drop-in discovery; and
- FreeCAD console and offscreen GUI environment construction.

Manual development testing has used downloaded CPython 3.12 and 3.13 builds,
multi-package locked compositions, native packages, and a local FreeCAD build.

## Work remaining for 0.1.0

### Clean-system validation

- Test launcher installation from a fresh checkout.
- Test first lock and install with no existing NodePhell data.
- Repeat installation and confirm every immutable item is reused.
- Validate supported Linux architectures and Python version lines.
- Exercise installation with paths containing spaces and non-ASCII characters.

### Recovery and errors

- Exercise interruption during runtime, package, and host downloads.
- Exercise interruption during extraction and atomic commit.
- Verify `doctor`, `store check`, and `store clean` give a complete recovery
  path for every recoverable state.
- Improve network, certificate, timeout, and release-feed error messages.
- Verify unavailable drives and restored project locations end to end.

### Format and compatibility

- Review and freeze the initial `pylock.toml` schema.
- Record compatibility expectations for project, runtime, host, and store
  manifests.
- Decide how future format migrations will be detected and reported.
- Add automated checks for every supported management-Python version.

### Packaging and operations

- Build and install NodePhell as a distribution, not only from a checkout.
- Build and install the FreeCAD adapter independently.
- Verify entry-point discovery in packaged installations.
- Document backup, restore, cleanup, upgrade, and release procedures.
- Prepare release notes and a reproducible release checklist.

### Real-project acceptance

- Run a small pure-Python command-line project.
- Run a project with compiled wheels.
- Run two projects requiring conflicting versions of one package and command.
- Validate a packaged FreeCAD release in console and GUI modes.
- Validate read-only reuse and fallback when an application-owned package
  changes or disappears.

## Release acceptance

`0.1.0` is ready when:

- the clean-system workflow succeeds on every declared supported platform;
- repeat installation performs no unnecessary download or copy;
- interruption leaves either a valid committed item or removable staging work;
- diagnostics identify the selected providers and all known recovery actions;
- lock and manifest formats are documented and frozen for the release line;
- NodePhell core and the FreeCAD adapter install and discover independently;
- automated tests pass on all supported management-Python versions; and
- the user and adapter-authoring documentation matches the released commands.

## Post-0.1 candidates

These are outside the frozen initial scope and require separate design work:

- Windows and macOS support;
- broader dependency declaration forms;
- additional embedded-host adapters;
- deeper cross-wheel file deduplication;
- native-library or non-Python package integration; and
- alternatives to stock pip or upstream CPython distributions.
