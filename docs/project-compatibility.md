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
- **[Flask](https://github.com/pallets/flask), 2026-10-10:** recorded pass for
  base synchronization, a Flit editable installation, imports, CLI execution,
  an in-process HTTP request, troubleshooting, and an optional dependency cycle.
- **[Black](https://github.com/psf/black), 2026-10-10:** recorded pass for
  marker-aware synchronization, dynamic Hatch metadata, formatter execution,
  troubleshooting, and a platform-marked optional dependency cycle.
- **[Pillow](https://github.com/python-pillow/Pillow), 2026-10-10:** recorded
  pass for a native editable build, PNG and JPEG encode-decode, managed
  compiler fallback, project reuse, and optional-feature discovery.
- **[ir_datasets](https://github.com/allenai/ir_datasets), 2026-10-10:**
  recorded pass for backend-supplied dynamic dependencies, native dependency
  builds, editable installation, imports, CLI execution, and option discovery.
- **[orjson](https://github.com/ijl/orjson), 2026-10-10:** recorded pass for a
  Maturin/Rust native editable build on CPython 3.15, serialization and
  deserialization, and project reuse.

## Test environment

- **NodePhell for MNE-Python and Frogmouth:**
  `5659449462eb317fa45345687506934640a01e94`
- **NodePhell for Flask:** `8245d158ef8549b222619a2e277b57a113ce54ce`
- **NodePhell for Black:** `3d3057ec3725382562a76ba4f27e3734a80971f0`
- **NodePhell for Pillow:** `7a5e57586833ed5e0e828c2a028139edf0df472c`
- **NodePhell for ir_datasets:** `993df616abea9821dc6e5c529480b7a587596350`
- **NodePhell for orjson:** `da6ccdcac73e5c0b2ad7096611bba1a273fe36e9`
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

NodePhell intentionally generates its own project lock; it does not import the
project's existing `poetry.lock`.

## Flask

- **Upstream revision:** `d086db856be187255b8ec61ef409357393020f32`
- **Project version:** `3.2.0.dev`, installed as `3.2.0.dev0`
- **Metadata:** PEP 621, Flit build backend, two optional features, seven
  dependency groups, and one project command
- **Python requirement:** `>=3.11`
- **Selected runtime:** CPython 3.15.0
- **Lock result:** six releases; four newly installed and two reused; editable
  project metadata and the `flask` command installed

Commands and results:

```console
nodephell sync
nodephell run -c \
  'import flask, blinker, click, itsdangerous, jinja2, markupsafe, werkzeug'
flask --help
nodephell run -c \
  "from flask import Flask; app=Flask(__name__); app.add_url_rule('/', 'index', lambda: {'status': 'ok'}); response=app.test_client().get('/'); assert response.status_code == 200; assert response.json == {'status': 'ok'}"
printf '\n' | nodephell troubleshoot
printf 'q\n' | nodephell options
```

Synchronization selected CPython 3.15.0 and locked Blinker 1.9.0, Click 8.5.0,
ItsDangerous 2.2.0, Jinja2 3.1.6, MarkupSafe 3.0.4, and Werkzeug 3.1.9. The
MarkupSafe release was a CPython 3.15 manylinux wheel, providing compiled-wheel
coverage. Imports, `flask --help`, and the in-process test-client request all
returned status 0; the request returned status 200 and `{"status": "ok"}`.

The interactive troubleshooter inferred `flask --help` from `[project.scripts]`
and correctly reported that no runtime fallback was needed. `nodephell options`
listed both extras and all seven groups. The `async` extra installed and exposed
`asgiref==3.12.1`; disabling it removed the selection from the lock and safely
left the now-unused shared release in the store after cleanup was declined.

**Outcome: passed for the recorded path.** The `gha-update` dependency group
contains a Python marker and was listed but not selected during this run. The
real-project option cycle exposed and prompted a correction to singular cleanup
text; the complete message now reads `1 release is no longer selected and
remains in the shared store`.

## Black

- **Upstream revision:** `c9b1148b5b8799758756cbec7c0d1ac187d37f1a`
- **Project version:** `26.10.1.dev18+gc9b1148b5`
- **Metadata:** PEP 621, Hatch with dynamic VCS versioning, four optional
  features, fourteen dependency groups, and two project commands
- **Python requirement:** `>=3.10`
- **Selected runtime:** CPython 3.15.0
- **Base lock result:** six releases; three newly installed and three reused;
  editable project metadata plus the `black` and `blackd` commands installed

Commands and results:

```console
nodephell sync
nodephell run -c \
  'import black, click, mypy_extensions, packaging, pathspec, platformdirs, pytokens'
black --version
printf 'value={"answer":42}\n' | black - --quiet
printf '1\n' | nodephell troubleshoot
printf 'q\n' | nodephell options
```

The untouched project initially exposed NodePhell's lack of standard dependency
markers through Black's Python-version-conditional `tomli` and
`typing-extensions` requirements. Commit `3d3057e` added marker preservation and
delegated evaluation to stock pip under the selected runtime. Repeating the run
at that commit produced a six-package marker-free lock: both requirements were
correctly omitted on Python 3.15. Imports and formatter commands returned status
0, and formatting stdin changed `value={"answer":42}` to
`value = {"answer": 42}`.

The interactive troubleshooter presented both project commands and successfully
ran the selected `black --help`. `nodephell options` listed all four extras and
fourteen groups. Enabling `uvloop` evaluated both platform markers: Linux
selected and imported `uvloop==0.23.0`, while Windows-only `winloop` was absent
from the lock. Disabling the extra returned to the six-package base lock and
left the safely unused shared release in the store after cleanup was declined.

**Outcome: passed for the recorded path.** Standard marker support is retained
by focused metadata and resolver tests. Black's direct-URL `diff-shades` group,
the `blackd` optional dependency path, and the upstream test suite were not run.

## Pillow

- **Upstream revision:** `d3470c327840f4c216a1610f30e7091dfd0b97c0`
- **Project version:** `13.0.0.dev0`
- **Metadata:** PEP 621 with dynamic versioning, a custom in-tree build backend,
  and six optional features
- **Python requirement:** `>=3.11`
- **Selected runtime:** CPython 3.15.0
- **Base lock result:** zero package releases; native editable project metadata
  installed

The first untouched synchronization reached Pillow's native build but failed
because the managed python-build-standalone interpreter recorded `clang` and
`llvm-ar`, neither of which existed on this host. Commit `7a5e575` made source
package and editable builds preserve explicit tool settings while replacing
unavailable recorded defaults with host `CC`, `CXX`, and `AR` tools. The next
build used `/usr/bin/cc` and `/usr/bin/ar` and proceeded to Pillow's external
JPEG development-header requirement.

Ubuntu's `libjpeg-turbo8` runtime was installed, but its development package
was not and privileged installation was unavailable. For this run,
`libjpeg-turbo8-dev` 2.1.5 was unpacked under
`~/.local/nodephell-build-deps/jpeg`; its include and library directories were
provided through `CFLAGS` and `LDFLAGS`. This was an operating-system build
prerequisite, not a NodePhell package or project modification.

Commands and results:

```console
CFLAGS='-I/home/john/.local/nodephell-build-deps/jpeg/usr/include -I/home/john/.local/nodephell-build-deps/jpeg/usr/include/x86_64-linux-gnu' \
LDFLAGS='-L/home/john/.local/nodephell-build-deps/jpeg/usr/lib/x86_64-linux-gnu' \
  nodephell sync
nodephell run -c \
  "from io import BytesIO; import PIL, PIL._imaging; from PIL import Image, features; image=Image.new('RGB',(3,2),(12,34,56)); png=BytesIO(); image.save(png,'PNG'); png.seek(0); decoded=Image.open(png); decoded.load(); assert decoded.format=='PNG' and decoded.size==(3,2) and decoded.getpixel((1,1))==(12,34,56); jpeg=BytesIO(); image.save(jpeg,'JPEG'); jpeg.seek(0); decoded_jpeg=Image.open(jpeg); decoded_jpeg.load(); assert decoded_jpeg.format=='JPEG' and decoded_jpeg.size==(3,2); assert features.check('zlib') and features.check('jpg')"
nodephell sync
printf 'q\n' | nodephell options
```

The native extension loaded from
`src/PIL/_imaging.cpython-315-x86_64-linux-gnu.so`. PNG and JPEG in-memory
round trips returned status 0. The second synchronization used no compiler or
library flags and reused the prepared editable project. Option discovery listed
all six extras: `docs`, `fpx`, `mic`, `test-arrow`, `tests`, and `xmp`.

**Outcome: passed for the recorded path.** The run proves NodePhell can prepare
and reuse a substantial native editable project when its operating-system
development prerequisites are available. Optional codecs beyond JPEG and zlib,
all optional dependency selections, and the upstream test suite were not run.

## ir_datasets

- **Upstream revision:** `76d107e3c1f9acf05875d263fcb206f94f7a356b`
- **Project version:** `0.5.11`
- **Metadata:** PEP 621 with setuptools-supplied dynamic dependencies, ten
  optional features, and one project command
- **Python requirement:** `>=3.8`
- **Selected runtime:** CPython 3.15.0
- **Lock result:** ten releases; editable project metadata and the
  `ir_datasets` command installed

The untouched project declares `dynamic = ["version", "dependencies"]` and
loads its dependencies from `requirements.txt` through setuptools. The first
synchronization showed that NodePhell had treated the dependency list as empty.
Commit `993df61` resolves the project root through its build backend and omits
the root editable from the resulting package lock. Dynamic dependency locks are
refreshed on every `sync` because a backend may obtain their metadata from
arbitrary files or code.

Resolution then reached the native `lxml` build, which reported missing libxml2
and libxslt development packages. NodePhell identified these as external system
prerequisites and gave the Debian or Ubuntu command
`sudo apt install libxml2-dev libxslt1-dev`. For this unprivileged test, those
packages and their development dependencies were unpacked under
`~/.local/nodephell-build-deps/xml` and exposed with ordinary compiler,
linker, executable, and pkg-config environment variables. They were not added
to NodePhell's store or installed by NodePhell.

Commands and results:

```console
PATH="$HOME/.local/nodephell-build-deps/xml/usr/bin:$PATH" \
CFLAGS="-I$HOME/.local/nodephell-build-deps/xml/usr/include -I$HOME/.local/nodephell-build-deps/xml/usr/include/libxml2 -I$HOME/.local/nodephell-build-deps/xml/usr/include/x86_64-linux-gnu" \
LDFLAGS="-L$HOME/.local/nodephell-build-deps/xml/usr/lib/x86_64-linux-gnu" \
PKG_CONFIG_PATH="$HOME/.local/nodephell-build-deps/xml/usr/lib/x86_64-linux-gnu/pkgconfig" \
  nodephell sync
nodephell run -c \
  "import ir_datasets, lxml, lz4, numpy, requests, tqdm, yaml; from lxml import etree; root=etree.fromstring(b'<root><item>ok</item></root>'); assert root.findtext('item')=='ok'; keys=sorted(ir_datasets.registry._registered); assert keys; dataset=ir_datasets.load(keys[0]); print(ir_datasets.__version__, len(keys), keys[0], type(dataset).__name__)"
ir_datasets --help
nodephell options
```

The lock contains Certifi 2026.7.22, Charset-Normalizer 3.5.2, IDNA 3.20,
lxml 5.4.0, lz4 4.4.5, NumPy 2.5.3, PyYAML 6.0.3, Requests 2.34.2, tqdm
4.70.1, and urllib3 2.8.0. The smoke test imported every direct dependency,
parsed XML through the native lxml extension, found 769 registered datasets,
and loaded the first registry entry without downloading dataset content. The
project command returned its help successfully. Option discovery listed all
ten extras. A second synchronization refreshed backend metadata and reused all
exact package releases and the prepared editable project.

**Outcome: passed for the recorded path.** The run validates dynamic dependency
resolution and native package building when external headers are available.
No optional feature was selected, no dataset content was downloaded, and the
upstream test suite was not run.

## orjson

- **Upstream revision:** `bd00937c5c46ab20eb5d7fe1cfc034b906c4578f`
- **Project version:** `3.13.0`
- **Metadata:** PEP 621, Maturin build backend, and no package dependencies
- **Python requirement:** `>=3.10`
- **Selected runtime:** CPython 3.15.0
- **Lock result:** zero package releases; native editable project metadata
  installed

The host initially had no `rustc` or `cargo` on `PATH`. During the untouched
editable build, Maturin's build environment bootstrapped Rust 1.99.0 through
its `puccinialin` cache under `~/.cache`. That 647 MB toolchain is owned by the
external build backend, not NodePhell's runtime or package store. The resulting
extension was built at
`pysrc/orjson/orjson.cpython-315-x86_64-linux-gnu.so`.

Commands and results:

```console
nodephell sync
nodephell run -c \
  "import dataclasses, datetime, orjson; Record=dataclasses.make_dataclass('Record',[('value',int),('when',datetime.datetime)]); record=Record(42,datetime.datetime(2026,10,10,tzinfo=datetime.timezone.utc)); encoded=orjson.dumps(record); decoded=orjson.loads(encoded); assert decoded=={'value':42,'when':'2026-10-10T00:00:00+00:00'}; print(orjson.__version__, encoded.decode())"
nodephell sync
```

The first synchronization built and prepared `orjson==3.13.0`. The smoke test
returned status 0, reported version 3.13.0, and round-tripped the dataclass to
`{"value":42,"when":"2026-10-10T00:00:00+00:00"}`. The second synchronization
reported that the lock already matched, reused the empty package composition,
and reused the prepared editable project without rebuilding it.

**Outcome: passed for the recorded path.** No NodePhell change was required.
The upstream test suite, performance benchmarks, packaging commands, and
non-Linux targets were not run.

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
