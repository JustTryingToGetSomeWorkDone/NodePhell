<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Changelog

## Unreleased

- Grouped the management package browser by name with paginated name lists;
  selecting a package opens its individual versions and builds for review.
- Added terminal colors for management menu headings, option numbers, actions,
  and statuses, plus separated inventory rows and indented long-path wrapping.
  Color respects `NO_COLOR`, dumb terminals, and redirected output.
- Added `nodephell manage`, a numbered menu for runtime, package, project, and
  host inventories, integrity checking, and selected cleanup with previews and
  explicit confirmation. Existing CLI commands remain available.
- Management inventories retain registrations for missing executables and
  separate unregistering records from deleting managed files. Package browsing
  uses metadata-only checks; full integrity checking is an explicit operation.
- Selected cleanup rechecks candidates under the maintenance lock, and unused
  package removal now retains referenced releases even when damaged.
- Moved discovery aliases and application hints into editable
  `assets/import-mappings.toml`, with `--mappings FILE` for independent additions
  and overrides. Removed redundant same-name distribution entries.
- Application-module suggestions now require explicit `--application` context
  or a matching project host declaration instead of global name assumptions.
- Added interactive `nodephell discover` for reviewing static Python imports
  and creating a dependency-only `pyproject.toml` without executing project
  code or downloading packages.
- Discovery filters standard-library and local modules, labels optional,
  conditional, function-local, and development imports, supports exclusions,
  and offers editable distribution suggestions and version constraints.
- Existing project metadata is report-only. Existing requirements files can
  be selected as a synchronization input instead of reconstructing imports.

## 0.2.0 - 2026-11-18

### Added

- Added persistent pip requirements-file profiles for `sync`, `lock`, and
  `update`, including nested-file fingerprinting and stock-pip handling of
  markers, index directives, constraints, and direct archives.
- Added credential-free HTTPS PEP 508 direct references, compatible duplicate
  constraints, uv named indexes, and centrally prepared editable uv path
  sources.
- Kept accelerator-specific profiles isolated from the project's default
  dependencies and preserved profile/source identity across lock updates.
- Added a generic completeness warning and failure guidance for replacement
  requirements inputs that omit separately documented prerequisite packages.

### Fixed

- Reject insecure or credential-bearing resolved artifact URLs before locking.
- Recover missing SHA-256 values by downloading the exact resolved HTTPS
  artifact through stock pip and computing its digest before writing the lock.
  Installation continues to require hashed artifacts.

### Validation and documentation

- Recorded successful PCB Timelapse 1.0.0 and 1.3.0 rendering from KiCad through
  the NodePhell Python shim using the same locked dependency configuration.
- Recorded successful ACE-Step 1.5 ROCm web UI startup and music generation on
  an AMD Radeon 880M using managed CPython 3.12.15 and a complete requirements
  profile, including a compatible torchao pin.
- Expanded requirements-profile guidance, compatibility evidence, and README
  installation and usage documentation.
- The independently distributed FreeCAD adapter remains at version 0.1.0.

## 0.1.0 - 2026-10-10

NodePhell's first public release provides shared, immutable Python runtimes and
package releases selected automatically from each project's lock, without
per-project virtual environments.

### Included

- Interactive initialization plus separate lock, install, update, sync, option,
  troubleshooting, diagnostic, and lifecycle commands.
- Verified acquisition and reuse of historical CPython runtimes, exact wheels,
  runtime-specific native builds, and compatible external distributions.
- Standard PEP 621 projects, backend-supplied dynamic dependencies, Poetry
  dependency declarations, PEP 508 markers, PEP 685 normalized option names,
  and PEP 735 dependency groups.
- Supported PEP 751 `pylock.toml` import and output, with
  `nodephell.lock.toml` for exact runtime and embedded-host data.
- Editable project metadata and project-specific `console_scripts` commands
  without activation.
- Integrity checks, conservative cleanup, project references, atomic commits,
  concurrent-writer protection, and guided recovery messages.
- Independently distributed embedded-host adapters, with FreeCAD as the
  reference plugin for console and GUI launches.

### Validation

The automated suite covers the runtime, package, project, launcher, store,
adapter, host, application, and recovery layers. Real-project smoke testing is
recorded for MNE-Python, Frogmouth, Flask, Black, Pillow, ir_datasets, and
orjson, including pure Python, compiled wheels, native editable builds,
multiple build backends, dynamic metadata, and package commands.

Launcher validation covers version reporting, adapter discovery, source
checkout installation, system-Python fallback, and clean launcher removal.

### Scope

The validated release platform is Linux x86-64 with a management Python of
3.11 or newer. Runtime acquisition also recognizes Linux AArch64, but it has
not received the same release validation. Direct URL and local-path dependency
requirements, richer multi-environment PEP 751 locks, Windows, and macOS are
outside this release.
