"""Live smoke of the local judge adapters. Skipped unless AFAST_JUDGE_LIVE=1.

Only local endpoints are touched (Ollama, Laya), and only arms whose endpoint
answers a probe; three dev cases each.
"""
import asyncio
import os
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
for extra in (str(ROOT), str(ROOT / "src")):
    if extra not in sys.path:
        sys.path.insert(0, extra)


@unittest.skipUnless(os.environ.get("AFAST_JUDGE_LIVE") == "1", "set AFAST_JUDGE_LIVE=1 to run live local checks")
class LiveLocalArmTests(unittest.TestCase):
    def test_local_arms_answer_three_cases(self):
        import httpx
        from evals import judges
        from evals.judge_bench import arms, cases, scoring
        cfg = judges.load_config()
        specs = cfg["arms"]
        try:
            tags = httpx.get("http://127.0.0.1:11434/api/tags", timeout=3).json()
            models = {m["name"] for m in tags.get("models", [])}
        except Exception:
            models = None
        try:
            laya_up = httpx.get("http://127.0.0.1:8090/health", timeout=3).status_code == 200
        except Exception:
            laya_up = False
        probes = cases.dev_cases()[:3]
        ran = 0
        for name, spec in specs.items():
            if not spec.get("local") or spec["adapter"] == "instruction_clause":
                continue
            if spec["url" if "url" in spec else "adapter"] and spec.get("url", "").startswith("http://127.0.0.1:8090"):
                if not laya_up:
                    continue
            elif models is None or (spec.get("model") not in models and f"{spec.get('model')}:latest" not in models):
                continue
            with self.subTest(arm=name):
                arm = arms.build_arm(spec, specs)

                async def go():
                    async with httpx.AsyncClient(timeout=60) as client:
                        return [await arm.decide(client, case["payload"]) for case in probes]
                for case, result in zip(probes, asyncio.run(go())):
                    scoring.validate_answer(case, result["answer"])
                    self.assertIn("timing", result)
                ran += 1
        if not ran:
            self.skipTest("no local endpoint answered a probe")


if __name__ == "__main__":
    unittest.main()
