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

NodePhell removes an inherited `PYTHONPATH` and disables Python's generic user
site for project launches so unrelated packages cannot silently override the
project's selection. Its explicitly selected shared package view is still added.

## Shared, readable storage

Interpreters and packages are shared between projects rather than copied into a
directory inside every project. The directory names should remain useful to a
person inspecting them:

```text
~/.python/
  packages/
    package-name/
      exact-version/
        download-filename/
          download-hash/
            root/
  python313/
    interpreter/3.13.15/cpython-313-x86_64-linux-gnu/DOWNLOAD_HASH/
    compositions/
  runtimes/
    registry.json
```

The exact downloaded wheel is the unit NodePhell shares. A pure-Python or
stable-interface wheel can therefore be stored once and used by several Python
versions. Different native wheels naturally have different filenames or hashes
and remain separate.

For example, projects using Python 3.13 and Python 3.16 may both select the same
`lark-1.3.1-py3-none-any.whl`. Both point to one stored release rather than
installing two copies. NumPy wheels built separately for Python 3.13 and 3.16
have different filenames and hashes, so they remain separate automatically.

A package built from a source archive also includes the target Python version
line and binary interface below the download hash. Building the same source
under two Python versions can produce different files, so those results must not
be merged. A Python binary interface (often called an ABI) is the set of details
that compiled packages depend on.

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

A lock should mean that another installation selects the same inputs. New
shared-store entries record the package name, version, download filename, and
SHA-256 hash. They also record a fingerprint of the files pip installed.
NodePhell checks the short identity record during normal startup and checks the
full file fingerprint when the user runs `nodephell store check`. This keeps
normal launches quick while still making manual damage detectable. The version
remains easy to find in the directory tree, while the filename and hash prevent
two different builds from contaminating one another.

Installing a release and creating a combined package view are protected by
machine-local locks. If two NodePhell processes request the same item, one does
the work and the other reuses the completed result. A crash releases the lock
automatically. Cleanup can then recognize and remove the abandoned temporary
directory. Installs share a broader maintenance guard, while cleanup takes it
exclusively, so cleanup cannot remove a newly installed release before its
project record is written.

`nodephell store clean` reports what it would remove without changing anything.
`nodephell store clean --apply` removes entries that cannot be used, such as a
damaged release or broken combined view. A successful `nodephell install` also
records the project path, a fingerprint of its lock, and the exact shared
releases it uses under `~/.python/projects/`. Cleanup uses those records to find
healthy releases that no installed project uses.

Most `python` launches remain read-only. When an unregistered or changed project
already has every exact locked item available, its first successful launch
refreshes the small project record without downloading anything. If anything is
missing, the launch still stops and asks for `nodephell install`. Until either
action succeeds, the previous record conservatively retains its releases. If a
project or its lock disappears, dry-run cleanup explains that its record and
newly unused releases can be removed before `--apply` changes anything.
`nodephell project list` shows each record as current, changed, or missing.

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

The prototype may use a package installed alongside the selected interpreter
when its name and version exactly match the project lock. It does not count the
generic per-user site, because project launches disable that site to prevent
contamination. Otherwise it uses the shared package store. Checking only a
version is weaker than checking the exact downloaded file. The policy needs to
be stated clearly wherever NodePhell promises repeatable results.

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

The current FreeCAD adapter uses the application's supported `--python-path`
option because an embedded interpreter may deliberately ignore `PYTHONPATH`.
For that child process, it also points Python's generic user base at an unused
NodePhell location. FreeCAD can keep its user-site setting enabled, while the
ordinary user site stays off `sys.path` and FreeCAD's separately configured
addon and module directories remain available.

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
