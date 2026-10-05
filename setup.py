"""Build hook: ship the one copy of the default configuration inside the wheel.

``behaviors/fast-decisions.yaml`` is the only hand-edited copy of the shipped defaults. A checkout reads it in
place; an installed wheel has no ``behaviors/`` directory, so the build copies it to
``amplifier_fast_decisions/shipped/`` (see ``config.shipped_behavior_path``). Everything else is in pyproject.toml.
"""
from pathlib import Path
from shutil import copyfile

from setuptools import setup
from setuptools.command.build_py import build_py


class BuildPy(build_py):
    def run(self):
        super().run()
        source = Path(__file__).parent / "behaviors" / "fast-decisions.yaml"
        if source.is_file() and not self.dry_run:
            target = Path(self.build_lib) / "amplifier_fast_decisions" / "shipped"
            target.mkdir(parents=True, exist_ok=True)
            copyfile(source, target / source.name)


setup(cmdclass={"build_py": BuildPy})
