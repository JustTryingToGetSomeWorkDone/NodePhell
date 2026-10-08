<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Author an embedded-host adapter

This guide is for application developers and integrators connecting an
embedded-Python application to NodePhell. An adapter is a separately
distributable Python plugin. It teaches NodePhell how to inspect and launch one
kind of application while NodePhell supplies the runtime matching, package
selection, locking, and registry behavior.

For a compact implementation contract suitable for a coding agent, see the
[AI adapter implementation brief](adapter-authoring-ai.md). The FreeCAD plugin
under `plugins/freecad` is the
[reference implementation](../plugins/freecad/README.md).

## When an adapter fits

Build an adapter when the application:

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
- host requirements in `pyproject.toml` and `pylock.toml`;
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

## Create the plugin package

Choose a stable lowercase kind matching `[a-z][a-z0-9_-]*`. The kind is stored
in project locks and host registrations, so treat it as a public identifier.

A packaged plugin can use this layout:

```text
nodephell-example-adapter/
├── pyproject.toml
└── src/
    └── example_nodephell/
        └── __init__.py
```

Minimal packaging metadata:

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "nodephell-example-adapter"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["nodephell>=0.1.0"]

[project.entry-points."nodephell.adapters"]
example = "example_nodephell:ADAPTER"

[tool.setuptools]
package-dir = { "" = "src" }

[tool.setuptools.packages.find]
where = ["src"]
```

The entry-point name and `ADAPTER.kind` must be identical.

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
`example/__init__.py`, and that module must expose `ADAPTER`. For the package
layout above, use a directory whose child name matches the adapter kind or test
the installed entry point instead. Multiple development directories can be
listed in `NODEPHELL_ADAPTER_PATH` using the platform path separator (`:` on
Linux).

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

## Publish or bundle the adapter

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

Python packages publish through the `nodephell.adapters` entry-point group.
Install the package into the Python environment that runs the `nodephell`
management command.

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
