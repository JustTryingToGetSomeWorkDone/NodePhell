<!-- SPDX-License-Identifier: GPL-3.0-only -->

# AI implementation brief: NodePhell host adapter

Use this document as the task contract when implementing an adapter for an
existing embedded-Python application. Read the target application source and
documentation before coding. Confirm all executable names, probe syntax,
package-path controls, archive layouts, and release metadata from primary
evidence.

## Objective

Produce a separately distributable adapter plugin that lets NodePhell:

1. recognize and probe the application's command-line executable;
2. register its application and embedded-Python identity;
3. select it by host version, Python ABI, platform, and artifact identity;
4. expose NodePhell's selected package composition for one launch;
5. launch console scripts and an optional GUI correctly;
6. reuse verified application-owned Python distributions read-only; and
7. optionally acquire and verify an application artifact.

Do not add application-specific branches to NodePhell core. If the existing
protocol cannot represent a verified requirement, report the exact missing
generic capability before proposing a core change.

## Required source inspection

Read these files in the NodePhell repository:

- `src/nodephell/adapters/base.py`: authoritative protocol and records;
- `src/nodephell/adapters/__init__.py`: discovery and validation;
- `src/nodephell/host.py`: call order, matching, installation, and execution;
- `src/nodephell/metadata.py`: `HostRequirement` and `HostArtifact` validation;
- `plugins/freecad/src/freecad/__init__.py`: complete reference adapter;
- `tests/test_adapters.py` and `tests/test_host.py`: expected behavior; and
- `docs/host-adapters.md`: packaging and manual workflow.

Inspect the target application for:

- a command-line executable capable of running a Python script;
- a reliable in-process application version API;
- `sys.implementation.name`, full Python version, `SOABI`, and platform;
- required environment and shared-library paths;
- supported per-launch Python/module search-path arguments;
- GUI executable location;
- application-owned `site-packages` or `dist-packages` roots;
- official release API/feed, archive format, filename semantics, hashes; and
- a deterministic mapping from extracted root to command executable.

Do not guess these details from common conventions when the application can be
queried or its source inspected.

## Plugin shape

Choose a stable kind matching:

```text
^[a-z][a-z0-9_-]*$
```

Expose one object named `ADAPTER`. Its `kind` must equal the package entry-point
name or drop-in filename.

Packaged discovery:

```toml
[project.entry-points."nodephell.adapters"]
example = "example_nodephell:ADAPTER"
```

Drop-in discovery:

```text
~/.local/share/nodephell/adapters/example.py
~/.local/share/nodephell/adapters/example/__init__.py
```

NodePhell rejects duplicate providers for one kind. Do not implement fallback
or precedence between plugin copies.

## Exact protocol

Implement every attribute and method below. Use the types from NodePhell; do
not create parallel record classes.

```python
class HostAdapter(Protocol):
    kind: str
    display_name: str

    def accepts_executable(self, executable: Path) -> bool: ...
    def probe(self, executable: Path) -> EmbeddedHost: ...
    def resolve_artifact(
        self, requirement: HostRequirement, runtime: Runtime
    ) -> HostArtifact: ...
    def validate_artifact(
        self, artifact: HostArtifact, runtime: Runtime
    ) -> None: ...
    def validate_probed_artifact(
        self, host: EmbeddedHost, artifact: HostArtifact
    ) -> None: ...
    def extract(self, archive: Path, destination: Path) -> Path: ...
    def installed_executable(self, root: Path) -> Path: ...
    def gui_executable(self, host: EmbeddedHost) -> Path: ...
    def launch_arguments(self, packages: PackageSelection) -> tuple[str, ...]: ...
    def augment_environment(
        self, host: EmbeddedHost, environment: dict[str, str]
    ) -> dict[str, str]: ...
```

All methods are runtime-required. For an intentionally unsupported operation,
raise `NodePhellError` with the missing capability and user remedy. Do not leave
`NotImplementedError`, return placeholder records, or silently select defaults.

## Method constraints

### `accepts_executable`

- Keep it cheap and side-effect free.
- Use only strong recognition signals available from the path/name.
- Return `False` when uncertain; explicit `host add --kind KIND` remains
  available.

### `probe`

- Resolve the executable and require a regular file.
- Run the application without `shell=True`.
- Clear inherited `PYTHONPATH` and `PYTHONHOME` for the probe unless the
  application requires a documented value.
- Set a finite timeout and capture stdout/stderr.
- Execute a short script inside the embedded interpreter.
- Emit a uniquely prefixed JSON line and ignore unrelated output.
- Validate every JSON field and version before constructing records.
- Probe actual Python identity; never derive Python version or ABI from the app
  version or artifact filename.
- Return `EmbeddedHost(kind, app_version, executable, runtime, environment,
  artifact=None, package_roots)`.
- Set `runtime.executable` to the command used to run embedded Python.
- Include only real, existing package roots owned by the application.
- Convert expected failures into `NodePhellError` with path and detail.

### `resolve_artifact`

- Query an authoritative source over HTTPS.
- Filter by `requirement.requires`, runtime platform/architecture, and embedded
  Python compatibility.
- Require a SHA-256 digest and an unambiguous filename.
- Return one deterministic best candidate, normally the newest compatible
  stable version.
- Raise `NodePhellError` when no candidate exists; include requirement,
  platform, and Python compatibility detail.

### `validate_artifact`

- Re-parse application-specific filename or release metadata.
- Verify claims not covered by generic `HostArtifact` checks, especially
  architecture and embedded Python tag.
- Do not download or extract here.

### `extract`

- Treat the archive as untrusted input even after hash verification.
- Extract only under `destination`.
- Use argument arrays, finite timeouts, and checked return codes.
- Reject traversal, unexpected layout, missing root markers, or unsupported
  file types where the extraction mechanism does not already do so safely.
- Return the single application root NodePhell should commit.

### `installed_executable`

- Return a deterministic path below `root`.
- Do not search the machine or consult `PATH`.
- Core verifies the returned file before registration.

### `validate_probed_artifact`

- Compare probed app version, platform, architecture/Python tag, and any
  artifact-specific identity.
- Reject a valid archive that contains the wrong application build.

### `gui_executable`

- Derive the GUI from the registered command executable or recorded host
  layout.
- Require the resulting file to exist.
- Raise `NodePhellError` if GUI launch is unsupported or incomplete.

### `launch_arguments`

- Translate every `packages.paths` item into the application's documented
  per-launch package/module path arguments.
- Preserve package order.
- Return an immutable tuple of separate arguments.
- Do not quote for a shell and do not mutate application settings.

### `augment_environment`

- Start from the provided environment; it already contains NodePhell's runtime
  and package isolation.
- Add only application-required variables.
- Preserve unrelated variables.
- Return the dictionary used for launch.
- Do not write user configuration or application files.

## Core lifecycle to preserve

Existing host registration:

```text
host add -> adapter selection -> probe -> registry write
```

Artifact installation:

```text
resolve_artifact -> generic checks -> validate_artifact
-> core HTTPS download -> core SHA-256 verification
-> extract -> installed_executable -> probe
-> validate_probed_artifact -> atomic commit -> registry write
```

Project launch:

```text
load lock -> select stock runtime -> select ABI-compatible registered host
-> resolve managed/external packages -> launch_arguments
-> generic host environment -> augment_environment -> exec host
```

Compatibility requires equal Python implementation, ABI, and platform between
the selected project runtime and `host.runtime`. Do not weaken this check in an
adapter.

## Ownership and safety invariants

- Application-owned files and package roots are read-only inputs.
- Never install into, delete from, clean, rewrite, or chmod an external
  application tree during registration or launch.
- NodePhell-owned downloaded hosts are committed only by core.
- Never bypass core hash verification or fabricate a digest.
- Never use `shell=True` for paths or user arguments.
- Never select a plugin, host, artifact, or command by installation order when
  more than one valid provider exists.
- Never modify global `sys.path`, environment, or process state at plugin import
  time.
- Keep imports free of network access, probing, and application startup.
- Preserve NodePhell's generic user-site isolation.
- Keep application constants and release parsing inside the plugin.

## Required tests

Implement focused automated tests for:

1. discovery through the `nodephell.adapters` entry point or drop-in;
2. exact `kind`, `display_name`, and complete protocol validation;
3. executable recognition, including false positives;
4. successful probe parsing with unrelated application output;
5. malformed output, timeout, missing executable, and nonzero exit;
6. reported app version, Python version, ABI, platform, environment, and
   package roots;
7. host requirement and ABI compatibility selection;
8. launch arguments for zero, one, and multiple package paths;
9. environment augmentation without removing generic NodePhell values;
10. GUI path success and missing-GUI failure;
11. artifact candidate filtering and deterministic newest selection;
12. artifact filename/platform/Python validation;
13. extraction failure, incomplete layout, and installed executable mapping;
14. post-extraction identity mismatch; and
15. preservation of application-owned files and package roots.

Use mocks or local fixtures for network and archive tests. Do not make the test
suite depend on a live release server. Add an opt-in manual smoke procedure for
the real application.

## Manual acceptance sequence

```console
nodephell host adapters
nodephell host add --kind KIND /path/to/CommandExecutable
nodephell host list
nodephell lock /path/to/project
nodephell install /path/to/project
cd /path/to/project
nodephell host resolve
nodephell host run script.py
nodephell host gui
nodephell doctor
```

Confirm that `host resolve` reports the expected host, embedded Python ABI,
package roots, and provider for each package. Confirm console and GUI launches
see the locked packages and that the application's existing configuration and
package directories are unchanged.

## Completion output

When reporting completion, include:

- adapter kind and distribution/drop-in path;
- evidence source for probe and launch behavior;
- whether artifact acquisition is supported;
- probe identity fields and package-root policy;
- console and GUI launch mechanisms;
- automated tests added and their result;
- manual commands run and observed result; and
- any unsupported application versions, platforms, layouts, or capabilities.
