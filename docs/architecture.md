<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Architecture direction

## User interface

NodePhell separates its identity from its everyday compatibility interface:

- `python` is an optional user-level launcher placed ahead of the system interpreter in the user's `PATH`.
- `nodephell` manages runtimes, package stores, locks, and diagnostics.
- `/usr/bin/python3` bypasses NodePhell and retains normal distribution behavior.

NodePhell must never replace the operating system's Python installation or modify distribution-managed `site-packages`.

## Launch flow

1. Discover `pylock.toml` or `pyproject.toml` from the script or project.
2. If neither exists, execute the configured system Python without altering its environment.
3. Read the required Python implementation and version.
4. Select a matching immutable runtime by version, ABI, platform, and architecture.
5. Select compatible ordinary packages where policy permits, then locked releases from the historical package store.
6. Construct the module search path once and execute the selected interpreter.
7. Keep the selection fixed for the lifetime of the process.

Project metadata must eventually identify an exact runtime artifact for reproducibility. A `requires-python` range alone can select a compatible runtime but cannot fully lock its build.

## Storage principles

- Runtime and package releases are immutable after installation.
- Multiple projects reuse the same compatible artifacts.
- Native artifacts are separated by interpreter ABI and platform.
- Integrity hashes from locks or trusted runtime manifests are verified before use.
- A real user or system `site-packages` directory is never used as a mutable symlink farm.

Selected package roots should be passed directly to stock Python when possible. If a unified filesystem view is required, it must be immutable and keyed by the lock identity so concurrent projects cannot alter one another's imports.

## Embedded applications

Pure Python projects may select any compatible stored interpreter. Embedded applications are constrained by the Python ABI against which the host was compiled. For example, a FreeCAD binary built for CPython 3.13 cannot simply load CPython 3.11; NodePhell must select the host build and runtime as a compatible pair.

## Initial scope

The first launcher prototype should:

- select among already-installed CPython runtimes;
- parse project metadata;
- assemble deterministic package paths;
- execute ordinary Python scripts; and
- delegate cleanly to system Python when no project is selected.

Automatic runtime downloads, embedded-host launching, source-distribution builds, and console-script shims can follow after the core selection model is reliable.
