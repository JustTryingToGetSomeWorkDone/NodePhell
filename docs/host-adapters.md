<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Host adapters: using NodePhell with applications such as FreeCAD

A host adapter lets an application that has Python built into it use the
dependencies selected by NodePhell. FreeCAD is one example: its workbenches
and Python console run inside FreeCAD, so they need access to the right Python
libraries when FreeCAD starts.

The adapter is a small Python plugin that knows how that application works.
For FreeCAD, it finds the executable, checks which Python the build uses, and
passes NodePhell's selected package paths to FreeCAD when launching it.

## Why this is useful: a native FreeCAD build

Our FreeCAD test on Linux Mint 22.3 started with a practical problem: the build
needed a Python version and newer Python libraries that were difficult to
accommodate in the system Python setup. Changing shared packages risked
interfering with other software, and replacing the system interpreter was
not a convenient way to meet one application's requirements.

NodePhell let the build use an appropriate CPython installation and keep its
Python dependencies in the shared historical store. The FreeCAD adapter then
connected the native build to that locked package selection. FreeCAD could
run with the libraries it needed, while other projects kept their own
selections and the system Python installation remained intact.

That is the purpose of the adapter: making NodePhell's dependency selection
available **inside an application that runs its own Python interpreter**.
In this case, the result was a working, natively compiled FreeCAD on Mint,
without mixing its Python dependencies into the system's package directories.

FreeCAD's build configuration determines which Python it links to. The adapter
inspects that actual interpreter and checks that the selected packages match
it. Compiled Python packages must match the interpreter's binary interface
(ABI), which includes details such as the CPython version and platform.

## Use the existing FreeCAD adapter

If you want to use FreeCAD, the adapter is already included in the NodePhell
checkout. From that checkout, register it:

```console
nodephell plugin add ./plugins/freecad
nodephell host adapters
```

The second command should list `freecad`. Then, from your FreeCAD source
project, with its Python dependencies declared in `pyproject.toml`, run:

```console
nodephell app add
FreeCAD
```

`app add` looks for your build, checks its embedded Python, synchronizes the
project's dependencies, and creates a `FreeCAD` launcher bound to that project.
If it cannot identify the intended build, pass the path to its `FreeCADCmd`
executable. The resulting launcher also works outside the source directory.

The [FreeCAD adapter guide](../plugins/freecad/README.md) covers the complete
workflow, including console launches, GUI launches, and diagnostics.

## When do you need an adapter?

When you run a script with `python script.py`, NodePhell's Python launcher can
select the interpreter and dependencies directly. An application such as
FreeCAD starts its embedded interpreter itself. Selecting a different
`python` command in your shell therefore does not select FreeCAD's Python.
The adapter connects NodePhell to the application's own launch and scripting
interfaces.

Adapters can also reuse verified packages that an application already provides.
Some support downloading an application release. The native FreeCAD workflow
above uses an existing local build.

The rest of this guide is for people adding support for another application.
It explains the Python object an adapter must provide and how to test it.
The FreeCAD plugin is the reference implementation. For a compact contract
intended for coding agents, see the
[AI adapter implementation brief](adapter-authoring-ai.md).

## Writing an adapter for another application

An application is a good fit when it:

- embeds CPython and exposes a command-line executable that can run a script;
- can report its Python implementation, version, ABI, and platform;
- has a supported way to add package or module search paths for one launch;
- may have application-owned Python package directories worth reusing; and
- can be identified and launched without modifying NodePhell core.

The command-line executable is the anchor for registration, probing, script
execution, and locating an optional GUI executable.

## What NodePhell handles

NodePhell core owns these operations:

- adapter discovery and validation;
- host requirements in `pyproject.toml` and `nodephell.lock.toml`;
- host registration and selection;
- host/runtime ABI and platform matching;
- HTTPS download and SHA-256 verification of locked host artifacts;
- atomic commit into `~/.python/hosts`;
- exact package selection and composition;
- project references, cleanup protection, and diagnostics; and
- process replacement with the adapter's arguments and environment.

The adapter owns application knowledge:

- recognizing its executable;
- probing application and embedded-Python identity;
- reporting application-owned package roots;
- selecting and validating downloadable application artifacts, if supported;
- extracting an artifact and finding installed executables;
- translating package paths into application launch arguments; and
- adding application-specific environment variables.

## Create the plugin source directory

Choose a stable lowercase kind matching `[a-z][a-z0-9_-]*`. The kind is stored
in project locks and host registrations, so treat it as a public identifier.

A source plugin can use this layout:

```text
nodephell-example-adapter/
└── src/
    └── example/
        └── __init__.py
```

Put the adapter implementation in `src/example/__init__.py` and expose an
object named `ADAPTER`. The module directory name and `ADAPTER.kind` must both
be `example`. Register the source plugin with:

```console
nodephell plugin add /path/to/nodephell-example-adapter
```

NodePhell links the source into its user adapter directory. Keep that source
directory available while the adapter is registered.

## Implement the adapter object

The protocol and shared records live in `nodephell.adapters.base`. Every method
is required, including acquisition methods for adapters that support only
existing installations. Unsupported operations should raise `NodePhellError`
with a useful remedy.

```python
from pathlib import Path

from nodephell.adapters.base import EmbeddedHost
from nodephell.errors import NodePhellError
from nodephell.metadata import HostArtifact, HostRequirement
from nodephell.runtime import Runtime
from nodephell.store import PackageSelection


class ExampleAdapter:
    kind = "example"
    display_name = "Example Application"
    executable_names = ("ExampleCmd", "examplecmd")
    launcher_name = "Example"
    project_search_patterns = (
        "build/*/bin/ExampleCmd",
        "bin/ExampleCmd",
    )
    launch_mode = "gui"

    def accepts_executable(self, executable: Path) -> bool:
        return executable.name in self.executable_names

    def probe(self, executable: Path) -> EmbeddedHost:
        # Run the application probe, validate its output, and build both
        # the application identity and embedded Runtime record here.
        raise NodePhellError("implement the application probe")

    def resolve_artifact(
        self,
        requirement: HostRequirement,
        runtime: Runtime,
    ) -> HostArtifact:
        raise NodePhellError("this adapter requires an existing installation")

    def validate_artifact(
        self,
        artifact: HostArtifact,
        runtime: Runtime,
    ) -> None:
        raise NodePhellError("this adapter does not provide downloadable artifacts")

    def validate_probed_artifact(
        self,
        host: EmbeddedHost,
        artifact: HostArtifact,
    ) -> None:
        raise NodePhellError("this adapter does not provide downloadable artifacts")

    def extract(self, archive: Path, destination: Path) -> Path:
        raise NodePhellError("this adapter does not extract artifacts")

    def installed_executable(self, root: Path) -> Path:
        raise NodePhellError("this adapter does not manage installations")

    def gui_executable(self, host: EmbeddedHost) -> Path:
        raise NodePhellError("this application has no graphical executable")

    def launch_arguments(self, packages: PackageSelection) -> tuple[str, ...]:
        return tuple(
            argument
            for path in packages.paths
            for argument in ("--python-path", str(path))
        )

    def augment_environment(
        self,
        host: EmbeddedHost,
        environment: dict[str, str],
    ) -> dict[str, str]:
        return environment


ADAPTER = ExampleAdapter()
```

Replace the placeholder methods with application behavior. Use `NodePhellError`
for expected user-facing failures.

## Build a reliable probe

`probe()` is the most important method. It receives a user-supplied or
NodePhell-installed command-line executable and returns an `EmbeddedHost`.

A reliable probe should:

1. resolve and verify the executable path;
2. invoke the application with a short Python script using `subprocess.run`;
3. set a finite timeout and capture output;
4. print one uniquely prefixed JSON record from inside the embedded Python;
5. parse only that marked record, since applications may print other output;
6. validate every field before constructing records; and
7. report launch failures as `NodePhellError` with the executable and detail.

The returned host contains:

- `kind`: exactly the adapter kind;
- `version`: the application version used by host requirements;
- `executable`: the resolved command-line executable;
- `runtime`: the actual embedded CPython implementation, full version, ABI,
  platform, executable, and required library paths;
- `environment`: stable variables required whenever the host starts; and
- `package_roots`: existing application-owned directories containing standard
  installed Python distributions.

Probe the interpreter itself. Do not infer its ABI or Python version from the
application version, filename, or release notes.

A typical in-application probe payload looks like this:

```python
import json
import platform
import sys
import sysconfig

import example_api

print("__NODEPHELL_EXAMPLE__" + json.dumps({
    "host_version": example_api.version(),
    "implementation": sys.implementation.name,
    "python_version": platform.python_version(),
    "abi": sysconfig.get_config_var("SOABI") or "",
    "platform": sysconfig.get_platform(),
    "package_roots": example_api.python_package_roots(),
}))
```

After validating that JSON, construct the records from the observed values:

```python
runtime = Runtime(
    implementation=details["implementation"].lower(),
    version=details["python_version"],
    executable=executable,
    abi=details["abi"],
    platform=details["platform"],
    library_paths=required_library_paths,
)
return EmbeddedHost(
    kind=self.kind,
    version=details["host_version"],
    executable=executable,
    runtime=runtime,
    environment=tuple(sorted(required_environment.items())),
    package_roots=tuple(validated_package_roots),
)
```

The target application determines how the payload is supplied: a temporary
script, a command option, or another documented scripting interface. Keep the
probe self-contained and delete temporary files after the subprocess exits.

Package roots are read-only providers. NodePhell accepts a release from them
only when exact `METADATA` and `RECORD` information matches the lock. It tracks
external file identity in the generated composition and does not clean those
directories.

## Add launch behavior

`launch_arguments()` receives NodePhell's selected `PackageSelection`. Translate
each `packages.paths` entry into the application's supported path option. Some
embedded interpreters ignore `PYTHONPATH`, so prefer the application's native
command-line mechanism when one exists.

`augment_environment()` receives the environment already prepared with runtime
library paths, user-site isolation, and the selected package view. Add only
variables required by the application and return the resulting dictionary.

`gui_executable()` maps the registered command-line host to its graphical
counterpart. Verify the result is a file. If the application has no GUI entry
point, raise a clear `NodePhellError`; `host run` can still work.

## Support downloadable artifacts

Artifact acquisition is optional for an integration but all protocol methods
must exist. To support it:

1. `resolve_artifact()` queries an authoritative release source and returns one
   `HostArtifact` satisfying the host version requirement, runtime platform,
   architecture, and embedded Python line.
2. `validate_artifact()` checks application-specific filename and compatibility
   rules. Core has already checked kind, platform, host version requirement,
   HTTPS URL shape, and SHA-256 format.
3. `extract()` unpacks the verified archive into the supplied temporary
   destination and returns the application root that should be committed.
4. `installed_executable()` returns the command-line executable relative to an
   extracted or committed application root.
5. `validate_probed_artifact()` compares the probed application and Python
   identity with artifact-specific claims after extraction.

NodePhell performs the download, verifies SHA-256 before extraction, commits
the returned root atomically, and registers the resulting host.

## Test as a drop-in

During development, point NodePhell at the directory containing the adapter
module or package:

```console
export NODEPHELL_ADAPTER_PATH=/work/nodephell-example-adapter/src
nodephell host adapters
nodephell host add --kind example /path/to/ExampleCmd
nodephell host list
```

The development directory must contain either `example.py` or
`example/__init__.py`, and that module must expose `ADAPTER`. The source layout
above already matches the `example` adapter kind. Multiple development
directories can be listed in `NODEPHELL_ADAPTER_PATH` using the platform path
separator (`:` on Linux).

Create a project declaration using the version reported by `host list`:

```toml
[tool.nodephell.host]
kind = "example"
requires = "==2.4.1"
```

Then exercise the complete workflow:

```console
nodephell sync
nodephell host resolve
nodephell host run script.py
nodephell host gui
nodephell doctor
```

`host resolve` is the best first diagnostic: it selects the runtime, host, and
packages without starting the application.

## Share or bundle the adapter

Share the adapter's source directory with its setup instructions. Someone who
clones it can register it with `nodephell plugin add /path/to/adapter`.

An application distribution can keep its adapter inside the project and
declare that relative path in `pyproject.toml`:

```toml
[tool.nodephell.application]
adapter = "nodephell-plugins/example"
# executable = "build/release/bin/ExampleCmd" # only if discovery is ambiguous
```

With a matching host requirement and lock, `nodephell install` validates the
plugin, registers the application, supplies its packages, and creates its
launcher. The adapter path may not leave the project.

Application installers may instead place one of these drop-ins under the user
data directory:

```text
~/.local/share/nodephell/adapters/example.py
~/.local/share/nodephell/adapters/example/__init__.py
```

`XDG_DATA_HOME` replaces `~/.local/share` when set. Multiple providers for the
same kind are an error, including one entry point plus one drop-in. This makes
adapter selection independent of installation order.

## Validation checklist

Before release, verify:

- `nodephell host adapters` loads exactly one provider for the kind;
- executable inference and explicit `--kind` both behave as intended;
- malformed or noisy probe output fails clearly;
- the probe reports actual application, Python, ABI, and platform identity;
- incompatible ABI and platform combinations are rejected;
- package paths take effect for both console and GUI launch modes;
- application-owned package roots remain unchanged;
- GUI absence or layout errors produce actionable messages;
- downloads use authoritative HTTPS URLs and verified SHA-256 values;
- extraction rejects incomplete or mismatched artifacts;
- paths and arguments containing spaces work without shell parsing; and
- automated tests cover discovery, probe parsing, launch arguments,
  environment changes, artifact validation, and failure cases.
