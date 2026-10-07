# NodePhell FreeCAD adapter

This package connects FreeCAD's embedded Python runtime to NodePhell. It is a
reference host plugin and is released independently from NodePhell core.

Install the package into the Python environment that runs `nodephell`. Its
`nodephell.adapters` entry point then provides the `freecad` host kind.

Application installers may instead place the `freecad` package directory at
`~/.local/share/nodephell/adapters/freecad` as a drop-in plugin.
