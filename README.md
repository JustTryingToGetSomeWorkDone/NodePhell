<!-- SPDX-License-Identifier: GPL-3.0-only -->

![NodePhell](assets/nodephell-banner.png)

# NodePhell

No dependency hell: deterministic Python runtime and package selection without virtual environments.

NodePhell is an early-stage, general-purpose launcher and shared package store.
It is meant to prevent dependency conflicts and packages leaking between
projects. Its everyday interface is the ordinary `python` or `python3` command;
the separate `nodephell` command installs and manages what projects need.

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

## One package copy when possible

Virtual environments commonly install another copy of the same dependency for
every project. NodePhell stores an exact downloaded wheel once for the whole
machine. Any project and Python version that can use that same wheel shares the
stored release.

Different builds are not forced together. Native wheels with different files
or hashes remain separate, and packages built from source are kept with the
Python version line and binary interface they were built for. This reduces
duplicate files without hiding incompatible packages behind one name and
version.

## Design goals

- Make `python script.py` work without activating an environment.
- Provide identical `python` and `python3` launchers.
- Select Python itself as well as Python packages from project metadata.
- Share unchanged runtimes and package releases between projects.
- Use upstream CPython and stock pip.
- Leave distribution-managed Python and PEP 668 protections intact.
- Keep `/usr/bin/python3` as an explicit distro-Python bypass.
- Keep runtime selection fixed for the life of a process.
- Support embedded-Python applications through a small general interface,
  without building application-specific rules into NodePhell's core.

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
- asks stock pip for every package the project needs, including dependencies;
- generates `pylock.toml` when a project does not have one;
- installs missing exact releases in temporary directories before moving
  completed installs into the shared store;
- stores one physical copy of an exact wheel and shares it across every
  compatible project and Python version;
- keeps genuinely different wheels and source builds separate;
- records the download filename and SHA-256 beside each stored release and
  checks that identity before reuse;
- records a fingerprint of the installed files for explicit health checks;
- prevents simultaneous installs from writing the same release or combined
  package view at the same time;
- selects ordinary packages or exact stored releases under
  `~/.python/packages/DISTRIBUTION/VERSION/DOWNLOAD/HASH`;
- combines related distributions into normal import views under
  `~/.python/pythonXY/compositions/`;
- launches stock CPython through the `python` and `python3` shims.

The prototype also contains experimental FreeCAD host support. FreeCAD is a
useful test because it has an embedded Python interpreter and compiled
dependencies. It is not part of NodePhell, and downloading or managing FreeCAD
is not a core project goal.

Managed interpreters and packages share one readable hierarchy:

```text
~/.python/
├── packages/DISTRIBUTION/VERSION/DOWNLOAD_FILENAME/SHA256/root/
└── pythonXY/
    ├── interpreter/FULL_VERSION/PYTHON_ABI/DOWNLOAD_SHA256/
    └── compositions/
```

For example, an upstream 3.16 development interpreter may live at
`~/.python/python316/interpreter/3.16.0a0/cpython-316-x86_64-linux-gnu/SHA256/`.
Source and compiler build trees remain outside the managed store.
The same wheel file is stored once even when several Python versions can use
it. Packages built from source include the target Python version line and binary
interface because two builds of the same source are not necessarily identical.

The next priorities are:

- install the launchers into the user's `PATH`;
- make locking, installing, and updating clearly separate actions;
- track which project locks still use each healthy stored release; and
- safely remove healthy releases after their final project stops using them.

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
```

From a project containing `pylock.toml` or `pyproject.toml`:

```console
/path/to/NodePhell/bin/nodephell install
/path/to/NodePhell/bin/nodephell resolve -c 'pass'
/path/to/NodePhell/bin/python3 app.py
```

The store maintenance commands are:

```console
/path/to/NodePhell/bin/nodephell store check
/path/to/NodePhell/bin/nodephell store clean
/path/to/NodePhell/bin/nodephell store clean --apply
```

`store check` reads every stored file and reports damage. `store clean` is a
dry run. With `--apply`, it removes only unusable releases, broken generated
views, and abandoned work from interrupted installs. Healthy releases are kept
until NodePhell can prove that no project lock uses them.

## Experimental embedded-application test

The current source includes a FreeCAD experiment. It checks whether an
application's embedded Python is compatible with the project's packages and can
then start the application with those packages available.

This code is a test of a future general adapter interface, not a promise that
NodePhell will install or manage FreeCAD. Its current configuration looks like:

```toml
[tool.nodephell.host]
kind = "freecad"
requires = "==1.1.3"
```

The experimental commands are:

```console
/path/to/NodePhell/bin/nodephell host run model.py
/path/to/NodePhell/bin/nodephell host gui
```

This area still needs redesign so application-specific downloading and launch
details do not live in NodePhell's package and runtime core.

Without a lock, direct dependencies in `pyproject.toml` must currently use exact
`name==version` pins. Stock pip finds their dependencies, NodePhell writes the
result to `pylock.toml`, and each package is installed separately so compatible
releases can be shared by many projects. The exact download filename and hash
decide whether two projects may share a stored wheel; a matching version number
alone is not enough.

`nodephell resolve` displays the runtime and package selection without starting
Python. The source tests have no third-party dependencies:

```console
cd /path/to/NodePhell
PYTHONPATH=src /usr/bin/python3 -m unittest discover -s tests -v
```

## License

NodePhell is licensed under the GNU General Public License, version 3 only.

`SPDX-License-Identifier: GPL-3.0-only`
