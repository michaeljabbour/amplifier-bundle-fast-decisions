"""Enforces the Smart Tool packaging boundary named in
docs/design/redesign-2026-09-17.md ("Smart-tool packaging target"):
harness-agnostic core modules must import nothing from amplifier_core or
amplifier_foundation, transitively, within this package.

An import-graph scan over src/, not a runtime check -- it holds even when
amplifier_core/amplifier_foundation are not installed.

``bench/`` is a subpackage (PR D): its modules are included in the scanned
set via a recursive walk, and relative imports are resolved with full
Python package semantics (level-1 imports resolve within the module's own
package; level-2+ walk up one package per extra dot), not the flat
same-directory assumption that was sufficient before bench/ existed.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "amplifier_fast_decisions"

# Harness-agnostic core (must not import the kernel, transitively). Dotted
# names are relative to ROOT; "bench" is the bench/__init__.py package
# itself, "bench.metrics" etc. are its submodules.
AGNOSTIC = {
    "contracts",
    "operations",
    "state",
    "candidates",
    "questions",
    "service",
    "backends",
    "local_backend",
    "privacy",
    "telemetry",
    "observatory",
    "bench",
    "bench.metrics",
    "bench.replay",
    "bench.suite",
    "bench.report",
}

FORBIDDEN_PREFIXES = ("amplifier_core", "amplifier_foundation")


def _dotted_key(path: Path) -> str:
    """``ROOT/contracts.py`` -> ``"contracts"``; ``ROOT/bench/metrics.py`` ->
    ``"bench.metrics"``; ``ROOT/bench/__init__.py`` -> ``"bench"``."""
    relative = path.relative_to(ROOT).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _own_package(path: Path, key: str) -> str:
    """The dotted package a module's own relative imports are resolved
    against -- itself, for an ``__init__.py``; its parent otherwise."""
    if path.name == "__init__.py":
        return key
    return key.rsplit(".", 1)[0] if "." in key else ""


def all_module_paths() -> list[Path]:
    return [p for p in ROOT.rglob("*.py") if "__pycache__" not in p.parts]


def module_imports(path: Path) -> set[str]:
    """Absolute (non-relative) import targets only; relative imports are
    resolved separately via the local package graph below."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def local_module_names() -> set[str]:
    return {_dotted_key(p) for p in all_module_paths()}


def _resolve_relative(
    node: ast.ImportFrom, own_package: str, local_names: set[str]
) -> set[str]:
    """Resolve one ``from .foo import bar`` / ``from . import foo`` node
    (``node.level >= 1``) against the *dotted* package it is relative to,
    following ordinary Python relative-import semantics: level 1 is the
    module's own package, level 2 its parent, etc."""
    parts = own_package.split(".") if own_package else []
    drop = node.level - 1
    base_parts = parts[: len(parts) - drop] if drop <= len(parts) else []
    base = ".".join(base_parts)
    targets: set[str] = set()
    if node.module:
        candidate = f"{base}.{node.module}" if base else node.module
        if candidate in local_names:
            targets.add(candidate)
    else:
        for alias in node.names:
            candidate = f"{base}.{alias.name}" if base else alias.name
            if candidate in local_names:
                targets.add(candidate)
    return targets


def build_local_graph() -> dict[str, set[str]]:
    """Maps each local module's dotted key to the *local* dotted module
    keys it imports via relative imports."""
    local_names = local_module_names()
    graph: dict[str, set[str]] = {}
    for path in all_module_paths():
        key = _dotted_key(path)
        own_package = _own_package(path, key)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.level >= 1:
                deps |= _resolve_relative(node, own_package, local_names)
        graph[key] = deps
    return graph


def transitive_kernel_imports(
    module: str,
    graph: dict[str, set[str]],
    all_imports: dict[str, set[str]],
    seen: set[str] | None = None,
) -> set[str]:
    seen = seen or set()
    if module in seen:
        return set()
    seen.add(module)
    direct = {
        name
        for name in all_imports.get(module, set())
        if any(
            name == prefix or name.startswith(prefix + ".")
            for prefix in FORBIDDEN_PREFIXES
        )
    }
    for dep in graph.get(module, set()):
        direct |= transitive_kernel_imports(dep, graph, all_imports, seen)
    return direct


class LayeringTests(unittest.TestCase):
    def test_agnostic_core_never_imports_the_kernel_transitively(self):
        graph = build_local_graph()
        all_imports = {_dotted_key(p): module_imports(p) for p in all_module_paths()}
        violations: dict[str, set[str]] = {}
        for module in AGNOSTIC:
            self.assertIn(module, all_imports, f"{module} not found under {ROOT}")
            hits = transitive_kernel_imports(module, graph, all_imports)
            if hits:
                violations[module] = hits
        self.assertEqual(
            violations,
            {},
            f"Harness-agnostic modules importing the kernel: {violations}",
        )

    def test_agnostic_list_matches_the_design_doc(self):
        # Guards against silent drift between this test and the design
        # doc's "Smart-tool packaging target" boundary list.
        expected = {
            "contracts",
    "operations",
            "state",
            "candidates",
            "questions",
            "service",
            "backends",
            "local_backend",
            "privacy",
            "telemetry",
            "observatory",
            "bench",
            "bench.metrics",
            "bench.replay",
            "bench.suite",
            "bench.report",
        }
        self.assertEqual(AGNOSTIC, expected)

    def test_bench_modules_are_scanned(self):
        # A regression guard for the scan itself: bench/*.py must actually
        # appear in the local module graph, not silently be skipped by a
        # non-recursive glob.
        found = local_module_names()
        for name in (
            "bench",
            "bench.metrics",
            "bench.replay",
            "bench.suite",
            "bench.report",
        ):
            self.assertIn(name, found)


if __name__ == "__main__":
    unittest.main()
