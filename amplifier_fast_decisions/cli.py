"""Human- and agent-friendly entrypoints, with a zero-dependency offline demo."""
from __future__ import annotations
import argparse
import asyncio
import importlib
import importlib.metadata
import inspect
import json
import os
from pathlib import Path
import sys
import threading
import webbrowser

from . import __version__
from .demo import run_demo
from .server import EventIndex, ViewerServer, STATIC

DEFAULT_EVENTS = Path.home() / ".amplifier" / "fast-decisions" / "events"


def doctor(require_amplifier: bool = False) -> int:
    checks: list[dict] = []
    checks.append({"check": "python", "ok": sys.version_info >= (3, 11), "value": sys.version.split()[0]})
    required_ok = True
    for module in ("amplifier_core", "amplifier_module_loop_streaming", "typesafe_sdk"):
        try:
            imported = importlib.import_module(module)
            ok = True
            value = getattr(imported, "__version__", "importable")
        except Exception as exc:
            ok, value = False, type(exc).__name__
        checks.append({"check": module, "ok": ok, "value": value})
        if module != "typesafe_sdk" and not ok:
            required_ok = False
    if required_ok:
        try:
            from .contracts import Candidate
            from .orchestrator import action_response
            from amplifier_module_loop_streaming import StreamingOrchestrator
            action_response(Candidate("doctor", "Doctor", "fast_workspace", {"operation": "list", "path": "."}), "doctor")
            instance = StreamingOrchestrator({})
            params = inspect.signature(instance.execute).parameters
            required_ok = all(p in params for p in ("prompt", "context", "providers", "tools", "hooks"))
            checks.append({"check": "real_envelopes_and_execute_signature", "ok": required_ok})
        except Exception as exc:
            required_ok = False
            checks.append({"check": "real_envelopes_and_execute_signature", "ok": False, "value": type(exc).__name__})
    try:
        importlib.import_module("amplifier_core._engine")
        checks.append({"check": "rust_extension_importable", "ok": True})
    except Exception:
        checks.append({"check": "rust_extension_importable", "ok": False, "note": "Not required for the offline demo"})
    checks.append({"check": "TYPESAFE_API_KEY_present", "ok": bool(os.getenv("TYPESAFE_API_KEY")), "note": "Value is never displayed"})
    entries = {e.name for e in importlib.metadata.entry_points(group="amplifier.modules")}
    checks.append({"check": "module_entry_points", "ok": {"loop-fast-decisions", "hooks-fast-decisions", "tool-fast-workspace"} <= entries,
                   "value": sorted(e for e in entries if "fast-" in e)})
    print(json.dumps({"version": __version__, "checks": checks,
          "note": "Import/schema checks are not a full Rust-kernel or live-Jev integration test."}, indent=2))
    return 1 if require_amplifier and not required_ok else 0


def export_html(directory: str | Path, output: str | Path):
    index = EventIndex(directory)
    index.scan()
    events = list(index.events)
    if not events:
        raise ValueError("No valid events found. Run demo --record-only first.")
    html = (STATIC / "index.html").read_text()
    css = (STATIC / "style.css").read_text()
    script = (STATIC / "app.js").read_text()
    embedded = json.dumps(events, ensure_ascii=True).replace("<", "\\u003c")
    html = html.replace('<link rel="stylesheet" href="style.css">', '<style>' + css + '</style>')
    html = html.replace('<script src="app.js"></script>',
                        '<script>window.AFAST_EMBEDDED=' + embedded + ';</script>\n<script>' + script + '</script>')
    output = Path(output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)
    print(str(output.resolve()))


def configure(args) -> int:
    root = Path(args.bundle_root or Path(__file__).resolve().parents[1]).resolve()
    if not (root / "bundle.md").is_file():
        raise ValueError("Pass --bundle-root pointing to the extracted source bundle")
    if args.mode == "active" and not args.allow_external_state:
        raise ValueError("Active Jev requires --allow-external-state; review docs/PRIVACY.md first")
    workspace = Path(args.workspace).expanduser().resolve(strict=True)
    config = {"mode": args.mode, "allow_external_state": args.allow_external_state,
              "events_dir": str(Path(args.events).expanduser().resolve()),
              "timeout_ms": args.timeout_ms}
    data = {"bundle": {"name": "fast-decisions-" + args.mode, "version": __version__},
            "includes": [{"bundle": root.as_uri()}],
            "session": {"orchestrator": {"module": "loop-fast-decisions", "config": config}},
            "tools": [{"module": "tool-fast-workspace", "config": {"root": str(workspace)}}]}
    output = Path(args.output).expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    # JSON is a YAML subset: no extra dependency needed for valid frontmatter.
    output.write_text("---\n" + json.dumps(data, indent=2) + "\n---\n")
    print(str(output.resolve()))
    print("This only wrote a local bundle profile. It did not modify your installed app or send data.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="afast", description="Amplifier Decision Observatory, local and read-only")
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("demo", "serve"):
        command = commands.add_parser(name)
        command.add_argument("--events", default=str(DEFAULT_EVENTS if name == "serve" else Path.cwd() / ".afast-demo-events"))
        command.add_argument("--port", type=int, default=8765)
        command.add_argument("--open", action="store_true")
        if name == "demo":
            command.add_argument("--record-only", action="store_true")
    command = commands.add_parser("export")
    command.add_argument("--events", required=True)
    command.add_argument("--output", default="decision-observatory.html")
    command = commands.add_parser("doctor")
    command.add_argument("--require-amplifier", action="store_true")
    command = commands.add_parser("configure")
    command.add_argument("--bundle-root")
    command.add_argument("--workspace", default=".")
    command.add_argument("--mode", choices=["off", "shadow", "active"], default="shadow")
    command.add_argument("--allow-external-state", action="store_true")
    command.add_argument("--events", default=str(DEFAULT_EVENTS))
    command.add_argument("--timeout-ms", type=int, default=750)
    command.add_argument("--output", default=".amplifier/fast-decisions-local.md")
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor(args.require_amplifier)
        if args.command == "configure":
            return configure(args)
        if args.command == "export":
            export_html(args.events, args.output)
            return 0
        if args.command == "demo" and args.record_only:
            asyncio.run(run_demo(args.events))
            print("Synthetic demo recorded in " + str(Path(args.events).resolve()))
            return 0
        server = ViewerServer(args.events, args.port)
        stop = threading.Event()
        worker = None
        if args.command == "demo":
            print("SYNTHETIC DEMO: scripted decisions and delays, not Jev benchmarks.")
            worker = threading.Thread(target=lambda: asyncio.run(run_demo(args.events, stop=stop, repeat=True)), daemon=True)
            worker.start()
        print("Read-only local viewer: " + server.url, flush=True)
        print("Telemetry directory: " + str(Path(args.events).expanduser().resolve()), flush=True)
        if args.open:
            webbrowser.open(server.url)
        try:
            server.serve_forever(poll_interval=0.25)
        except KeyboardInterrupt:
            pass
        finally:
            stop.set()
            server.server_close()
            if worker:
                worker.join(timeout=3)
        return 0
    except (ValueError, OSError) as exc:
        print("afast: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
