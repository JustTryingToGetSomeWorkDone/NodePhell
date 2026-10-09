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

- **[MNE-Python](https://github.com/mne-tools/mne-python), 2026-10-10:**
  recorded pass for base synchronization, editable installation, imports,
  package command execution, option discovery, and an empty option toggle.
- **[Frogmouth](https://github.com/Textualize/frogmouth), 2026-10-10:**
  recorded partial result. The unmodified project synchronizes on Python 3.15
  but its command fails in `httpcore`; a controlled Python 3.13 run passes.

## Test environment

- **NodePhell:** `5659449462eb317fa45345687506934640a01e94`
- **System:** Ubuntu 24.04, Linux x86_64
- **Management Python:** `/usr/bin/python3` 3.12.3
- **Source:** fresh clones of each GitHub default branch on 2026-10-10

## MNE-Python

- **Upstream revision:** `5ec89de232bd012240055ff2e26754c4842bf832`
- **Project version:** `1.14.0.dev85+g5ec89de23`
- **Metadata:** PEP 621, Hatch build backend, six optional features, and eight
  dependency groups
- **Python requirement:** `>=3.11`
- **Selected runtime:** CPython 3.15.0
- **Lock result:** 22 releases; editable project metadata and nine package
  commands installed

Commands and results:

```console
nodephell sync
nodephell run -c 'import mne, numpy, scipy'
mne --help
printf '1\na\n1\na\nq\n' | nodephell options
```

Synchronization, imports, and `mne --help` all returned status 0. The imports
reported MNE `1.14.0.dev85+g5ec89de23`, NumPy `2.5.3`, and SciPy `1.18.1`.
`nodephell options` listed all six extras and eight groups. The empty `data`
extra was enabled and disabled again; both changes updated only lock selection
metadata and did not resolve or install packages.

**Outcome: passed for the recorded path.** Package-heavy optional features and
the upstream test suite were not run.

## Frogmouth

- **Upstream revision:** `15c3e85a6e84b2e4a6845723acf12beb54c81eb2`
- **Project version:** `0.9.2`
- **Metadata:** Poetry runtime dependencies, one `dev` dependency group, and a
  Poetry build backend
- **Python requirement:** Poetry `^3.8`, translated to `>=3.8,<4.0`
- **Default selected runtime:** CPython 3.15.0
- **Lock result:** 16 releases; editable project metadata and five package
  commands installed

Default commands and results:

```console
nodephell sync
nodephell run -c 'import frogmouth'
frogmouth --help
printf 'q\n' | nodephell options
```

Synchronization, the top-level import, and option discovery returned status 0.
The option screen reported the Poetry `dev` group with four dependencies. The
actual `frogmouth --help` command returned status 1 while importing
`httpcore==0.17.3`: Python 3.15 rejects its attempt to assign `__module__` on a
`typing.Union` object.

For a controlled follow-up, only the local Poetry Python declaration was
changed from `^3.8` to `>=3.8,<3.14`. `nodephell sync` selected and downloaded
CPython 3.13.16, reused all 16 package releases, and prepared the editable
project again. The import and `frogmouth --help` then returned status 0. The
upstream declaration was restored afterward and the default 3.15 lock was
regenerated.

**Outcome: partial.** Poetry translation, locking, installation, editable
metadata, option discovery, and command generation work. The unmodified
project does not run on NodePhell's newest declared-compatible stable Python.
The controlled 3.13.16 result shows that bounding the interpreter restores the
application without changing its package selection.

NodePhell intentionally generates `pylock.toml`; it does not import the
project's existing `poetry.lock`.

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
