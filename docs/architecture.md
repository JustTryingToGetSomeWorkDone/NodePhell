<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Architecture direction

## User interface

NodePhell separates its identity from its everyday compatibility interface:

- `python` and `python3` are identical optional user-level launchers placed
  ahead of the system interpreter in the user's `PATH`.
- `nodephell` manages runtimes, package stores, locks, and diagnostics.
- `/usr/bin/python3` bypasses NodePhell and retains normal distribution behavior.

The launcher scripts must bootstrap from an absolute system interpreter rather
than `#!/usr/bin/env python3`. Once the optional `python3` shim is ahead of the
system interpreter in `PATH`, an `env` shebang would otherwise recurse through
the shim. Packaged launchers may instead use an installer-generated absolute
bootstrap path.

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

For each exact pin, the prototype first accepts the same installed version from
the selected interpreter's ordinary site directories. If that exact version is
not present, it selects the corresponding historical release. The ordinary
site is inspected once per launch; dependency resolution does not recursively
start Python processes.

The prototype reads the store already used by the experimental pip and CPython
work:

```text
~/.python/
  python313/
    interpreter/
      3.13.15/
        cpython-313-x86_64-linux-gnu/
          bin/
          include/
          lib/
          share/
    packages/
      distribution-name/
        exact-version/
```

`pythonXY` is the common home for one Python major/minor line. Installed
interpreter prefixes live under `interpreter/FULL_VERSION/ABI`, while package
releases remain under `packages`. The exact version is kept as a readable path
component; the ABI component prevents incompatible normal, debug, or
free-threaded builds from sharing an installation. Platform information that
is not already represented by the ABI will become part of the runtime artifact
manifest when automatic downloads are implemented.

Source checkouts and compiler build trees are deliberately outside this
hierarchy. They are working material rather than managed runtimes and may be
deleted without changing the stored interpreter.

Each exact-version directory must look like a normal installation root. A
distribution is never subdivided by its import packages. Related distributions
may still have separate roots when that is how they are published. NodePhell is
responsible for composing any shared regular import tree correctly; that policy
must not require changes to pip.

An inherited `PYTHONPATH` is discarded for project launches so it cannot
silently override locked releases. With no discovered project, the complete
environment is preserved.

## Embedded applications

Pure Python projects may select any compatible stored interpreter. Embedded applications are constrained by the Python ABI against which the host was compiled. For example, a FreeCAD binary built for CPython 3.13 cannot simply load CPython 3.11; NodePhell must select the host build and runtime as a compatible pair.

## Prototype scope

The first launcher prototype should:

- select among already-installed CPython runtimes;
- parse project metadata;
- assemble deterministic package paths;
- execute ordinary Python scripts; and
- delegate cleanly to system Python when no project is selected.

Automatic runtime downloads, embedded-host launching, lock generation, and
console-script shims can follow after the core selection model is reliable.

## Installation flow

`nodephell install` provisions a lock; it never activates an environment. For
each exact release unavailable from the selected interpreter's ordinary site
or historical store, NodePhell invokes that interpreter's unmodified pip with
`--no-deps` and an isolated temporary target. It validates the resulting
distribution name and version before atomically renaming the target into the
historical store. A failed download, build, or validation leaves no selected
release behind.

The initial implementation assumes the project metadata enumerates the full
dependency closure. Artifact-hash enforcement and safe composition of multiple
distributions contributing to one regular import package are intentionally
separate milestones. Those policies belong to NodePhell rather than patches to
pip.

Runtime registrations are stored in `~/.python/runtimes/registry.json`. The
registry records an absolute executable, its probed implementation/version/ABI,
and only the shared-library directories needed to start it. It is data, not a
selection override: project metadata remains the source of the version
requirement.

The prototype keeps one active executable for each implementation, version,
ABI, and platform identity. Registering another executable with the same
identity replaces the earlier registration. A future runtime-artifact lock will
distinguish reproducible builds more precisely; path ordering is deliberately
not used as a selection policy.
