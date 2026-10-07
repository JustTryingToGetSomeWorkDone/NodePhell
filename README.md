<!-- SPDX-License-Identifier: GPL-3.0-only -->

![NodePhell](assets/nodephell-banner.png)

# NodePhell

NodePhell selects a project's Python interpreter and exact package set without
creating a virtual environment for every project. Interpreters and package
releases live in shared storage; the `python`, `python3`, and installed package
commands select the correct combination automatically.

The initial feature set is complete. Current work is focused on real-project
validation and release hardening for `0.1.0`.

## Quick start

NodePhell currently requires Python 3.11 or newer to run. From a checkout:

```console
./bin/nodephell launcher install
nodephell --version
```

Create a project definition:

```toml
[project]
name = "example"
version = "0.1.0"
requires-python = ">=3.13,<3.14"
dependencies = [
    "lark==1.3.1",
    "requests==2.32.5",
]
```

Direct dependencies currently require exact versions. Lock and install the
project once:

```console
nodephell lock
nodephell install
```

Then use ordinary commands with no activation step:

```console
python app.py
python3 -m unittest
```

After changing `pyproject.toml`, update deliberately:

```console
nodephell update
nodephell install
```

`lock` creates a lock, `install` follows the existing lock, and `update`
re-resolves and replaces the lock. Installation never changes dependency
choices on its own.

## How selection works

Inside a project, a NodePhell launcher:

1. discovers `pylock.toml` from the working directory or script location;
2. selects the locked CPython runtime;
3. selects each exact package from the shared store, the runtime, or a verified
   embedded-host package directory;
4. builds the package view and starts the process.

The generic Python user site and inherited `PYTHONPATH` are excluded from a
project launch. Outside a NodePhell project, `python` and `python3` delegate to
the operating system's Python unchanged.

Inspect a selection without running it:

```console
nodephell resolve
nodephell host resolve
```

The JSON output identifies the runtime selection reason and the provider for
every package: `managed-store`, `selected-runtime`, or `external-host`.

## Shared storage

NodePhell stores exact package downloads once and reuses compatible releases:

```text
~/.python/
├── hosts/
├── locks/
├── packages/NAME/VERSION/DOWNLOAD_FILENAME/SHA256/root/
├── projects/PROJECT_NAME-PATH_HASH.json
├── runtimes/registry.json
└── pythonXY/
    ├── interpreter/FULL_VERSION/PYTHON_ABI/DOWNLOAD_SHA256/
    └── compositions/
```

Wheel filename and SHA-256 distinguish different builds with the same package
name and version. Source builds also include their target Python version and
ABI. Generated compositions merge compatible package trees, including split
families such as PySide6, without copying the package files per project.

The store supports integrity checking and preview-first cleanup:

```console
nodephell store check
nodephell store clean
nodephell store clean --apply
nodephell doctor
```

Project records protect referenced releases. Temporarily unavailable projects
retain their references; `project move` updates a moved registration, and
`project remove` explicitly releases it.

## Package commands

`nodephell install` creates managed shims in `~/.local/bin` for locked
`console_scripts` entry points. A shim resolves the calling project each time,
so different projects can use different versions of the same tool.

Command metadata may come from:

- a fingerprinted NodePhell-managed release;
- an exact package already present in the selected runtime; or
- an external package whose `METADATA` and `RECORD` passed NodePhell's
  read-only verification.

Duplicate command providers are rejected. Executable files without matching
Python distribution metadata do not receive shims.

## Embedded hosts and adapter plugins

An embedded-host adapter connects NodePhell to an application that runs Python
through its own executable. The adapter reports the embedded Python identity,
application-owned package directories, launch arguments, and any optional
downloadable artifacts. NodePhell core handles registries, artifact hashes,
ABI matching, package selection, project references, and execution.

Adapters are discovered as Python entry points or drop-in modules. The FreeCAD
adapter under `plugins/freecad` is the reference implementation.

```console
nodephell host adapters
nodephell host add /path/to/FreeCADCmd
nodephell host list
```

A project selects an adapter by kind:

```toml
[tool.nodephell.host]
kind = "freecad"
requires = "==1.1.3"
```

Use the version reported by `nodephell host list` for an existing application.
Once locked and installed:

```console
nodephell host resolve
nodephell host run script.py
nodephell host gui -- model.FCStd
```

Adapter documentation:

- [Author an embedded-host adapter](docs/host-adapters.md): human-oriented
  walkthrough, packaging, and validation.
- [AI adapter implementation brief](docs/adapter-authoring-ai.md): compact
  contract and constraints for an AI coding agent.
- [FreeCAD adapter](plugins/freecad/README.md): reference plugin usage and
  development notes.

## Commands and documentation

- [User guide](docs/user-guide.md): installation, daily workflows, command
  reference, cleanup, and troubleshooting.
- [Architecture](docs/architecture.md): selection, storage, locking, ownership,
  and embedded-host design.
- [Roadmap](docs/roadmap.md): release status, completed validation, and
  hardening work.

Run `nodephell --help` for the complete command list or add `--help` after a
command group such as `nodephell host --help`.

## Current platform scope

- NodePhell runs on Python 3.11 or newer.
- Automatic CPython and FreeCAD artifact acquisition currently targets
  supported Linux builds.
- Direct dependencies in `pyproject.toml` currently use exact `name==version`
  requirements.
- FreeCAD is the current reference embedded-host adapter.

## Development

The core test suite has no third-party test dependencies:

```console
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
```

The suite covers runtime and host registries, locking, atomic installation,
shared package compositions, cleanup, command shims, adapter discovery, and
FreeCAD adapter behavior.

## License

NodePhell is licensed under the GNU General Public License, version 3 only.

`SPDX-License-Identifier: GPL-3.0-only`
