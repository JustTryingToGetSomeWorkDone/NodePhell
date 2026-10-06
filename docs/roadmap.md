<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Roadmap

NodePhell has proven its core selection model. The next phase is to turn the
prototype into an everyday Linux tool that another user can install, provision,
and understand without knowing its internal store layout.

## Completed foundation

The current prototype can:

- discover projects from `pyproject.toml` or `pylock.toml`;
- select and launch stock CPython without modifying the system interpreter;
- resolve complete dependency closures with stock pip;
- install exact package releases into immutable, reusable stores;
- compose distributions that contribute to the same regular import package;
- lock, acquire, probe, and launch FreeCAD in headless or GUI mode; and
- preserve exact runtime and host artifact provenance in generated locks.

### Managed Python runtime acquisition

Python runtime downloading is already part of the completed foundation.
Both `nodephell install` and `nodephell runtime install SPEC` use the managed
acquisition path. In the project installation flow, NodePhell can:

1. Query python-build-standalone release metadata for a compatible Linux build.
2. Select an exact CPython version and `install_only` archive.
3. Record the archive URL, platform, and SHA-256 in `pylock.toml`.
4. Download into temporary storage and verify the locked digest.
5. Extract and probe the interpreter before accepting its identity.
6. Atomically commit it under:

   ```text
   ~/.python/pythonXY/interpreter/FULL_VERSION/ABI/ARTIFACT_SHA256/
   ```

7. Register its executable, ABI, platform, required library paths, and artifact
   provenance for later selection.

Subsequent provisioning requires the same artifact identity and does not resolve
against the latest-release feed again.

## v0.2: Acceptance project

Create a small, checked-in FreeCAD example that proves the complete workflow
from an empty NodePhell data store:

- declare the Python, package, and FreeCAD requirements;
- run `nodephell install` to generate a lock and provision every artifact;
- create a deterministic model through `nodephell host run`;
- open the generated document through `nodephell host gui`;
- document expected output and a short manual inspection checklist; and
- retain a lightweight automated smoke path that does not require a display.

This milestone should be completed before broadening the feature set. It proves
that runtime acquisition, package composition, embedded-host selection, and GUI
startup work together as one user workflow.

## v0.3: User installation

Make NodePhell usable without commands that point into a source checkout:

- install `nodephell`, `python`, and `python3` launchers under `~/.local/bin`;
- generate launchers with an explicit bootstrap interpreter to avoid recursion;
- verify that `/usr/bin/python3` remains an unchanged system-Python bypass;
- provide an uninstall path that removes launchers without deleting managed
  runtimes or packages; and
- diagnose `PATH` ordering when the compatibility launchers are not active.

## v0.4: Package commands

Expose console scripts supplied by selected package releases without creating a
virtual environment:

- discover entry points from locked distributions;
- generate deterministic user-facing shims;
- resolve each shim through the invoking project's lock;
- handle duplicate command names explicitly; and
- keep scripts fixed to the selected runtime and package composition for the
  life of the process.

## v0.5: Lock lifecycle and diagnostics

Make lock changes deliberate and observable:

- add explicit lock, update, and validation commands;
- distinguish lock generation from artifact provisioning in diagnostics;
- explain why a runtime, package, or embedded host was selected;
- add a `doctor` command for registries, missing files, hashes, and `PATH` setup;
- define recovery behavior for interrupted installs and stale registrations;
  and
- add safe cleanup and garbage-collection commands for unreferenced artifacts.

## v0.6: Hardening

- add continuous integration for supported Linux and Python combinations;
- exercise clean-store installation and lock reuse in integration tests;
- test concurrent provisioning and artifact-store races;
- improve network failure and release-metadata error reporting;
- define compatibility policy for lock-format changes; and
- prepare an initial user-facing release process.

## Deferred work

These are valuable, but they should not distract from the milestones above:

- non-exact direct requirements in unlocked `pyproject.toml` files;
- environment markers and broader wheel-selection cases;
- Windows and macOS acquisition and launchers;
- pure-Python, ABI3, or global content-addressed deduplication;
- additional embedded applications beyond FreeCAD; and
- replacement of stock pip or patches to CPython.
