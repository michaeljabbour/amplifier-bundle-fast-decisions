"""Thin Amplifier module entrypoint. Shared code is provided by the root bundle package."""
__amplifier_module_type__ = "hook"

try:
    from amplifier_fast_decisions.registry import mount
except ImportError as exc:  # pragma: no cover - exercised by the stale-package test
    # Every build of the shared package is version 0.1.0 pinned to @main, so an
    # installer can keep an older copy that predates registry mode. The host
    # then drops this hook and fast-decisions silently stops routing. Fail with
    # the repair instead (docs/FACADE-CONTRACT.md, "stale shared package").
    import amplifier_fast_decisions as _package

    raise ImportError(
        "hooks-fast-decisions-router needs amplifier_fast_decisions.registry, but the "
        f"installed amplifier-fast-decisions at {_package.__file__} predates registry mode. "
        "Reinstall it in this environment: uv pip install --python <this python> "
        "--reinstall-package amplifier-fast-decisions --no-deps "
        "'amplifier-fast-decisions @ git+https://github.com/michaeljabbour/amplifier-bundle-fast-decisions@main'"
    ) from exc

__all__ = ["mount"]
