<!-- SPDX-License-Identifier: GPL-3.0-only -->

# Project compatibility evidence

This ledger records real Python projects exercised with NodePhell. Its purpose
is to show which workflows have evidence behind them, preserve the limitations
found during each run, and turn compatibility discoveries into regression
coverage.

An entry applies only to the path that was tested. It is not a guarantee that
every version, optional feature, platform, or application workflow works.

## Evidence levels

- **Development**: a real project exposed a compatibility gap and was used to
  validate the resulting implementation, but some reproduction details were
  not recorded.
- **Recorded**: the upstream revision, platform, Python, NodePhell revision,
  commands, selected options, and outcome are all present here.
- **Automated**: the recorded scenario also has a repeatable integration test
  or fixture in the repository.

Unit tests linked from an entry prove the NodePhell behavior that was retained;
they do not by themselves reproduce the complete upstream project run.

## Project summary

- **[MNE-Python](https://github.com/mne-tools/mne-python), 2026-10-09:**
  development evidence for PEP 621 optional dependencies; compatible with the
  exercised option-selection path.
- **[Frogmouth](https://github.com/Textualize/frogmouth), 2026-10-09:**
  development evidence for Poetry runtime dependencies and development groups;
  supported declarations translated into a NodePhell lock.

## MNE-Python

- **Upstream revision:** not recorded
- **Platform and Python:** not recorded
- **NodePhell revisions prompted by the run:** `9d45fe1`, `7101b97`
- **Workflow exercised:** project metadata inspection and selection of optional
  dependency features before generating and installing NodePhell's lock.
- **Result:** NodePhell now discovers standard `[project.optional-dependencies]`
  and dependency groups, presents them through `nodephell options`, persists
  the selected set in `pylock.toml`, and synchronizes only when the dependency
  selection changes.
- **Regression evidence:**
  [metadata tests](../tests/test_metadata.py),
  [option-selection tests](../tests/test_project_options.py), and
  [resolver tests](../tests/test_resolver.py).
- **Follow-up:** repeat the run with an exact MNE revision, record the selected
  features and commands, and exercise at least one import or project test under
  the locked runtime.

## Frogmouth

- **Upstream revision:** not recorded
- **Platform and Python:** not recorded
- **NodePhell revisions prompted by the run:** `392d200`, `cfc366f`
- **Workflow exercised:** reading Poetry-style runtime requirements and
  development groups from `pyproject.toml`, then resolving NodePhell's own
  exact package lock.
- **Result:** NodePhell translates supported Poetry exact, comparison, caret,
  tilde, wildcard, and unversioned constraints. Modern groups and the older
  `dev-dependencies` table appear in `nodephell options`, including group
  inclusion.
- **Intentional lock behavior:** NodePhell does not consume `poetry.lock`; it
  resolves and writes `pylock.toml` from supported project declarations.
- **Known limits:** custom Poetry sources, markers, platform-specific variants,
  Git/path/URL dependencies, multiple constraint tables, prerelease opt-in,
  and legacy Poetry optional extras remain unsupported.
- **Regression evidence:**
  [Poetry metadata tests](../tests/test_metadata.py) and
  [option-selection tests](../tests/test_project_options.py).
- **Follow-up:** repeat the run at a recorded Frogmouth revision and capture
  `sync`, launcher, and basic application smoke results.

## Add a project

Copy this record for each compatibility run:

```markdown
## Project name

- **Upstream repository and revision:** URL and commit or release
- **Test date:** YYYY-MM-DD
- **NodePhell revision:** commit
- **System:** operating system and architecture
- **Python requirement and selected runtime:** requirement and exact version
- **Metadata style:** PEP 621, Poetry, or another supported form
- **Selected options:** extras or dependency groups, or none
- **Commands:** exact preparation and smoke commands
- **Outcome:** passed, partial, or blocked, with the observed behavior
- **Changes prompted:** NodePhell commits, issues, or none
- **Known limits:** untested or unsupported paths
- **Evidence:** logs, tests, or fixtures retained in the repository
```

Prefer a small representative smoke test over a vague claim that the whole
project works. Preserve failures too: a blocked project is useful evidence when
the unsupported declaration or runtime behavior is named precisely.
