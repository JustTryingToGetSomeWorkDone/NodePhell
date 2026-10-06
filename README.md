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

The import-selection behavior is currently proven in experimental CPython, pip, and FreeCAD branches. The next stage is moving that behavior into a stock-Python-compatible launcher while keeping those branches as reference implementations.

## License

NodePhell is licensed under the GNU General Public License, version 3 only.

`SPDX-License-Identifier: GPL-3.0-only`
