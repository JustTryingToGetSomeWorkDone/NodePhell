<!-- SPDX-License-Identifier: GPL-3.0-only -->

![NodePhell](assets/nodephell-banner.png)

# NodePhell

**No dependency hell: shared Python runtimes and packages without virtual environments.**

NodePhell is a shared Python runtime and package system for Linux.

Projects declare the Python version and packages they need. NodePhell obtains the missing pieces, verifies them, preserves exact runtimes and package artifacts for reuse, and selects the correct combination automatically whenever the project runs.

After setup, normal use is simply:

```console
python app.py
```

There is no virtual environment to activate, no private dependency tree to rebuild for every project, and no need to modify the operating system's Python.

Old projects can keep using the Python generation they were written for. New projects can use newer releases. Compatible projects reuse the same stored runtimes and package artifacts instead of installing unnecessary copies.

NodePhell can also extend the same model to Linux applications that embed Python. Adapter plugins let those applications use locked package sets, reuse exact packages they already own, and obtain missing packages without putting application-specific behavior into NodePhell core.

The initial feature set is complete. Current work is focused on real-project validation and release hardening for `0.1.0`.

## Why NodePhell is different

Python dependency conflicts are usually handled by building a separate environment around each project:

```text
choose Python
- create an environment
- activate it
- install another dependency set
- keep the correct environment selected
- rebuild or repair it when necessary
```

NodePhell moves that work into the computer:

```text
project metadata
- exact Python runtime
- exact package artifacts
- shared verified storage
- automatic selection at launch
```

The project still gets an exact, deterministic package set. The difference is that isolation comes from **selection**, not from giving every project its own private copy of a Python environment.

**NodePhell is not another environment format. It is a shared store plus a selection layer.**

## One Python history, shared

NodePhell treats interpreters and package releases as reusable artifacts.

A project that needs an older Python release does not have to move just because another project uses a newer one. NodePhell can preserve multiple CPython runtimes and select the exact runtime recorded by each project's lock.

Packages work the same way. If an exact compatible artifact already exists, NodePhell reuses it instead of downloading another copy. Pure-Python packages may be shared across compatible Python versions, while incompatible native builds remain separate automatically.

```text
                         shared NodePhell store

                    CPython 3.11 ---------- project A
                                        +-- project B

                    CPython 3.13 ---------- project C

                    lark 1.3.0 ------------ project A
                                        +-- project B
                                        +-- project C

                    requests 2.32 --------- project A
                                        +-- project C

                    NumPy cp311 build ----- project A
                                        +-- project B

                    NumPy cp313 build ----- project C

verified external
application package ----------------------- application D
```
Compatible projects reuse the same stored interpreter and package artifacts. NodePhell only keeps separate copies when compatibility actually requires them, such as different Python ABIs or platform-specific native builds.

This lets NodePhell preserve more of Python's history while often storing fewer duplicate files than per-project environments.

## Everyday use

NodePhell itself currently requires Python 3.11 or newer.

Install its launchers once from a checkout:

```console
./bin/nodephell launcher install
nodephell --version
```

For a new project:

```console
nodephell init
```

For an existing project with `pyproject.toml`:

```console
nodephell sync
```

After that, use Python normally:

```console
python app.py
python3 -m unittest
pytest
```

There is nothing to activate.

NodePhell uses standard project metadata. A typical project might contain:

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

`pyproject.toml` expresses human intent. NodePhell generates `pylock.toml` with the exact CPython runtime, dependency closure, artifacts, and hashes needed to reproduce the selected state.

When requirements change, run:

```console
nodephell sync
```

## What happens when Python starts

Inside a NodePhell project, the launcher:

1. finds the project's lock;
2. selects the exact locked CPython runtime;
3. finds each locked package from an approved provider;
4. builds the required package view;
5. starts the process.

A package may come from:

- NodePhell's managed package store;
- the selected Python runtime; or
- a verified external application package store.

If an exact compatible copy already exists and can be verified, NodePhell can reuse it instead of downloading another one.

Project launches exclude the generic Python user site and inherited `PYTHONPATH`, preventing unrelated local packages from silently contaminating the locked package set.

Outside a NodePhell project, `python` and `python3` delegate to the operating system's Python unchanged.

## Package commands without activation

Python distributions often provide commands through `console_scripts`.

NodePhell preserves that behavior without a virtual environment. If the selected package set provides `pytest`, for example:

```console
pytest
```

works normally.

NodePhell-managed shims resolve the calling project at invocation time, so different projects can use different versions of the same command without activating different shells or environments.

Only commands declared by valid Python distribution metadata are exposed. Arbitrary executables found in an application directory are not turned into NodePhell commands.

## Python applications can use NodePhell too

NodePhell is not limited to programs started with `python`.

Many Linux applications embed Python and maintain their own package directories. An adapter plugin lets such an application participate in the same runtime and package-selection system.

An adapter describes only application-specific facts, such as:

- how to identify the application's embedded Python;
- which Python ABI and platform it uses;
- which package directories it already owns;
- how additional package paths are supplied; and
- how command-line or graphical modes are launched.

NodePhell core continues to handle package selection, ABI matching, hashes, shared storage, project references, and execution.

This also lets NodePhell reuse exact verified packages that an application already has instead of downloading duplicate copies. Missing locked packages can be supplied separately without modifying the application's own package store.

FreeCAD is the current reference adapter. It is a plugin, not a special case in NodePhell core.

Adapters may be installed as Python entry points or discovered from NodePhell's standard local plugin location. See the adapter documentation for authoring, packaging, scanning, and validation details.

## Status

The initial feature set is complete. Current development is focused on proving that the existing system behaves reliably across real projects and release-hardening `0.1.0`.

Current validation includes ordinary Python projects, historical runtimes, native packages and ABI boundaries, package commands, shared package reuse, cleanup and integrity checking, external package stores, and embedded Python applications.

## Current platform scope

- NodePhell itself requires Python 3.11 or newer.
- Automatic CPython and FreeCAD artifact acquisition currently targets supported Linux builds.
- Direct dependencies may omit a version, specify an exact version, or use a version range.
- `pylock.toml` always records exact releases.
- Dependency markers and direct URL or path requirements are not yet supported.
- FreeCAD is the current reference embedded-host adapter.

## Documentation

- [User guide](docs/user-guide.md) — installation, daily workflows, commands, cleanup, and troubleshooting.
- [Architecture](docs/architecture.md) — runtime selection, storage, locking, ownership, package composition, and embedded-host design.
- [Roadmap](docs/roadmap.md) — release status, validation, and hardening work.
- [Host adapter guide](docs/host-adapters.md) — human-oriented adapter authoring.
- [AI adapter brief](docs/adapter-authoring-ai.md) — implementation contract and constraints for coding agents.
- [FreeCAD reference adapter](plugins/freecad/README.md) — reference plugin usage and development notes.

Run `nodephell --help` or add `--help` after a command group for the complete command reference.

## License

NodePhell is licensed under the GNU General Public License, version 3 only.

`SPDX-License-Identifier: GPL-3.0-only`
