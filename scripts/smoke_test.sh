#!/usr/bin/env bash
# Offline smoke test. The package uses a src/ layout, so either install it
# (`pip install -e '.[test]'`) or put src/ on the path, as done here.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONPATH="${PWD}/src${PYTHONPATH:+:$PYTHONPATH}"
python3 -m unittest discover -s tests -v
python3 -m amplifier_fast_decisions doctor
