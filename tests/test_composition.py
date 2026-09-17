"""Bundle-composition checks.

Two independent concerns live here:

1. ``YamlSourceTests`` parses bundle.md / behaviors / bundles YAML directly
   (no amplifier_foundation needed) and checks every module ``source:``
   points at the supported ``git+https://.../amplifier-bundle-fast-decisions@main#subdirectory=modules/<name>``
   form, with a matching ``modules/<name>/pyproject.toml`` declaring the
   right entry point. This always runs.

2. ``BundleLoadTests`` actually loads the bundles through
   amplifier_foundation.load_bundle() and inspects the compiled mount plan.
   It is skipped whenever amplifier_foundation is not installed (the
   offline CI lane). It requires network access to resolve the foundation
   include (git+https://github.com/microsoft/amplifier-foundation@main),
   which is acceptable in the upstream CI lane this test is meant for.
"""

from __future__ import annotations

import asyncio
import importlib.util
import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

SOURCE_PREFIX = "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main#subdirectory=modules/"
UNSUPPORTED_PREFIX = "fast-decisions:modules/"

# Files that may declare a module `source:` pointing into modules/.
COMPOSITION_FILES = [
    ROOT / "bundle.md",
    ROOT / "behaviors" / "fast-decisions.yaml",
    ROOT / "bundles" / "shadow.yaml",
    ROOT / "bundles" / "active.yaml",
]


def _load_frontmatter(path: Path) -> dict:
    """Parse a bundle file's YAML, whether it's frontmatter (bundle.md) or plain YAML."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        match = re.match(r"^---\n(.*?)\n---\n?", text, re.DOTALL)
        if not match:
            raise ValueError(f"No YAML frontmatter found in {path}")
        text = match.group(1)
    return yaml.safe_load(text)


def _iter_module_sources(data: dict):
    """Yield (module_name, source) pairs for every module entry in a parsed bundle doc."""
    for section in ("tools", "hooks", "providers"):
        for entry in data.get(section, []) or []:
            if isinstance(entry, dict) and "source" in entry:
                yield entry.get("module"), entry["source"]
    session = data.get("session") or {}
    orchestrator = session.get("orchestrator") or {}
    if isinstance(orchestrator, dict) and "source" in orchestrator:
        yield orchestrator.get("module"), orchestrator["source"]
    context = session.get("context") or {}
    if isinstance(context, dict) and "source" in context:
        yield context.get("module"), context["source"]


class YamlSourceTests(unittest.TestCase):
    """Always-on checks against the raw YAML; no amplifier_foundation needed."""

    def test_module_sources_use_supported_form_and_resolve(self):
        checked_any = False
        for path in COMPOSITION_FILES:
            data = _load_frontmatter(path)
            for module_name, source in _iter_module_sources(data):
                if UNSUPPORTED_PREFIX in source:
                    self.fail(
                        f"{path}: module {module_name!r} uses unsupported "
                        f"'{UNSUPPORTED_PREFIX}' source form: {source!r}"
                    )
                if "amplifier-bundle-fast-decisions" not in source:
                    # Not one of our own modules (e.g. foundation's loop-streaming); skip.
                    continue
                checked_any = True
                self.assertTrue(
                    source.startswith(SOURCE_PREFIX),
                    f"{path}: module {module_name!r} source {source!r} does not "
                    f"start with {SOURCE_PREFIX!r}",
                )
                mod_dir_name = source[len(SOURCE_PREFIX) :]
                module_pyproject = ROOT / "modules" / mod_dir_name / "pyproject.toml"
                self.assertTrue(
                    module_pyproject.is_file(),
                    f"{path}: module {module_name!r} references "
                    f"modules/{mod_dir_name}/pyproject.toml, which does not exist",
                )
                entry_point_pattern = re.compile(
                    r'\[project\.entry-points\."amplifier\.modules"\]\s*\n'
                    rf"{re.escape(mod_dir_name)}\s*="
                )
                self.assertRegex(
                    module_pyproject.read_text(encoding="utf-8"),
                    entry_point_pattern,
                    f"modules/{mod_dir_name}/pyproject.toml does not declare the "
                    f"'{mod_dir_name}' entry point under [project.entry-points.\"amplifier.modules\"]",
                )
        self.assertTrue(
            checked_any, "Expected to find at least one fast-decisions module source"
        )


def _amplifier_foundation_importable() -> bool:
    """True only if amplifier_foundation actually imports (not merely findable).

    A stale/partial editable install (present on sys.path but missing a
    transitive dependency such as amplifier_core) must skip, not error.
    """
    if importlib.util.find_spec("amplifier_foundation") is None:
        return False
    try:
        importlib.import_module("amplifier_foundation")
    except ImportError:
        return False
    return True


@unittest.skipUnless(
    _amplifier_foundation_importable(),
    "amplifier_foundation not installed (or not importable)",
)
class BundleLoadTests(unittest.TestCase):
    """Loads real bundles through amplifier_foundation and inspects the mount plan.

    Requires network access to resolve git+https://.../amplifier-foundation@main;
    intended for the upstream CI lane.
    """

    @staticmethod
    def _load(relative_path: str):
        from amplifier_foundation import load_bundle

        uri = "file://" + str((ROOT / relative_path).resolve())
        return asyncio.run(load_bundle(uri))

    def test_root_bundle_composes_with_foundation(self):
        bundle = self._load("bundle.md")
        self.assertEqual(bundle.name, "fast-decisions")
        mount_plan = bundle.to_mount_plan()

        orchestrator = mount_plan["session"]["orchestrator"]
        self.assertEqual(
            orchestrator["module"],
            "loop-streaming",
            "root bundle.md must not replace foundation's orchestrator",
        )

        tool_modules = {t["module"] for t in mount_plan.get("tools", [])}
        hook_modules = {h["module"] for h in mount_plan.get("hooks", [])}
        self.assertIn("tool-fast-workspace", tool_modules)
        self.assertIn("hooks-fast-decisions", hook_modules)

    def _assert_decision_bundle(
        self,
        relative_path: str,
        expected_name: str,
        expected_mode: str,
        expected_allow_external: bool,
    ):
        bundle = self._load(relative_path)
        self.assertEqual(bundle.name, expected_name)
        mount_plan = bundle.to_mount_plan()

        orchestrator = mount_plan["session"]["orchestrator"]
        self.assertEqual(orchestrator["module"], "loop-fast-decisions")

        config = orchestrator["config"]
        self.assertEqual(config["mode"], expected_mode)
        self.assertIs(config["allow_external_state"], expected_allow_external)
        self.assertIn("upstream", config)

        self.assertTrue(
            orchestrator["source"].startswith(
                "git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main"
                "#subdirectory=modules/loop-fast-decisions"
            ),
            orchestrator["source"],
        )

        # Inherited from root bundle.md via the includes chain.
        tool_modules = {t["module"] for t in mount_plan.get("tools", [])}
        hook_modules = {h["module"] for h in mount_plan.get("hooks", [])}
        self.assertIn("tool-fast-workspace", tool_modules)
        self.assertIn("hooks-fast-decisions", hook_modules)

    def test_shadow_bundle_is_deprecated_forwarding_alias(self):
        """bundles/shadow.yaml no longer swaps session.orchestrator (P3): shadow
        measurement now lives on the hook and composes onto any orchestrator.
        This bundle still resolves and still names/configures the shadow
        rung, but the orchestrator stays loop-streaming (inherited via
        bundle.md), and its description opens with DEPRECATED."""
        bundle = self._load("bundles/shadow.yaml")
        self.assertEqual(bundle.name, "fast-decisions-shadow")
        self.assertTrue(bundle.description.strip().startswith("DEPRECATED"))
        mount_plan = bundle.to_mount_plan()

        orchestrator = mount_plan["session"]["orchestrator"]
        self.assertEqual(
            orchestrator["module"], "loop-streaming",
            "bundles/shadow.yaml must no longer swap the orchestrator",
        )

        hook_modules = {h["module"]: h for h in mount_plan.get("hooks", [])}
        self.assertIn("hooks-fast-decisions", hook_modules)
        self.assertEqual(hook_modules["hooks-fast-decisions"]["config"]["mode"], "shadow")

        tool_modules = {t["module"] for t in mount_plan.get("tools", [])}
        self.assertIn("tool-fast-workspace", tool_modules)

    def test_active_bundle(self):
        self._assert_decision_bundle(
            "bundles/active.yaml",
            expected_name="fast-decisions-active",
            expected_mode="active",
            expected_allow_external=True,
        )


if __name__ == "__main__":
    unittest.main()
