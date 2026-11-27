# SPDX-License-Identifier: GPL-3.0-only

"""Review dependencies inferred from source without importing project code."""

from __future__ import annotations

import ast
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
import shlex
import sys
import tokenize

from .errors import NodePhellError
from .initializer import (
    _ask_dependencies,
    _ask_dependency_version,
    _ask_project_name,
    _ask_project_version,
    _ask_python_requirement,
    _confirmed,
    _project_toml,
)
from .metadata import load_project_definition, normalize_name, parse_package_requirement


_IGNORED = {
    "__pycache__", "__pypackages__", "node_modules", "site-packages",
    "build", "dist", "checkpoints",
}
_DEVELOPMENT = {"test", "tests", "testing", "example", "examples", "docs"}
# These are suggestions for import names, never automatically installed.
_DISTRIBUTIONS = {
    "PIL": ("Pillow",),
    "yaml": ("PyYAML",),
    "cv2": ("opencv-python", "opencv-python-headless"),
    "sklearn": ("scikit-learn",),
    "bs4": ("beautifulsoup4",),
    "dateutil": ("python-dateutil",),
    "dotenv": ("python-dotenv",),
    "serial": ("pyserial",),
    "Crypto": ("pycryptodome",),
    "fitz": ("PyMuPDF",),
    "pymupdf": ("PyMuPDF",),
    "typing_extensions": ("typing-extensions",),
    "requests": ("requests",),
    "numpy": ("numpy",),
    "scipy": ("scipy",),
    "pandas": ("pandas",),
    "matplotlib": ("matplotlib",),
    "pytest": ("pytest",),
}
_APPLICATION_MODULES = {"FreeCAD", "FreeCADGui", "Part", "Sketcher", "pcbnew", "bpy"}


@dataclass(frozen=True)
class ImportUse:
    module: str
    file: Path
    line: int
    context: tuple[str, ...] = ()


@dataclass(frozen=True)
class ImportScan:
    root: Path
    files: int
    imports: tuple[ImportUse, ...]
    standard_library: tuple[str, ...]
    local_modules: tuple[str, ...]
    warnings: tuple[str, ...]


class _Imports(ast.NodeVisitor):
    def __init__(self, file: Path, context: tuple[str, ...]):
        self.file = file
        self.context = context
        self.imports: list[ImportUse] = []
        self.warnings: list[str] = []
        self.dynamic_functions = {"__import__"}

    def _add(self, name: str, node: ast.AST) -> None:
        self.imports.append(
            ImportUse(name.split(".")[0], self.file, node.lineno, self.context)
        )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._add(alias.name, node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level == 0 and node.module:
            self._add(node.module, node)
            if node.module == "importlib":
                self.dynamic_functions.update(
                    alias.asname or alias.name for alias in node.names
                    if alias.name == "import_module"
                )

    def _visit_body(self, nodes: list[ast.stmt], label: str) -> None:
        previous = self.context
        self.context = (*previous, label)
        try:
            for node in nodes:
                self.visit(node)
        finally:
            self.context = previous

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        condition = ast.unparse(node.test)
        self._visit_body(node.body, f"conditional: {condition[:100]}")
        self._visit_body(node.orelse, f"else: {condition[:100]}")

    def visit_Try(self, node: ast.Try) -> None:
        optional = any(
            handler.type is None or any(
                isinstance(item, ast.Name)
                and item.id in {"ImportError", "ModuleNotFoundError"}
                for item in ast.walk(handler.type)
            )
            for handler in node.handlers
        )
        if optional:
            self._visit_body(node.body, "optional: import-error fallback")
        else:
            for item in node.body:
                self.visit(item)
        for handler in node.handlers:
            self._visit_body(handler.body, "exception fallback")
        for item in (*node.orelse, *node.finalbody):
            self.visit(item)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.visit(node.args)
        if node.returns is not None:
            self.visit(node.returns)
        self._visit_body(node.body, f"inside function: {node.name}")

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_TryStar = visit_Try

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Name) and node.func.id in self.dynamic_functions
        ) or (
            isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
        ):
            self.warnings.append(
                f"{self.file}:{node.lineno}: dynamic import needs manual review"
            )
        self.generic_visit(node)


def _project_files(root: Path, exclude: tuple[str, ...]) -> tuple[Path, ...]:
    files: list[Path] = []

    def excluded(path: Path) -> bool:
        relative = path.relative_to(root).as_posix()
        return any(
            fnmatch.fnmatch(relative, pattern)
            or (path.is_dir() and fnmatch.fnmatch(relative + "/", pattern))
            for pattern in exclude
        )

    def failed(error: OSError) -> None:
        raise NodePhellError(f"cannot scan project directory: {error}") from error

    for directory, children, names in os.walk(root, followlinks=False, onerror=failed):
        parent = Path(directory)
        children[:] = sorted(
            name for name in children
            if not name.startswith(".") and name not in _IGNORED
            and not name.startswith("venv")
            and not (parent / name).is_symlink()
            and not (parent / name / "pyvenv.cfg").exists()
            and not excluded(parent / name)
        )
        files.extend(
            parent / name for name in sorted(names)
            if name.endswith(".py") and not (parent / name).is_symlink()
            and not excluded(parent / name)
        )
    return tuple(files)


def scan_imports(root: Path, exclude: tuple[str, ...] = ()) -> ImportScan:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise NodePhellError(f"project directory does not exist: {root}")
    files = _project_files(root, exclude)
    names: dict[Path, set[str]] = defaultdict(set)
    for file in files:
        names[file.parent].add(file.stem)
        parent = file.parent
        while parent != root:
            if parent.name.isidentifier():
                names[parent.parent].add(parent.name)
            parent = parent.parent
    if (root / "__init__.py").is_file():
        names[root].add(root.name)
    stdlib = set(sys.stdlib_module_names) | set(sys.builtin_module_names)
    external: list[ImportUse] = []
    standard: set[str] = set()
    local: set[str] = set()
    warnings: list[str] = []
    for file in files:
        relative = file.relative_to(root)
        development = (
            any(part in _DEVELOPMENT for part in relative.parts[:-1])
            or file.name.startswith("test_") or file.name.endswith("_test.py")
        )
        visitor = _Imports(relative, ("tests/examples/docs",) if development else ())
        try:
            with tokenize.open(file) as source:
                tree = ast.parse(source.read(), filename=str(relative))
        except (OSError, SyntaxError, UnicodeError, LookupError) as error:
            warnings.append(f"{relative}: could not scan ({error})")
            continue
        visitor.visit(tree)
        warnings.extend(visitor.warnings)
        supplied = names[root] | names[root / "src"] | names[file.parent]
        for use in visitor.imports:
            if use.module in supplied:
                local.add(use.module)
            elif use.module in stdlib:
                standard.add(use.module)
            else:
                external.append(use)
    return ImportScan(root, len(files), tuple(external), tuple(sorted(standard)),
                      tuple(sorted(local)), tuple(warnings))


def _requirements_files(root: Path) -> tuple[Path, ...]:
    candidates = (*root.glob("*requirements*.txt"), *root.glob("*requirements*.in"),
                  *(root / "requirements").glob("*.txt"),
                  *(root / "requirements").glob("*.in"))
    return tuple(sorted({
        p for p in candidates
        if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(root)
    }))


def _report(scan: ImportScan, say: Callable[[str], None]) -> dict[str, list[ImportUse]]:
    groups: dict[str, list[ImportUse]] = defaultdict(list)
    for use in scan.imports:
        groups[use.module].append(use)
    noun = "file" if scan.files == 1 else "files"
    say(f"Scanned {scan.files} Python {noun} without executing project code.")
    say(f"Filtered {len(scan.standard_library)} standard-library names and "
        f"{len(scan.local_modules)} local module names.")
    say(f"Standard-library filtering uses management Python {sys.version_info.major}."
        f"{sys.version_info.minor}; review differences for other target versions.")
    for module, uses in sorted(groups.items()):
        say(f"Import {module}:")
        for use in uses[:5]:
            context = "; ".join(use.context) or "runtime"
            say(f"  {use.file}:{use.line} ({context})")
        if len(uses) > 5:
            say(f"  ... and {len(uses) - 5} more occurrences")
    for warning in scan.warnings:
        say(f"Review: {warning}")
    say("Dynamic imports, plugins, native libraries, and undeclared extras may "
        "need dependencies that this scan cannot determine.")
    return groups


def discover_dependencies(
    start: Path | None = None,
    exclude: tuple[str, ...] = (),
    prompt: Callable[[str], str] | None = None,
    announce: Callable[[str], None] | None = None,
) -> Path | None:
    root = (Path.cwd() if start is None else start.expanduser()).resolve()
    if not root.is_dir():
        raise NodePhellError(f"project directory does not exist: {root}")
    say = print if announce is None else announce
    read = input if prompt is None else prompt

    def ask(message: str) -> str:
        try:
            return read(message)
        except (EOFError, KeyboardInterrupt) as error:
            raise NodePhellError("dependency discovery cancelled") from error

    path = root / "pyproject.toml"
    existing = path.exists() or path.is_symlink()
    requirements = _requirements_files(root)
    selected = None
    if requirements:
        say("Existing requirements files can be used directly instead of inferring imports:")
        for number, file in enumerate(requirements, 1):
            say(f"  {number}. {file.relative_to(root)}")
        if not existing:
            while True:
                value = ask("Use requirements file number, or Enter to scan imports: ").strip()
                if not value:
                    break
                if value.isdigit() and 1 <= int(value) <= len(requirements):
                    selected = requirements[int(value) - 1].relative_to(root)
                    break
                say("Choose a listed number, or press Enter to scan.")

    groups = {} if selected is not None else _report(scan_imports(root, exclude), say)
    if existing:
        definition = load_project_definition(root)
        declared = {normalize_name(item.name) for item in definition.requirements}
        say("Existing pyproject.toml is unchanged. Possible missing dependencies:")
        for module in sorted(groups):
            candidates = _DISTRIBUTIONS.get(module, (module,))
            if not any(normalize_name(name) in declared for name in candidates):
                say(f"  {module}: review {', '.join(candidates)}")
        say("Suggestions may already be covered by optional dependencies, groups, "
            "or application-provided modules. Review before editing the declaration.")
        return None

    name = _ask_project_name(ask, say, root.name)
    version = _ask_project_version(ask, say)
    requires = _ask_python_requirement(
        ask, say, f"{sys.version_info.major}.{sys.version_info.minor}"
    )
    dependencies = []
    seen = set()
    for module, uses in sorted(groups.items()):
        candidates = _DISTRIBUTIONS.get(module, (module,))
        review_only = module in _APPLICATION_MODULES or all(
            any(not context.startswith("inside function:") for context in use.context)
            for use in uses
        )
        if module in _APPLICATION_MODULES:
            say(f"{module} is commonly supplied by an application; skip unless needed separately.")
        elif module not in _DISTRIBUTIONS:
            say(f"{module}: same-name distribution is an unverified suggestion.")
        elif len(candidates) > 1:
            say(f"{module}: choose a distribution ({', '.join(candidates)}).")
        default = "-" if review_only or len(candidates) > 1 else candidates[0]
        while True:
            value = ask(f"Distribution for {module} [{default}; '-' skips]: ").strip() or default
            if value == "-":
                break
            try:
                base = parse_package_requirement(value)
                if base.specifiers or base.marker or base.url:
                    raise NodePhellError("enter a distribution name; specify its version next")
            except NodePhellError as error:
                say(f"Invalid dependency: {error}")
                continue
            normalized = normalize_name(base.name)
            if normalized not in seen:
                dependencies.append(_ask_dependency_version(ask, say, base))
                seen.add(normalized)
            break
    if selected is None:
        say("Add any dependencies the scan missed, then press Enter to finish.")
        dependencies = list(_ask_dependencies(ask, say, tuple(dependencies)))
    text = _project_toml(name, version, requires, tuple(dependencies))
    say("Proposed pyproject.toml:\n" + text)
    if selected is not None:
        say(f"Dependencies will come from {selected} at synchronization time.")
    if not _confirmed(ask("Write pyproject.toml? [Y/n]: ")):
        raise NodePhellError("dependency discovery cancelled")
    try:
        with path.open("x", encoding="utf-8") as file:
            file.write(text)
    except OSError as error:
        raise NodePhellError(f"cannot create {path}: {error}") from error
    say(f"Created {path}")
    command = "nodephell sync"
    if selected is not None:
        command += " --requirements " + shlex.quote(str(selected))
    say(f"From {root}, run: {command}")
    return path
