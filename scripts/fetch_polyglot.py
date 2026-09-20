"""Fetch (or update) a shallow clone of Aider-AI/polyglot-benchmark and record
a manifest describing what languages/exercises it contains.

Usage:
    python3 scripts/fetch_polyglot.py --dest <dir> [--ref main]

Behavior:
  - If `<dest>/polyglot-benchmark` does not exist: `git clone --depth 1
    [--branch <ref>] <url> <dest>/polyglot-benchmark`.
  - If it already exists: `git -C <dest>/polyglot-benchmark pull --ff-only`.
  - Writes `<dest>/polyglot-manifest.json` with the resulting commit sha and
    the per-language exercise count.
  - Prints one JSON line to stdout summarizing the result.

This module intentionally separates network/subprocess actions (`fetch`) from
pure manifest construction (`build_manifest`) so tests can exercise the
manifest logic against a fake on-disk tree without touching the network.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

REPO_URL = "https://github.com/Aider-AI/polyglot-benchmark"
CHECKOUT_DIRNAME = "polyglot-benchmark"
MANIFEST_FILENAME = "polyglot-manifest.json"


def _run_git(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
        timeout=600,
    )


def clone_or_update(dest: Path, ref: str | None = None) -> Path:
    """Ensure a checkout of the polyglot-benchmark repo exists under `dest`.

    Returns the path to the checkout directory. Raises RuntimeError if the
    underlying git command fails.
    """
    dest.mkdir(parents=True, exist_ok=True)
    checkout = dest / CHECKOUT_DIRNAME
    if checkout.exists():
        proc = _run_git(["pull", "--ff-only"], cwd=checkout)
        if proc.returncode != 0:
            raise RuntimeError(f"git pull failed: {proc.stderr}")
        return checkout

    clone_args = ["clone", "--depth", "1"]
    if ref:
        clone_args += ["--branch", ref]
    clone_args += [REPO_URL, str(checkout)]
    proc = _run_git(clone_args)
    if proc.returncode != 0:
        raise RuntimeError(f"git clone failed: {proc.stderr}")
    return checkout


def current_sha(checkout: Path) -> str:
    proc = _run_git(["rev-parse", "HEAD"], cwd=checkout)
    if proc.returncode != 0:
        raise RuntimeError(f"git rev-parse failed: {proc.stderr}")
    return proc.stdout.strip()


def _exercise_slugs(lang_dir: Path) -> list[str]:
    practice = lang_dir / "exercises" / "practice"
    if not practice.is_dir():
        return []
    return sorted(p.name for p in practice.iterdir() if p.is_dir())


def build_manifest(checkout: Path, sha: str | None = None) -> dict:
    """Build the manifest dict by scanning an on-disk checkout tree.

    Pure function of the filesystem contents of `checkout` -- no network, no
    subprocess (except the optional caller-supplied sha). Safe to call
    against a fake tree in tests.
    """
    languages: dict[str, dict] = {}
    if checkout.is_dir():
        for lang_dir in sorted(checkout.iterdir()):
            if not lang_dir.is_dir() or lang_dir.name.startswith("."):
                continue
            slugs = _exercise_slugs(lang_dir)
            if not slugs:
                continue
            languages[lang_dir.name] = {"count": len(slugs), "exercises": slugs}
    return {
        "sha": sha,
        "languages": {lang: info["count"] for lang, info in languages.items()},
        "exercise_slugs": {lang: info["exercises"] for lang, info in languages.items()},
        "total_exercises": sum(info["count"] for info in languages.values()),
    }


def write_manifest(dest: Path, manifest: dict) -> Path:
    manifest_path = dest / MANIFEST_FILENAME
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def fetch(dest: Path, ref: str | None = None) -> dict:
    """Full fetch flow: clone/update, compute sha, build + write manifest."""
    checkout = clone_or_update(dest, ref=ref)
    sha = current_sha(checkout)
    manifest = build_manifest(checkout, sha=sha)
    write_manifest(dest, manifest)
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Fetch the Aider polyglot-benchmark corpus.")
    parser.add_argument("--dest", required=True, help="Destination directory for the checkout + manifest.")
    parser.add_argument("--ref", default=None, help="Optional branch/tag/ref to clone (default: repo default branch).")
    args = parser.parse_args(argv)

    dest = Path(args.dest).expanduser()
    manifest = fetch(dest, ref=args.ref)
    summary = {
        "dest": str(dest),
        "checkout": str(dest / CHECKOUT_DIRNAME),
        "sha": manifest["sha"],
        "languages": manifest["languages"],
        "total_exercises": manifest["total_exercises"],
    }
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
