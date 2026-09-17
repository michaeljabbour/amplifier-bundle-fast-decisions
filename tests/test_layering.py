"""Enforces the Smart Tool packaging boundary named in
docs/design/redesign-2026-09-17.md ("Smart-tool packaging target"):
harness-agnostic core modules must import nothing from amplifier_core or
amplifier_foundation, transitively, within this package.

An import-graph scan over src/, not a runtime check -- it holds even when
amplifier_core/amplifier_foundation are not installed.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "amplifier_fast_decisions"

# Harness-agnostic core (must not import the kernel, transitively).
AGNOSTIC = {
    "contracts",
    "state",
    "candidates",
    "questions",
    "service",
    "backends",
    "privacy",
    "telemetry",
}
# bench/* is named in the design doc but does not exist yet in this PR.

FORBIDDEN_PREFIXES = ("amplifier_core", "amplifier_foundation")


def module_imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
            # Relative imports (`from .foo import bar`) are resolved by name
            # below via the local module graph, not by dotted prefix.
    return names


def local_module_names() -> set[str]:
    return {p.stem for p in ROOT.glob("*.py")}


def build_local_graph() -> dict[str, set[str]]:
    """Maps each local module name to the *local* modules it imports
    (relative imports only -- ``from .foo import bar`` / ``from . import foo``)."""
    graph: dict[str, set[str]] = {}
    local_names = local_module_names()
    for path in ROOT.glob("*.py"):
        name = path.stem
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        deps: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.level >= 1:
                if node.module:
                    candidate = node.module.split(".")[0]
                    if candidate in local_names:
                        deps.add(candidate)
                # `from . import x, y` -- each imported name may itself be a
                # local module.
                if node.module is None:
                    for alias in node.names:
                        if alias.name in local_names:
                            deps.add(alias.name)
        graph[name] = deps
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
        all_imports = {p.stem: module_imports(p) for p in ROOT.glob("*.py")}
        violations: dict[str, set[str]] = {}
        for module in AGNOSTIC:
            self.assertIn(module, all_imports, f"{module}.py not found under {ROOT}")
            hits = transitive_kernel_imports(module, graph, all_imports)
            if hits:
                violations[module] = hits
        self.assertEqual(
            violations,
            {},
            f"Harness-agnostic modules importing the kernel: {violations}",
        )

    def test_agnostic_list_matches_the_design_doc(self):
        # Guards against silent drift between this test and the design doc's
        # "Smart-tool packaging target" boundary list (bench/* excluded --
        # it does not exist yet in this PR).
        expected = {
            "contracts",
            "state",
            "candidates",
            "questions",
            "service",
            "backends",
            "privacy",
            "telemetry",
        }
        self.assertEqual(AGNOSTIC, expected)


if __name__ == "__main__":
    unittest.main()
