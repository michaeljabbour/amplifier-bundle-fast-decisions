"""Export the actual viewer with the no-key demo; never read user telemetry."""
import asyncio
from pathlib import Path
import tempfile

from amplifier_fast_decisions.cli import export_html
from amplifier_fast_decisions.demo import run_demo


async def main():
    output = Path(__file__).with_name("observatory-preview.html")
    with tempfile.TemporaryDirectory(prefix="afast-visual-preview-") as directory:
        await run_demo(directory)
        export_html(directory, output)
    # Show explicitly synthetic data in this standalone preview only. The live
    # viewer retains its default exclusion, and all metrics still exclude it.
    output.write_text(output.read_text().replace(
        "<script>window.AFAST_EMBEDDED=",
        '<script>document.getElementById("includeSynthetic").checked=true;window.AFAST_EMBEDDED=',
    ))


if __name__ == "__main__":
    asyncio.run(main())
