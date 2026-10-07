<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Roadmap

NodePhell aims to make Python projects dependable without creating a separate
virtual environment for every project. A project states which Python and
packages it needs. NodePhell installs anything missing into shared storage, then
the ordinary `python` or `python3` command selects the right combination.

FreeCAD is one of our real-world test projects because it combines Python,
compiled packages, and an application with an embedded Python interpreter. It
is not part of NodePhell, and NodePhell should not become a FreeCAD installer or
contain FreeCAD-specific policy in its core design.

## What works today

The source prototype can:

- find a project's `pyproject.toml` or `pylock.toml`;
- select a registered Python interpreter;
- download a stock CPython build on supported Linux systems;
- ask stock pip to resolve a project's complete package list;
- install exact package versions into shared storage;
- store one exact wheel once and reuse it across compatible Python versions;
- distinguish different builds by their download filename and SHA-256;
- keep source-built packages separate when they target different Python binary
  interfaces;
- combine related distributions, such as the PySide6 family, into a normal
  import layout; and
- run a project with the selected Python and packages without activation.

The prototype also contains experimental FreeCAD host code. It has useful ideas
for testing embedded Python applications, but it is not yet a finished or
general NodePhell feature.

## Shared package storage achieved

Package storage is no longer divided into copies under every `pythonXY`
directory. Exact wheels now live in one machine-wide, readable store:

```text
~/.python/packages/NAME/VERSION/DOWNLOAD_FILENAME/SHA256/root/
```

The package name and version remain easy to find. The filename and hash appear
only where they are needed to prove that two projects selected the same wheel.
Compatible projects share one physical copy. Different wheels remain separate,
and source builds add the Python version line and binary interface they target.

The remaining storage work is hardening rather than another redesign:

- detect incomplete or manually damaged entries and explain how to repair them;
- test two processes installing the same release at once; and
- add safe cleanup for releases that are no longer used.

## Make NodePhell an everyday command

A user should not need paths into a source checkout.

- Install `nodephell`, `python`, and `python3` launchers under `~/.local/bin`.
- Make `python` and `python3` behave the same way.
- Keep `/usr/bin/python3` available as a direct route to the operating system's
  Python.
- Avoid launcher loops when NodePhell starts Python.
- Provide a simple uninstall command that leaves stored interpreters and
  packages alone unless the user asks to remove them.
- Give a plain explanation when `PATH` ordering prevents the launchers from
  being used.

The intended daily workflow is then simply:

```console
nodephell install
python app.py
```

`nodephell install` is run when project requirements change. It is not an
activation command and does not need to be run in every terminal.

## Make locks understandable and deliberate

A user should know when NodePhell is creating a lock, following one, or changing
one.

- Separate `lock`, `install`, and `update` behavior clearly.
- Never silently replace a working lock with newer versions.
- Explain which Python and packages were selected and why.
- Report missing files, changed hashes, stale registrations, and incompatible
  builds in ordinary language.
- Add a `doctor` command that checks the store and launcher setup.
- Add safe cleanup for stored items that no project still uses.

## Make installed package commands work

Projects often depend on commands as well as importable modules. Those commands
should work without activating an environment.

- Find commands supplied by locked packages.
- Create small launchers that select the calling project's Python and packages.
- Handle two packages providing the same command without silently choosing one.
- Keep the selected Python and packages fixed while the command runs.

## Prove the design with real projects

Use several projects to test the general design, including a small pure-Python
project, packages with compiled extensions, the PySide6 package family, and
FreeCAD as an embedded-Python stress test.

For FreeCAD, the important question is whether NodePhell can supply the correct
Python packages without modifying FreeCAD or CPython. Downloading and managing
FreeCAD itself is not a core project goal. Any application-specific support
should live behind a small, replaceable adapter rather than in the package and
runtime selection code.

## Prepare a first dependable release

- Test clean installation and repeat installation on supported Linux systems.
- Test two processes installing or reading the same stored package at once.
- Recover cleanly from interrupted downloads and installs.
- Improve network error messages.
- Settle the initial lock format before the first public release.
- Add automated checks for the supported Python versions.
- Document backup, cleanup, recovery, and release procedures.

## Later work

These may be valuable, but they should not distract from the basic workflow:

- Windows and macOS support;
- broader forms of Python dependency declarations;
- support for more embedded applications;
- file-by-file deduplication between different wheels, but only if it provides
  a meaningful benefit without making the store difficult to understand;
- system-library and non-Python package management; and
- replacing stock pip or maintaining a CPython fork.
