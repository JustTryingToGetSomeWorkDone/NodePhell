<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell

No dependency hell: deterministic Python runtime and package selection without virtual environments.

NodePhell is an early-stage design and prototype. Its intended everyday interface is a user-level `python` or `python3` launcher that discovers project metadata, selects the required Python runtime and locked packages from shared immutable stores, and then starts an otherwise standard interpreter. When no project metadata exists, it delegates to the operating system's Python unchanged.

The separate `nodephell` command will manage runtimes, package stores, diagnostics, and lock-aware execution.

## Design goals

- Make `python script.py` work without activating an environment.
- Provide identical `python` and `python3` launchers for modern project tooling.
- Select Python itself from project metadata, not only Python packages.
- Share immutable runtimes and package releases between projects.
- Leave distribution-managed Python and PEP 668 protections intact.
- Allow `/usr/bin/python3` to remain an explicit system-Python bypass.
- Support embedded applications without application-specific absolute paths.
- Keep dependency and runtime selection deterministic for the life of a process.

See [Architecture](docs/architecture.md) for the current design direction.

## Status

The repository now contains a first launcher prototype. It uses only Python's
standard library and currently:

- discovers `pylock.toml` or `pyproject.toml` from the working directory or
  script location;
- selects an already-installed, registered CPython runtime;
- resolves exact package releases under
  `~/.python/pythonXY/packages/PROJECT/VERSION`;
- passes those release roots to an otherwise ordinary interpreter; and
- delegates to the interpreter that started the launcher when no project
  metadata is found.

It does not download runtimes or launch embedded Python hosts such as FreeCAD
yet. The initial package installer resolves exact direct pins and their full
dependency closure through stock pip; artifact-hash enforcement and shared
import-package composition remain in progress.

Managed interpreters use the same per-Python-version hierarchy as packages:

```text
~/.python/pythonXY/interpreter/FULL_VERSION/ABI/
```

For example, a normal upstream 3.16 development build is installed under
`~/.python/python316/interpreter/3.16.0a0/cpython-316-x86_64-linux-gnu/`.
Source and build directories are not stored there; the directory contains only
the installed interpreter prefix (`bin`, `include`, `lib`, and `share`).

## Trying the prototype

Run it directly from a checkout; installation is not required:

```console
cd /path/to/NodePhell
./bin/nodephell --version
./bin/nodephell runtime list
./bin/nodephell runtime add /path/to/python3.13 \
  --library-path /path/to/python/lib
```

From a project containing `pylock.toml` or `pyproject.toml`:

```console
/path/to/NodePhell/bin/nodephell install
/path/to/NodePhell/bin/nodephell resolve -c 'pass'
/path/to/NodePhell/bin/python -c 'import your_dependency'
```

`nodephell install` is an idempotent provisioning command, not activation. It
uses the selected interpreter's unmodified pip to install each missing exact
release into a temporary directory, validates its distribution metadata, and
then atomically moves it into the shared historical store. It does not change
the current shell or create anything inside the project.

When a project has no `pylock.toml`, NodePhell first asks stock pip to resolve
the complete dependency closure while ignoring currently installed packages.
It records the exact selected artifacts and hashes in a new `pylock.toml`, then
executes the per-release installation queue from that lock. Subsequent runs use
the lock directly and do not resolve again.

The `resolve` command prints the choice without starting the selected
interpreter. The `python` and `python3` shims accept ordinary Python arguments.
Outside a project, either shim leaves the environment unchanged and executes
the bootstrap interpreter.

The prototype accepts PEP 751-style `pylock.toml` files with
`lock-version = "1.0"`. Without a lock, every dependency in `pyproject.toml`
must currently use an exact direct `name==version` pin. Stock pip resolves
their transitive dependencies before NodePhell invokes the per-release install
steps with `--no-deps`.

Install-time enforcement of artifact hashes and merging distributions that
share a regular import package, such as the PySide6 family, are the next
installer milestones. Existing correctly merged store releases remain usable.

The source tests are intentionally dependency-free:

```console
cd /path/to/NodePhell
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
```

## License

NodePhell is licensed under the GNU General Public License, version 3 only.

`SPDX-License-Identifier: GPL-3.0-only`
