<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Changelog

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

The packaged NodePhell and FreeCAD wheels were also installed together in an
isolated environment to verify version reporting, adapter entry-point
discovery, launcher installation, system-Python fallback, and clean launcher
removal.

### Scope

The validated release platform is Linux x86-64 with a management Python of
3.11 or newer. Runtime acquisition also recognizes Linux AArch64, but it has
not received the same release validation. Direct URL and local-path dependency
requirements, richer multi-environment PEP 751 locks, Windows, and macOS are
outside this release.
