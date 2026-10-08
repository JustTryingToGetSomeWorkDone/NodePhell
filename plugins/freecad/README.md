<!-- SPDX-License-Identifier: GPL-3.0-only -->

# NodePhell FreeCAD adapter

This plugin connects FreeCAD's embedded CPython runtime to NodePhell. It
provides the `freecad` host kind and can:

- recognize and probe `FreeCADCmd`/`freecadcmd`;
- report FreeCAD and embedded-Python identity;
- report FreeCAD-owned Python package directories;
- select compatible Linux AppImage releases from FreeCAD's release feed;
- verify artifact filename, architecture, Python tag, and probed identity;
- extract AppImages and locate console and GUI executables; and
- launch FreeCAD with NodePhell's selected package composition through
  `--python-path` and `--module-path`.

## Install the plugin

A packaged installation exposes this entry point:

```toml
[project.entry-points."nodephell.adapters"]
freecad = "freecad:ADAPTER"
```

Install the distribution into the same Python environment that runs the
`nodephell` management command.

For checkout development or application bundling, expose the package as a
drop-in through NodePhell:

```console
nodephell plugin add /path/to/NodePhell/plugins/freecad
```

The application installer may copy that directory instead of linking it.
Verify discovery:

```console
nodephell host adapters
```

Expected output includes:

```text
freecad	FreeCAD
```

## Register and use FreeCAD

From a FreeCAD source project, NodePhell can find common build-tree locations,
including `build/*/bin/FreeCADCmd`:

```console
cd /path/to/FreeCAD
nodephell app add
FreeCAD
```

The guided command probes and registers the build, updates the project's exact
host requirement, synchronizes its lock and packages, and creates the bound
`~/.local/bin/FreeCAD` launcher. Pass `FreeCADCmd` explicitly if discovery finds
none or more than one. The launcher works outside the source directory and can
be used by a desktop icon.

A FreeCAD distribution that bundles this plugin can declare its project-local
copy in `pyproject.toml`:

```toml
[tool.nodephell.application]
adapter = "nodephell-plugins/freecad"
```

When its exact host requirement and lock are already present, the user needs
only `nodephell install`; that command also creates the `FreeCAD` launcher.

The lower-level equivalent remains available for development and diagnosis.

Register an existing command-line executable:

```console
nodephell host add /path/to/FreeCADCmd
nodephell host list
```

Use the reported FreeCAD version in the project definition:

```toml
[tool.nodephell.host]
kind = "freecad"
requires = "==1.1.3"
```

The version above is an example; match the installed build or use an
appropriate supported range. Then synchronize the project:

```console
nodephell sync
nodephell host resolve
```

Run a script through FreeCAD's console host or start the GUI:

```console
nodephell host run script.py
nodephell host gui
nodephell host gui -- model.FCStd
```

The project lock, selected stock Python, and FreeCAD embedded Python must have
compatible implementation, ABI, and platform identities. `host resolve` shows
the selection without starting FreeCAD.

## Package reuse

The probe reports FreeCAD package roots that contain standard Python
distribution metadata. NodePhell may reuse an exact locked distribution from
those roots when its `METADATA` and `RECORD` match. Reused files remain owned by
FreeCAD and are tracked read-only in NodePhell's generated composition.

During launch, NodePhell's selected composition takes priority through
FreeCAD's path arguments. The adapter redirects the generic Python user base
for that process while preserving FreeCAD's application directories and saved
configuration.

## Development

Use the source directory directly while editing:

```console
NODEPHELL_ADAPTER_PATH=/path/to/NodePhell/plugins/freecad/src \
  nodephell host adapters
```

Run the adapter and core host tests:

```console
cd /path/to/NodePhell
PYTHONPATH=src:plugins/freecad/src \
  /usr/bin/python3 -m unittest tests.test_adapters tests.test_host -v
```

See [Author an embedded-host adapter](../../docs/host-adapters.md) for the
human-oriented protocol guide and the
[AI adapter implementation brief](../../docs/adapter-authoring-ai.md) for the
normative implementation checklist.
