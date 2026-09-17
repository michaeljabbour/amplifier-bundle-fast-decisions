"""A deliberately small read-only workspace tool for the initial active pilot.

No shell, network, writes, recursion, dotfiles, symlinks, or non-text reads.
The filesystem must not be adversarially mutated during a read; ordinary
workspace containment is provided, not an OS sandbox for hostile processes.
"""
from __future__ import annotations
import asyncio
import codecs
import os
from pathlib import Path
import stat
from typing import Any

from .contracts import Candidate, digest
from .privacy import scrub

__amplifier_module_type__ = "tool"
_ALLOWED = {".md", ".txt", ".py", ".rs", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".html", ".css"}
_BLOCKED = {"credentials", "secrets", "secret", "id_rsa", "id_ed25519", "token", "tokens", "passwords"}


class WorkspaceTool:
    name = "fast_workspace"
    description = "Read or list non-hidden text files within the configured workspace. No writes, shell, or network."
    input_schema = {
        "type": "object", "additionalProperties": False,
        "properties": {"operation": {"type": "string", "enum": ["read", "list"]},
                       "path": {"type": "string", "maxLength": 512}},
        "required": ["operation", "path"],
    }

    def __init__(self, root: str | Path = ".", max_bytes: int = 32768):
        self.root = Path(root).expanduser().resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("Workspace root is not a directory")
        self.max_bytes = max(1024, min(int(max_bytes), 262144))

    def _path(self, relative: str, *, file: bool = False) -> Path:
        if not isinstance(relative, str) or len(relative) > 512 or "\x00" in relative:
            raise ValueError("Invalid path")
        rel = Path(relative)
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Path must stay inside the workspace")
        current = self.root
        for part in rel.parts:
            if part in {"", "."}:
                continue
            if part.startswith(".") or Path(part).stem.lower() in _BLOCKED:
                raise ValueError("Hidden or sensitive file is excluded")
            current = current / part
            if current.is_symlink():
                raise ValueError("Symlinks are excluded")
        resolved = current.resolve(strict=True)
        resolved.relative_to(self.root)
        if file and (not resolved.is_file() or resolved.suffix.lower() not in _ALLOWED):
            raise ValueError("Only allowed text files may be read")
        return resolved

    def _revision(self, path: Path) -> str:
        st = path.stat()
        return digest([st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns])

    def candidate_for_path(self, relative: str, index: int) -> Candidate | None:
        try:
            path = self._path(relative, file=True)
        except (OSError, ValueError):
            return None
        return Candidate("read_" + digest(relative)[:12], f"Read requested file {index + 1}", self.name,
            {"operation": "read", "path": relative},
            rationale=f"Read the workspace text file explicitly named by the user: {relative}",
            origin="explicit_user_path", revision=self._revision(path))

    def validate_candidate(self, candidate: Candidate) -> bool:
        args = candidate.arguments
        if set(args) != {"operation", "path"} or args.get("operation") not in {"read", "list"}:
            return False
        try:
            path = self._path(args["path"], file=args["operation"] == "read")
            if args["operation"] == "list" and not path.is_dir():
                return False
            return not candidate.revision or candidate.revision == self._revision(path)
        except (OSError, ValueError, TypeError):
            return False

    def _read(self, args: dict[str, Any]) -> dict[str, Any]:
        if set(args) != {"operation", "path"}:
            raise ValueError("Unexpected input fields")
        operation = args["operation"]
        if operation not in {"read", "list"}:
            raise ValueError("Unsupported operation")
        path = self._path(args["path"], file=operation == "read")
        if operation == "list":
            if not path.is_dir():
                raise ValueError("Path is not a directory")
            entries = []
            for entry in sorted(path.iterdir()):
                if entry.name.startswith(".") or entry.stem.lower() in _BLOCKED or entry.is_symlink():
                    continue
                entries.append({"name": entry.name, "type": "directory" if entry.is_dir() else "file"})
                if len(entries) >= 100:
                    break
            return {"entries": entries, "limit": 100}
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as file:
            if not stat.S_ISREG(os.fstat(file.fileno()).st_mode):
                raise ValueError("Not a regular file")
            data = file.read(self.max_bytes + 1)
        # Allow a truncated final UTF-8 codepoint, but still reject invalid bytes.
        decoder = codecs.getincrementaldecoder("utf-8")()
        text = decoder.decode(data[:self.max_bytes], final=len(data) <= self.max_bytes)
        if "\x00" in text:
            raise ValueError("Binary content excluded")
        return {"text": scrub(text, self.max_bytes), "truncated": len(data) > self.max_bytes}

    async def execute(self, input: dict[str, Any], **kwargs):
        from amplifier_core.models import ToolResult
        try:
            output = await asyncio.to_thread(self._read, input)
            return ToolResult(success=True, output=output)
        except (ValueError, OSError, UnicodeError) as exc:
            return ToolResult(success=False, error={"message": str(exc), "type": type(exc).__name__})


async def mount(coordinator, config: dict):
    tool = WorkspaceTool(config.get("root", "."), config.get("max_bytes", 32768))
    await coordinator.mount("tools", tool, name=tool.name)
    return None
