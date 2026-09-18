"""Package-level source provenance (HC00: "freeze source").

Answers "which source actually ran?" with hashes and versions only -- never
a filesystem path. See docs/EVENTS.md (`fast_decisions:source`) and
docs/PRIVACY.md.
"""

from __future__ import annotations

import functools
import hashlib
import importlib.metadata
import platform
from pathlib import Path
from typing import Any


def tree_sha256(package_dir: Path) -> str:
    """SHA-256 over every ``*.py`` file under ``package_dir`` (skipping
    ``__pycache__``), keyed by (relative posix path, file bytes) pairs in a
    stable sorted order. Deterministic across machines given identical
    source. Never raises for a missing/unreadable file: it is simply
    skipped, since a partial hash is still more useful than a hard failure
    at mount.
    """
    package_dir = Path(package_dir)
    candidates = [
        path for path in package_dir.rglob("*.py") if "__pycache__" not in path.parts
    ]
    candidates.sort(key=lambda path: path.relative_to(package_dir).as_posix())

    hasher = hashlib.sha256()
    for path in candidates:
        try:
            data = path.read_bytes()
        except OSError:
            continue
        rel = path.relative_to(package_dir).as_posix()
        hasher.update(rel.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(data)
        hasher.update(b"\0")
    return hasher.hexdigest()


def _find_git_entry(start: Path) -> Path | None:
    """Walk up from ``start`` looking for a ``.git`` entry (directory or
    file). Returns the ``.git`` path itself, unresolved -- callers decide
    how to interpret it."""
    current = Path(start).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        git_path = candidate / ".git"
        if git_path.exists():
            return git_path
    return None


def _resolve_gitdir(git_entry: Path) -> Path | None:
    """``git_entry`` is a ``.git`` directory (plain repo) or a ``.git`` file
    (worktree) containing ``gitdir: <path>``. Returns the real gitdir."""
    if git_entry.is_dir():
        return git_entry
    try:
        content = git_entry.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not content.startswith("gitdir:"):
        return None
    raw_path = content.split(":", 1)[1].strip()
    gitdir = Path(raw_path)
    if not gitdir.is_absolute():
        gitdir = (git_entry.parent / gitdir).resolve()
    return gitdir if gitdir.exists() else None


def _common_dir(gitdir: Path) -> Path:
    """A worktree's gitdir carries a ``commondir`` file pointing at the main
    repository's ``.git`` directory, where shared refs actually live. Plain
    (non-worktree) repos have no such file; ``gitdir`` is already the
    common dir in that case."""
    commondir_file = gitdir / "commondir"
    if not commondir_file.exists():
        return gitdir
    try:
        content = commondir_file.read_text(encoding="utf-8").strip()
    except OSError:
        return gitdir
    common = Path(content)
    if not common.is_absolute():
        common = (gitdir / common).resolve()
    return common if common.exists() else gitdir


def _read_ref(base_dir: Path, ref: str) -> str | None:
    ref_path = base_dir / ref
    if ref_path.exists():
        try:
            value = ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            return None
        return value if len(value) == 40 else None
    packed_refs = base_dir / "packed-refs"
    if not packed_refs.exists():
        return None
    try:
        lines = packed_refs.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        line = line.strip()
        if not line or line[0] in "#^":
            continue
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1] == ref and len(parts[0]) == 40:
            return parts[0]
    return None


def git_head_sha(start: Path) -> str | None:
    """The 40-hex commit sha HEAD resolves to for the repo containing
    ``start``, or ``None`` if no repo is found or HEAD cannot be resolved.
    Supports a plain ``.git`` directory and a ``.git`` file (git worktrees):
    a worktree's own gitdir holds ``HEAD`` (and, for a detached checkout,
    HEAD already contains the raw sha); a symbolic HEAD's ref is looked up
    in the worktree gitdir first, then in the shared common dir found via
    ``commondir``, then in that common dir's ``packed-refs``. Never raises.
    """
    try:
        git_entry = _find_git_entry(start)
        if git_entry is None:
            return None
        gitdir = _resolve_gitdir(git_entry)
        if gitdir is None:
            return None
        head_file = gitdir / "HEAD"
        if not head_file.exists():
            return None
        head = head_file.read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head if len(head) == 40 else None
        ref = head.split(":", 1)[1].strip()
        sha = _read_ref(gitdir, ref)
        if sha:
            return sha
        common_dir = _common_dir(gitdir)
        return _read_ref(common_dir, ref)
    except Exception:
        return None


@functools.lru_cache(maxsize=1)
def describe_source() -> dict[str, Any]:
    """Cheap (~30 files), privacy-safe description of the running package's
    source: never a filesystem path, only hashes/counts/versions. Safe to
    call every mount; the result is cached for the process lifetime.
    """
    package_dir = Path(__file__).parent
    package_dir_str = str(package_dir)
    git_entry_found = _find_git_entry(package_dir) is not None
    if "/.amplifier/cache/" in package_dir_str:
        source_kind = "installed-cache"
    elif git_entry_found:
        source_kind = "worktree"
    elif "site-packages" in package_dir_str:
        source_kind = "site-packages"
    else:
        source_kind = "unknown"
    try:
        package_version = importlib.metadata.version("amplifier-fast-decisions")
    except importlib.metadata.PackageNotFoundError:
        package_version = None
    except Exception:
        package_version = None
    try:
        source_tree_sha256 = tree_sha256(package_dir)
    except Exception:
        source_tree_sha256 = None
    try:
        source_py_files = sum(
            1 for path in package_dir.rglob("*.py") if "__pycache__" not in path.parts
        )
    except Exception:
        source_py_files = 0
    return {
        "source_kind": source_kind,
        "source_git_sha": git_head_sha(package_dir),
        "source_tree_sha256": source_tree_sha256,
        "source_py_files": source_py_files,
        "package_version": package_version,
    }


def source_event_data(*, mode: str | None, module: str) -> dict[str, Any]:
    """Best-effort ``fast_decisions:source`` event payload. Never raises --
    a failure in provenance collection degrades to ``source_kind: "unknown"``
    rather than breaking hook/orchestrator mount.
    """
    try:
        data = dict(describe_source())
    except Exception:
        data = {
            "source_kind": "unknown",
            "source_git_sha": None,
            "source_tree_sha256": None,
            "source_py_files": None,
            "package_version": None,
        }
    data["mode"] = mode
    data["python"] = platform.python_version()
    data["module"] = module
    return data
