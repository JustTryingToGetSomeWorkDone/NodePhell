<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Embedded-host adapters

Ordinary Python remains NodePhell's primary path. Embedded-host adapters are a
small integration boundary for applications that own a Python interpreter and
must be launched through their own executable.

FreeCAD is the first reference plugin. It validates the interface, but it does
not define NodePhell's core package or runtime model.

## Boundary audit

The initial FreeCAD prototype mixed four kinds of behavior in `host.py`.

Application-specific behavior now belongs in `plugins/freecad`:

- recognizing and probing `FreeCADCmd`;
- importing the FreeCAD API to report the application version;
- finding FreeCAD-owned package directories;
- discovering AppImage releases and interpreting their filenames;
- extracting an AppImage and locating its command-line executable;
- deriving the graphical executable;
- supplying FreeCAD's `--python-path` and `--module-path` arguments; and
- isolating the generic Python user site for a FreeCAD launch.

Generic behavior remains in NodePhell core:

- loading and validating an adapter selected by host `kind`;
- storing host requirements and artifact records in project metadata;
- downloading and SHA-256-verifying locked artifacts;
- atomically committing extracted hosts to the managed store;
- recording and loading host registrations;
- matching host version, Python ABI, platform, and artifact provenance;
- selecting and composing locked package releases;
- preserving project references; and
- executing the adapter's command with its arguments and environment.

FreeCAD names remain intentionally in its adapter, reference tests, examples,
and documentation. They should not appear as policy branches in generic source.

## Adapter contract

An adapter plugin exposes an object named `ADAPTER`. The core validates these
capabilities when loading it:

- `accepts_executable(path)` cheaply recognizes a manually supplied command;
- `probe(path)` reports application and embedded-Python identity, launch
  environment, and application-owned package roots;
- `resolve_artifact(requirement, runtime)` selects an optional downloadable
  application artifact;
- `validate_artifact(artifact, runtime)` validates application-specific
  artifact naming and compatibility;
- `validate_probed_artifact(host, artifact)` verifies application-specific
  identity after extraction;
- `extract(archive, destination)` extracts an acquired artifact and returns its
  application root;
- `installed_executable(root)` locates the command-line executable;
- `gui_executable(host)` locates the graphical executable or reports that none
  is available;
- `launch_arguments(packages)` supplies application-specific package-path
  arguments; and
- `augment_environment(host, environment)` adds application-specific launch
  variables.

The common `EmbeddedHost` record and `HostAdapter` protocol live in
`nodephell.adapters.base`. The metadata and registry formats continue to use a
lowercase `kind`, so the refactor does not change existing project locks or
FreeCAD registrations.

## Discovery

NodePhell discovers adapters from two sources:

- Python packages may publish an entry point in the `nodephell.adapters` group.
  The entry-point name is the adapter `kind`, and its value loads either the
  adapter object or an object containing `ADAPTER`.
- An application installer or user may place `KIND.py` or
  `KIND/__init__.py` under `~/.local/share/nodephell/adapters`. Additional
  development directories can be listed in `NODEPHELL_ADAPTER_PATH`, separated
  by the platform path separator.

NodePhell core does not ship application adapters. A vendor or community
adapter can therefore evolve independently without waiting for a NodePhell
release. Multiple providers for one kind are rejected with their locations
rather than selected by installation order.

A packaged adapter declares its entry point like this:

```toml
[project.entry-points."nodephell.adapters"]
example = "example_nodephell:ADAPTER"
```

`nodephell host add` infers an adapter from the executable name when possible;
`--kind KIND` makes the choice explicit. Project installation and launch use
the `kind` stored in `[tool.nodephell.host]`. `nodephell host adapters` lists
the plugins currently visible to NodePhell.
