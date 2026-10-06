<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell

No dependency hell: deterministic Python runtime and package selection without virtual environments.

NodePhell is an early-stage launcher and shared package-store prototype. Its
everyday interface is the ordinary `python` or `python3` command; the separate
`nodephell` command provisions and manages what projects need.

## Intended workflow

A traditional environment workflow commonly looks like:

```text
create environment → activate it → install dependencies → run the program
```

NodePhell's intended workflow is:

```console
nodephell install   # once per lock state
python app.py       # normal use from then on
```

When `python app.py` runs, the launcher automatically discovers the project,
selects the exact locked CPython build and package releases,
constructs the package path, and starts the program. These are not recurring
environment-management steps for the user. `nodephell install` is provisioning,
not activation; rerun it when the lock changes or stored artifacts are missing.

## Why not another environment?

Virtual environments and Conda-style environments associate a dependency set
with a project-specific environment that must be selected or activated.
NodePhell instead preserves compatible interpreters and exact package releases
in shared reusable stores. Project metadata describes the required combination,
and the launcher selects it automatically.

NodePhell does not create a project environment, enter a special shell, or aim
to replace Conda's native-library and system-package use cases. Outside a
recognized project, the launcher delegates to the operating system's Python
without changing its environment.

## Design goals

- Make `python script.py` work without activating an environment.
- Provide identical `python` and `python3` launchers.
- Select Python itself as well as Python packages from project metadata.
- Share immutable runtimes and package releases between projects.
- Use upstream CPython and stock pip.
- Leave distribution-managed Python and PEP 668 protections intact.
- Keep `/usr/bin/python3` as an explicit distro-Python bypass.
- Keep runtime selection fixed for the life of a process.
- Eventually support embedded applications without application-specific paths.

See [Architecture](docs/architecture.md) for the detailed design and
[Roadmap](docs/roadmap.md) for the target milestones.

## Current status

The standard-library-only prototype currently:

- discovers `pylock.toml` or `pyproject.toml` from the working directory or
  script location;
- selects an already-installed, registered CPython runtime or downloads one
  from python-build-standalone on Linux;
- locks the exact runtime archive under `[tool.nodephell.runtime]` and verifies
  its SHA-256 before extraction;
- resolves the complete dependency closure through stock pip;
- generates `pylock.toml` when a project does not have one;
- provisions missing exact releases with stock pip and atomic staging;
- selects ordinary packages or immutable releases under
  `~/.python/pythonXY/packages/DISTRIBUTION/VERSION`;
- composes selected immutable releases into deterministic import views under
  `~/.python/pythonXY/compositions/`;
- locks, downloads, verifies, and atomically installs official FreeCAD
  AppImages on Linux;
- probes FreeCAD's embedded Python ABI against the locked project runtime and
  launches headless scripts or the GUI with `nodephell host run` and
  `nodephell host gui`; and
- launches stock CPython through the `python` and `python3` shims.

Managed interpreter prefixes and packages share one readable hierarchy:

```text
~/.python/pythonXY/
├── interpreter/FULL_VERSION/ABI/ARTIFACT_SHA256/
└── packages/DISTRIBUTION/VERSION/

~/.python/hosts/
├── registry.json
└── freecad/VERSION/PLATFORM/ARTIFACT_SHA256/
```

For example, an upstream 3.16 development interpreter may live at
`~/.python/python316/interpreter/3.16.0a0/cpython-316-x86_64-linux-gnu/SHA256/`.
Source and compiler build trees remain outside the managed store.

The next user-facing gaps are:

- a permanent FreeCAD acceptance project;
- installation of the compatibility launchers into the user's `PATH`; and
- console-script exposure.

The ordered implementation plan is maintained in [Roadmap](docs/roadmap.md).

## Trying the prototype

Run NodePhell directly from a checkout:

```console
cd /path/to/NodePhell
./bin/nodephell --version
./bin/nodephell runtime list
./bin/nodephell runtime add /path/to/python3.13 \
  --library-path /path/to/python/lib
./bin/nodephell runtime install '>=3.13,<3.14'
./bin/nodephell host add /path/to/freecadcmd
./bin/nodephell host list
```

From a project containing `pylock.toml` or `pyproject.toml`:

```console
/path/to/NodePhell/bin/nodephell install
/path/to/NodePhell/bin/nodephell resolve -c 'pass'
/path/to/NodePhell/bin/python3 app.py
```

For a headless FreeCAD project, add this to `pyproject.toml` before installing:

```toml
[tool.nodephell.host]
kind = "freecad"
requires = "==1.1.3"
```

`nodephell install` selects the newest matching official AppImage for the
locked runtime's Python line and platform, records its URL and SHA-256 in
`pylock.toml`, verifies it before extraction, and registers the probed host.
Then run the project script through that exact embedded host:

```console
/path/to/NodePhell/bin/nodephell host run model.py
/path/to/NodePhell/bin/nodephell host gui
```

NodePhell provisions packages with a locked stock CPython runtime, then permits
the embedded launch only when FreeCAD's probed implementation, SOABI, and
platform match that runtime. Python micro versions may differ when they share
the same extension ABI identity, such as CPython 3.11 builds with `cp311`
wheels.

Without a lock, direct dependencies in `pyproject.toml` must currently use
exact `name==version` pins. Stock pip resolves their transitive dependencies
while ignoring currently installed packages, and NodePhell records the selected
runtime and package artifacts with their hashes in `pylock.toml`. It then
installs missing distributions separately with `--no-deps`, preserving one
independently reusable store root per release. Subsequent runs use the exact
locked runtime build without querying the latest-release feed again.
Locked FreeCAD projects likewise reuse the exact digest-qualified host without
querying the FreeCAD release feed again.

`nodephell resolve` displays the runtime and package selection without starting
Python. The source tests have no third-party dependencies:

Set `NODEPHELL_HOME=/some/path` to use an alternate NodePhell data home. This is
useful for clean smoke tests because runtimes and packages will be stored under
`$NODEPHELL_HOME/.python` instead of the normal home directory.

```console
cd /path/to/NodePhell
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
```

## License

NodePhell is licensed under the GNU General Public License, version 3 only.

`SPDX-License-Identifier: GPL-3.0-only`
