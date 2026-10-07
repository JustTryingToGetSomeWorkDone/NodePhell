<!-- SPDX-License-Identifier: GPL-3.0-only -->

# How NodePhell is intended to work

NodePhell is a general solution for Python dependency conflicts and accidental
cross-project contamination. It is not tied to FreeCAD or any other
application, and it is not intended to become a full operating-system package
manager.

## The user experience

Inside a project, the ordinary commands select the Python and packages recorded
for that project:

```console
nodephell install
python app.py
```

There is no environment to create, activate, or remember. Outside a recognized
project, NodePhell's `python` launcher hands control to the operating system's
Python without changing its environment. `/usr/bin/python3` remains a direct
bypass to the operating-system interpreter.

`nodephell` is the management command. It installs missing items, manages locks,
and reports problems. `python` and `python3` are identical everyday launchers.

## What happens when Python starts

1. NodePhell looks upward from the project or script for `pylock.toml` or
   `pyproject.toml`.
2. If no project is found, it starts the system Python normally.
3. If a project is found, it reads the required Python version and package list.
4. It selects the matching stored interpreter and package releases.
5. It builds one package search path and starts Python.
6. That selection stays unchanged until the process exits.

NodePhell removes an inherited `PYTHONPATH` for project launches so unrelated
packages cannot silently override the project's selection.

## Shared, readable storage

Interpreters and packages are shared between projects rather than copied into a
directory inside every project. The directory names should remain useful to a
person inspecting them:

```text
~/.python/
  python313/
    interpreter/
      3.13.15/
        cpython-313-x86_64-linux-gnu/
          ARTIFACT_HASH/
            bin/
            lib/
    packages/
      package-name/
        exact-version/
  runtimes/
    registry.json
```

The current package layout is still being refined. Package name and version
will remain prominent, but native packages also need enough information to keep
incompatible builds apart. Two packages that have the same public version are
not necessarily interchangeable if they were built for different systems,
Python binary interfaces, or downloaded source files. A Python binary interface
(often called an ABI) is the set of details that compiled packages depend on.

Each stored package release must look like a normal installation. NodePhell does
not split one distribution into separate import directories. When several
distributions contribute files to the same import package, as PySide6 does,
NodePhell builds a combined view made from links. It does not copy those files
for every project.

## Locks and installation

For a new project, stock pip resolves the complete dependency list. NodePhell
records the chosen Python, packages, downloaded files, and hashes in
`pylock.toml`. Installation then uses stock pip to place each package release in
temporary storage before moving it into the shared store.

A lock should mean that another installation selects the same inputs. The
prototype verifies hashes while downloading, but it does not yet retain and
check enough information about the original download when reusing every
existing store entry. Fixing that gap is the next storage milestone.

The finished command behavior should be explicit:

- `lock` chooses versions and writes a lock;
- `install` follows the existing lock and supplies anything missing; and
- `update` deliberately chooses newer versions and changes the lock.

The current prototype combines some of those steps. It must not silently change
a lock once those commands are separated.

## Python interpreters

NodePhell can use a registered stock CPython interpreter. On supported Linux
systems, the prototype can also download a stock build, verify its hash, inspect
it, and store it under a path that includes its version, binary interface, and
download hash.

Interpreter acquisition is part of NodePhell's purpose: projects may require
different Python versions. Source trees and compiler build directories are not
part of the managed store and can be removed without deleting an installed
interpreter.

## Ordinary installed packages

The prototype may use an ordinary site-package when its name and version exactly
match the project lock. Otherwise it uses the historical shared store. This
preserves the behavior proven by the earlier CPython prototype, but checking
only a version is weaker than checking the exact downloaded file. The policy
needs to be stated clearly wherever NodePhell promises repeatable results.

## Embedded applications

Some applications include their own Python interpreter. They can use external
packages only when those packages are compatible with that embedded Python.
NodePhell needs a small general interface for discovering the embedded Python
identity and starting the application with the chosen packages.

FreeCAD is our first demanding test of that interface. The repository currently
contains experimental code to register, download, and launch FreeCAD builds.
That experiment is not the intended core architecture. NodePhell should prove
that it can serve compatible dependencies to FreeCAD without taking ownership
of installing or managing FreeCAD itself.

Application-specific details should be isolated behind adapters. The package
store, locks, resolver, and Python launcher must remain application-independent.

## Boundaries

NodePhell should:

- use upstream CPython and stock pip;
- leave distribution-managed Python and PEP 668 protections untouched;
- share unchanged, compatible package releases between projects;
- keep the storage layout understandable; and
- explain failures in language that helps a user fix them.

NodePhell should not:

- create or activate virtual environments;
- modify the operating system's Python installation;
- become a general native-library or application installer;
- put FreeCAD-specific rules into the package resolver; or
- fork CPython or pip unless a future requirement cannot reasonably be solved by
  the launcher.

See the [roadmap](roadmap.md) for the order in which these gaps will be closed.
