<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell

No dependency hell: deterministic Python runtime and package selection without virtual environments.

NodePhell is an early-stage design and prototype. Its intended everyday interface is a user-level `python` launcher that discovers project metadata, selects the required Python runtime and locked packages from shared immutable stores, and then starts an otherwise standard interpreter. When no project metadata exists, it delegates to the operating system's Python unchanged.

The separate `nodephell` command will manage runtimes, package stores, diagnostics, and lock-aware execution.

## Design goals

- Make `python script.py` work without activating an environment.
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

It does not download runtimes or packages yet, and it does not launch embedded
Python hosts such as FreeCAD yet.

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
/path/to/NodePhell/bin/nodephell resolve -c 'pass'
/path/to/NodePhell/bin/python -c 'import your_dependency'
```

The `resolve` command prints the choice without starting the selected
interpreter. The `python` shim accepts ordinary Python arguments. Outside a
project, the shim leaves the environment unchanged and executes the bootstrap
interpreter.

The prototype accepts PEP 751-style `pylock.toml` files with
`lock-version = "1.0"`. Without a lock, every dependency in `pyproject.toml`
must currently use an exact `name==version` pin.

The source tests are intentionally dependency-free:

```console
cd /path/to/NodePhell
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
```

## License

NodePhell is licensed under the GNU General Public License, version 3 only.

`SPDX-License-Identifier: GPL-3.0-only`
