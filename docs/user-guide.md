<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell user guide

NodePhell is an early prototype for running Python projects without virtual
environments. A project says which Python and packages it needs. NodePhell puts
missing items in shared storage, then its `python` and `python3` launchers choose
the right ones whenever that project runs.

## Use NodePhell from a checkout

The prototype does not install its commands into `PATH` yet. For the current
shell, put the checkout's `bin` directory first:

```console
export PATH=/path/to/NodePhell/bin:$PATH
```

You can instead use full paths such as
`/path/to/NodePhell/bin/nodephell`. The two Python launchers are identical.

## Prepare a project

NodePhell looks for `pylock.toml` or `pyproject.toml`. A minimal
`pyproject.toml` looks like this:

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

Direct dependencies must currently have exact versions. From the project
directory, provision it once:

```console
nodephell install
```

NodePhell chooses an exact Python build, asks stock pip for the complete
dependency list, writes `pylock.toml`, downloads anything missing, and records
the project. Keep `pylock.toml` with the project if you want another machine to
select the same downloads.

After that, use Python normally:

```console
python app.py
python3 -m unittest
python -c 'import requests; print(requests.__version__)'
```

There is no activation command and nothing needs to be repeated in each new
terminal. Run `nodephell install` again after changing the project's
requirements or lock.

## What the launcher does

Inside a project, `python` and `python3`:

1. find the project by looking upward from the working directory or script;
2. select the exact locked interpreter and package downloads;
3. start that interpreter with only the selected shared package view.

An inherited `PYTHONPATH` and Python's generic user-site directory are ignored
for project launches. This prevents unrelated user-installed packages from
leaking into the project. NodePhell's explicitly selected package directories
remain available.

Outside a recognized project, the launcher passes control to the operating
system Python without changing it. `/usr/bin/python3` is always a direct bypass
on systems where it is provided there.

## Commands

| Command | What it does |
| --- | --- |
| `nodephell install [PROJECT]` | Prepare the current project, or the directory given. |
| `nodephell run [--] PYTHON-ARGS` | Run Python through NodePhell. The `python` shim is shorter. |
| `nodephell resolve [--] PYTHON-ARGS` | Show the interpreter and package paths that would be used. |
| `nodephell runtime install SPEC` | Download and register a matching stock CPython build. |
| `nodephell runtime add PYTHON` | Register an interpreter already on the machine. |
| `nodephell runtime list` | List the system bootstrap and registered interpreters. |
| `nodephell project list` | List known projects as current, changed, or missing. |
| `nodephell store check` | Read stored releases and report damaged files. |
| `nodephell store clean` | Preview entries that can be removed. |
| `nodephell store clean --apply` | Remove the entries shown by the preview. |

`runtime install` accepts a Python version requirement, for example:

```console
nodephell runtime install '>=3.13,<3.14'
```

To register a locally installed interpreter that needs a shared-library path:

```console
nodephell runtime add /path/to/python3.13 \
  --library-path /path/to/python/lib
```

Use `nodephell resolve` when a selection is surprising. Its output includes the
project file, Python executable, Python version, and combined package path.

## Experimental FreeCAD host

FreeCAD is being used as a demanding embedded-Python test. Register an existing
command-line executable:

```console
nodephell host add /path/to/FreeCADCmd
```

Declare the host in the project's `pyproject.toml`:

```toml
[tool.nodephell.host]
kind = "freecad"
requires = "==27.1.0"
```

Use the version reported by your FreeCAD build. After the project is installed,
run a script or start the graphical application with:

```console
nodephell host run script.py
nodephell host gui
```

The embedded Python must have the same binary interface as the Python selected
for the project. NodePhell supplies the locked packages through FreeCAD's
`--python-path` option. For this launch only, the generic Python user site is
redirected to an unused location so it cannot contaminate the project. This
does not change FreeCAD's saved setting or remove its own addon, module, macro,
or preference paths.

## Where files live

NodePhell keeps managed files below `~/.python`:

```text
~/.python/
├── packages/NAME/VERSION/DOWNLOAD_FILENAME/SHA256/root/
├── projects/PROJECT_NAME-PATH_HASH.json
├── runtimes/registry.json
└── pythonXY/
    ├── interpreter/FULL_VERSION/PYTHON_ABI/DOWNLOAD_SHA256/
    └── compositions/
```

`packages` contains the physical package files. Compatible projects and Python
versions reuse them. `compositions` contains generated links that present each
project's selected packages as a normal import directory. `projects` records
which shared releases are still in use. The lock files under `~/.python/locks`
coordinate simultaneous NodePhell processes; they are internal bookkeeping.

Do not move individual directories inside this tree by hand. The names and
versions are visible for inspection, while NodePhell relies on the deeper
download and hash directories to distinguish incompatible files safely.

## Checking and cleaning the store

Run a health check whenever files may have been changed or copied manually:

```console
nodephell store check
```

Cleanup is deliberately a two-step operation:

```console
nodephell store clean
nodephell store clean --apply
```

The first command changes nothing. Read its list before using `--apply`.
NodePhell keeps releases referenced by current projects and conservatively keeps
the previous releases for a project whose lock has changed until that project
runs successfully or is installed again.

## Current limits

- Automatic interpreter downloads currently target supported Linux systems.
- The launchers must still be placed on `PATH` manually.
- Commands supplied by installed packages do not have NodePhell launchers yet.
- Locking, installing, and updating are not yet separate commands.
- FreeCAD host support is experimental; other embedded applications are not
  supported yet.

The [roadmap](roadmap.md) describes planned work. The
[architecture document](architecture.md) explains the design in more detail.
