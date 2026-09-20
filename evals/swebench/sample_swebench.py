#!/usr/bin/env python3
"""Host-side SWE-bench Verified sampler + task-dir generator.

Adapted from the amplifier-bundle-evaluation example 04 sampler
(examples/04-foundation-vs-dev-demo/swebench/sample_swebench.py, "Host-side
SWE-bench Multimodal sampler"), which sampled ONE instance per invocation into
a flat {instance.json, problem_statement.md} pair for run.sh to copy into a
single pre-existing task directory. This version:

  - targets `princeton-nlp/SWE-bench_Verified` (test split) instead of
    `SWE-bench_Multimodal` (dev split) -- Verified is plain Python issues,
    Multimodal is JS with image assets; S3 (STUDY-DESIGN.md section 15) is
    the pinned, gradable Verified slice.
  - samples a BATCH of --n instances at once (default 30) and writes one full
    task directory per instance directly under --out (task.yaml, meta.yaml,
    profile.yaml, grader.yaml, workspace/.gitkeep, grader-data/.gitkeep),
    following the same task shape as example 04's swebench-N tasks, instead
    of one instance.json/problem_statement.md pair for a caller to copy in.
  - a --pinned-file that holds MANY ids (one per line), not one. If the file
    exists and every id in it resolves against the loaded split, that exact
    list is used (reproducible re-runs). If it is absent, or any id fails to
    resolve, --n ids are re-sampled deterministically with --seed and the
    file is rewritten -- this is what lets a placeholder PINNED_INSTANCE_IDS
    self-heal the first time this script actually runs against the real
    dataset (see evals/swebench/README.md "Preflight").

Network access (HuggingFace Hub) happens only inside `_download_dataset` /
`_load_all_samples`; every other function is pure and takes the loaded
sample list as a plain argument, so tests substitute a fake list and never
touch the network -- see tests/test_swebench_stage.py.

Run via uv to avoid polluting the host env, exactly like the example:
    uv run --quiet --with huggingface_hub --with pyarrow python3 \
        evals/swebench/sample_swebench.py \
        --n 30 --seed 42 --split verified --out evals/swebench/tasks \
        --pinned-file evals/swebench/PINNED_INSTANCE_IDS
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

_DATASETS = {
    # split-name -> (HF repo id, HF split, parquet filename)
    "verified": (
        "princeton-nlp/SWE-bench_Verified",
        "test",
        "data/test-00000-of-00001.parquet",
    ),
}


@dataclass(frozen=True)
class SWEBenchInstance:
    """One SWE-bench Verified record. Mirrors the dataset's own columns --
    no image_assets field (that is Multimodal-only)."""

    instance_id: str
    repo: str
    base_commit: str
    patch: str
    test_patch: str
    problem_statement: str
    hints_text: str
    created_at: str
    version: str
    fail_to_pass: str
    pass_to_pass: str


# ---------------------------------------------------------------------------
# Network I/O (untested directly; substituted by fakes in tests)
# ---------------------------------------------------------------------------


def _download_dataset(cache_dir: Path, split: str) -> Path:
    """Download the SWE-bench Verified parquet from HuggingFace if absent."""
    from huggingface_hub import hf_hub_download  # pyright: ignore[reportMissingImports]

    repo_id, hf_split, filename = _DATASETS[split]
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = cache_dir / f"swebench_{split}_{hf_split}.parquet"
    if output_path.exists():
        return output_path

    try:
        cached_path = hf_hub_download(
            repo_id=repo_id, filename=filename, repo_type="dataset"
        )
    except Exception as exc:  # pragma: no cover -- network failure path
        print(f"ERROR: HuggingFace download failed: {exc}", file=sys.stderr)
        sys.exit(2)
    import shutil

    shutil.copy(cached_path, output_path)
    return output_path


def _load_all_samples(parquet_path: Path) -> list[SWEBenchInstance]:
    import pyarrow.parquet as pq  # pyright: ignore[reportMissingImports]

    table = pq.read_table(parquet_path)
    samples: list[SWEBenchInstance] = []
    for i in range(table.num_rows):
        row = {col: table.column(col)[i].as_py() for col in table.column_names}
        samples.append(
            SWEBenchInstance(
                instance_id=row["instance_id"],
                repo=row["repo"],
                base_commit=row["base_commit"],
                patch=row["patch"],
                test_patch=row["test_patch"],
                problem_statement=row["problem_statement"],
                hints_text=row.get("hints_text", "") or "",
                created_at=row["created_at"],
                version=row.get("version", "") or "",
                fail_to_pass=row["FAIL_TO_PASS"],
                pass_to_pass=row["PASS_TO_PASS"],
            )
        )
    return samples


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Pure selection logic (tested directly against a fake instance list)
# ---------------------------------------------------------------------------


def _count_tests(value: str) -> int:
    """FAIL_TO_PASS / PASS_TO_PASS are stored as JSON-string lists."""
    if not value:
        return 0
    try:
        parsed = json.loads(value)
        return len(parsed) if isinstance(parsed, list) else 0
    except json.JSONDecodeError:
        return 0


def read_pinned_ids(pinned_file: Path | None) -> list[str]:
    """Read one instance id per non-blank line, else []."""
    if not pinned_file or not pinned_file.exists():
        return []
    lines = [ln.strip() for ln in pinned_file.read_text(encoding="utf-8").splitlines()]
    return [ln for ln in lines if ln]


def select_batch(
    samples: list[SWEBenchInstance],
    *,
    n: int,
    seed: int,
    pinned_ids: list[str] | None = None,
) -> list[SWEBenchInstance]:
    """Select `n` instances: reuse `pinned_ids` verbatim if every one of them
    resolves against `samples`; otherwise (empty, or any id unresolvable)
    deterministically sample `n` instances with `seed` instead. Never raises
    on a bad pinned id -- callers that want strictness re-check the returned
    list length/ids themselves; this function's job is simply "give me a
    reproducible batch", falling back rather than failing loud, because a
    stale or placeholder pinned file is an expected, self-healing state (see
    module docstring).
    """
    by_id = {s.instance_id: s for s in samples}

    if pinned_ids:
        resolved = [by_id[i] for i in pinned_ids if i in by_id]
        if len(resolved) == len(pinned_ids) and len(resolved) == n:
            return resolved

    if len(samples) < n:
        raise SystemExit(
            f"ERROR: requested n={n} but only {len(samples)} instances available"
        )
    rng = random.Random(seed)
    return rng.sample(samples, n)


def write_pinned_ids(pinned_file: Path, instances: list[SWEBenchInstance]) -> None:
    pinned_file.parent.mkdir(parents=True, exist_ok=True)
    pinned_file.write_text(
        "".join(f"{s.instance_id}\n" for s in instances), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Task-directory generation (pure filesystem writes; no network)
# ---------------------------------------------------------------------------

_TASK_YAML_TEMPLATE = """\
instructions: |
  You are resolving a real GitHub issue in a Python codebase.

  Read the issue at 'problem_statement.md' in the current directory.

  The repository is at 'repo/' in the current directory, already checked out
  to the buggy commit. Edit files in that directory to resolve the issue. Do
  NOT commit your changes -- they are extracted via `git diff`. Do NOT modify
  files outside 'repo/'.

  Do NOT search the web for the fixing pull request or the project's issue
  tracker -- that would defeat the benchmark.

  Treat me as if I am asleep. I am not here to answer questions, only to read
  your output and grade your patch afterwards.

  When you believe the issue is fixed, stop. The project's test suite will be
  run on your changes.
"""


def _meta_yaml(task_name: str, index: int, total: int) -> str:
    return (
        f"name: {task_name}\n"
        f"description: >\n"
        f"  SWE-bench Verified task {index} of {total} (pinned instance,\n"
        f"  S3 slice -- STUDY-DESIGN.md section 15). Graded by the official\n"
        f"  swebench Docker harness (resolved / unresolved).\n"
        f"difficulty: hard\n"
        f"categories: [benchmark, swebench, swebench-verified, code-patch]\n"
        f"timeout: 2700\n"
    )


def _profile_yaml(task_name: str, repo_url: str, base_commit: str) -> str:
    """Render profile.yaml with the instance's GitHub repo URL and base
    commit baked in as LITERAL values in the `provision.setup_cmds` clone/
    checkout lines -- not as `${SWE_REPO_N}` / `${SWE_COMMIT_N}` launch-var
    placeholders.

    Earlier versions emitted `${SWE_REPO_N}`/`${SWE_COMMIT_N}` expecting
    run.sh to supply them via `--launch-var` (the pattern
    amplifier-bundle-evaluation's example 04 sampler uses). run.sh never
    grew that wiring, so every DTU provisioned with a profile still
    containing the unsubstituted placeholder failed identically:
    `git clone ${SWE_REPO_1} /workspace/repo` -> "repository does not
    exist" (all 90 S3 trials, in ~10s, before the agent ever ran). Baking
    the concrete values in at generation time removes the extra moving
    part entirely: nothing needs to build or thread a per-task
    `--launch-var` map through the harness, and there is nothing left to
    forget to wire up. See swebench_stage.check_preflight's
    `task-profile-placeholders` check, which fails loudly if a `${...}`
    placeholder ever reappears in a generated profile.yaml.
    """
    return (
        f"name: eval-{task_name}\n"
        f"description: >\n"
        f"  Ubuntu 24.04 with uv + git. Clones the SWE-bench Verified instance\n"
        f"  repo into /workspace/repo at its buggy base commit -- the repo URL\n"
        f"  and commit are resolved to literal values below at task-generation\n"
        f"  time (see sample_swebench.py), not via launch-time variables. The\n"
        f"  problem statement is staged into /workspace by the harness seeding\n"
        f"  stage. The agent installs foundation (+ fast-decisions, for the two\n"
        f"  amplifier-fd-* agents) from GitHub (see the agent's install.yaml).\n"
        f"\n"
        f"base:\n"
        f"  image: ubuntu:24.04\n"
        f"\n"
        f"passthrough:\n"
        f"  allow_external: true\n"
        f"  services:\n"
        f"    - name: anthropic\n"
        f"      key_env: ANTHROPIC_API_KEY\n"
        f"\n"
        f"provision:\n"
        f"  setup_cmds:\n"
        f"    - apt-get update && apt-get install -y --no-install-recommends git curl ca-certificates tmux python3 python3-pip && rm -rf /var/lib/apt/lists/*\n"
        f"    - curl -LsSf https://astral.sh/uv/install.sh | sh\n"
        f"    - mkdir -p /workspace\n"
        f"    - git clone {repo_url} /workspace/repo\n"
        f"    - git -C /workspace/repo checkout {base_commit}\n"
        f"\n"
        f"readiness:\n"
        f"  - name: uv-installed\n"
        f'    command: "PATH=/root/.local/bin:$PATH uv --version"\n'
        f"  - name: workspace-exists\n"
        f'    command: "test -d /workspace && echo OK"\n'
        f"  - name: repo-cloned\n"
        f'    command: "test -d /workspace/repo/.git && echo OK"\n'
    )


def _grader_yaml(task_name: str) -> str:
    return f"""\
# Grader for the SWE-bench Verified benchmark task ({task_name}).
#
# The authoritative verdict is PROGRAMMATIC: the official `swebench` Docker
# harness applies the solver's patch and runs the project test suite. The
# grader (1) extracts the solver's patch from the DTU, (2) runs the official
# harness via the kept helper `evals/swebench/grade.py --dataset verified`,
# and (3) awards the point iff the harness reports `resolved: true`.
#
# The harness runs on the HOST (it needs the host Docker daemon), not via the
# DTU exec wrapper. `evals/swebench/grade.py` and the instance.json path are
# resolved relative to the harness process cwd. All host temp paths are
# suffixed with the DTU id so multiple swebench tasks grading in parallel do
# not clobber each other.

evaluations:
  - name: swebench-resolved
    weight: 1.0
    steps: |
      Determine whether the solver resolved the GitHub issue, using the
      official SWE-bench Docker harness. Most commands run on the HOST (no
      exec wrapper); only step 1 reaches into the DTU.

      IMPORTANT: wherever you see <dtu_id> below, substitute the ACTUAL DTU
      id shown above -- temp paths are suffixed with it so concurrent
      gradings of other tasks do not collide.

      1. Extract the solver's patch from the DTU to a host file:
           amplifier-digital-twin exec <dtu_id> -- bash -c 'cd /workspace/repo && git add -N . && git diff' > /tmp/model_patch-<dtu_id>.diff
         Inspect it: `wc -c /tmp/model_patch-<dtu_id>.diff`. An empty patch
         means the solver changed nothing (unresolved), but still run the
         harness in step 2 to produce an authoritative verdict.

      2. Run the official harness via the kept helper. It pulls a
         per-instance Docker image and runs the project test suite, which
         can take 5-20 minutes -- launch it in the BACKGROUND with a
         sentinel and POLL. Do NOT run it as one blocking command:
           rm -rf /tmp/swebench-grade-<dtu_id> /tmp/swebench-grade-<dtu_id>.done /tmp/swebench-grade-<dtu_id>.log
           nohup bash -lc 'uv run --quiet --with swebench python3 evals/swebench/grade.py --instance {task_name}/grader-data/instance.json --patch /tmp/model_patch-<dtu_id>.diff --output /tmp/swebench-grade-<dtu_id> --dataset verified > /tmp/swebench-grade-<dtu_id>.log 2>&1; echo "EXIT:$?" > /tmp/swebench-grade-<dtu_id>.done' >/dev/null 2>&1 &
           echo launched
         Then poll, sleeping ~30s between checks, until the sentinel appears
         (be patient, up to ~25 minutes):
           if [ -f /tmp/swebench-grade-<dtu_id>.done ]; then echo "DONE $(cat /tmp/swebench-grade-<dtu_id>.done)"; else echo RUNNING; tail -c 400 /tmp/swebench-grade-<dtu_id>.log 2>/dev/null; fi
         Do NOT proceed while it prints RUNNING.

      3. Read the authoritative verdict:
           cat /tmp/swebench-grade-<dtu_id>/verdict.json
         The "resolved" boolean is the official result (true iff every
         FAIL_TO_PASS test passes AND every PASS_TO_PASS test still passes).

      4. Score: award the point iff "resolved" is true. If grade.py failed
         (non-zero EXIT, or verdict.json missing), award 0 and note the
         harness failure.
    rubric:
      issue_resolved:
        points: 1
        description: >
          The official SWE-bench harness reports resolved=true for the
          solver's patch (every FAIL_TO_PASS test passes AND every
          PASS_TO_PASS test still passes). Score 0 if unresolved, the patch
          is empty, or the harness did not produce a verdict.
"""


def build_task_dir(
    out_dir: Path,
    task_name: str,
    index: int,
    total: int,
    instance: SWEBenchInstance,
    parquet_sha256: str,
    seed: int | None,
    pinned: bool,
) -> Path:
    """Write one full task directory (task.yaml, meta.yaml, profile.yaml,
    grader.yaml, workspace/, grader-data/) for `instance` under
    `out_dir/task_name`. Pure filesystem writes -- no network. Returns the
    task directory path.
    """
    td = out_dir / task_name
    (td / "workspace").mkdir(parents=True, exist_ok=True)
    (td / "grader-data").mkdir(parents=True, exist_ok=True)
    (td / "workspace" / ".gitkeep").touch()
    (td / "grader-data" / ".gitkeep").touch()

    (td / "task.yaml").write_text(_TASK_YAML_TEMPLATE, encoding="utf-8")
    (td / "meta.yaml").write_text(_meta_yaml(task_name, index, total), encoding="utf-8")
    repo_url = f"https://github.com/{instance.repo}.git"
    (td / "profile.yaml").write_text(
        _profile_yaml(task_name, repo_url, instance.base_commit), encoding="utf-8"
    )
    (td / "grader.yaml").write_text(_grader_yaml(task_name), encoding="utf-8")

    record = asdict(instance)
    record["parquet_sha256"] = parquet_sha256
    record["seed"] = seed
    record["pinned"] = pinned
    record["fail_to_pass_count"] = _count_tests(instance.fail_to_pass)
    record["pass_to_pass_count"] = _count_tests(instance.pass_to_pass)
    (td / "grader-data" / "instance.json").write_text(
        json.dumps(record, indent=2), encoding="utf-8"
    )
    (td / "workspace" / "problem_statement.md").write_text(
        instance.problem_statement, encoding="utf-8"
    )

    return td


def build_all_task_dirs(
    out_dir: Path,
    instances: list[SWEBenchInstance],
    *,
    parquet_sha256: str = "unknown",
    seed: int | None = None,
    pinned: bool = False,
    prefix: str = "swebench",
) -> list[Path]:
    """Write one task dir per instance, named `<prefix>-1` .. `<prefix>-N`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    total = len(instances)
    return [
        build_task_dir(
            out_dir, f"{prefix}-{i}", i, total, inst, parquet_sha256, seed, pinned
        )
        for i, inst in enumerate(instances, start=1)
    ]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Sample a SWE-bench Verified batch and write task dirs"
    )
    parser.add_argument(
        "--out",
        type=Path,
        required=True,
        help="output dir for the swebench-N task dirs",
    )
    parser.add_argument(
        "--n", type=int, default=30, help="how many instances to sample (default 30)"
    )
    parser.add_argument(
        "--seed", type=int, default=42, help="random seed used when (re-)sampling"
    )
    parser.add_argument("--split", choices=list(_DATASETS.keys()), default="verified")
    parser.add_argument(
        "--pinned-file",
        type=Path,
        default=None,
        help="file with one instance id per line; reused verbatim if every id "
        "resolves against the loaded split and its length matches --n, else "
        "re-sampled with --seed and the file is rewritten",
    )
    parser.add_argument(
        "--prefix", default="swebench", help="task dir name prefix (default: swebench)"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / ".cache" / "amplifier-eval-swebench-verified",
        help="where to cache the downloaded parquet",
    )
    args = parser.parse_args(argv)

    print(f"[sample_swebench] downloading {_DATASETS[args.split][0]}", file=sys.stderr)
    parquet_path = _download_dataset(args.cache_dir, args.split)
    parquet_sha = _file_sha256(parquet_path)
    print(f"[sample_swebench] parquet sha256={parquet_sha[:16]}...", file=sys.stderr)

    samples = _load_all_samples(parquet_path)
    print(
        f"[sample_swebench] loaded {len(samples)} {args.split} instances",
        file=sys.stderr,
    )

    pinned_ids = read_pinned_ids(args.pinned_file)
    chosen = select_batch(samples, n=args.n, seed=args.seed, pinned_ids=pinned_ids)
    pinned = (
        bool(pinned_ids)
        and len(chosen) == len(pinned_ids)
        and all(c.instance_id == p for c, p in zip(chosen, pinned_ids))
    )

    if args.pinned_file and not pinned:
        write_pinned_ids(args.pinned_file, chosen)
        print(
            f"[sample_swebench] (re-)pinned {len(chosen)} ids to {args.pinned_file}",
            file=sys.stderr,
        )

    dirs = build_all_task_dirs(
        args.out,
        chosen,
        parquet_sha256=parquet_sha,
        seed=None if pinned else args.seed,
        pinned=pinned,
        prefix=args.prefix,
    )
    for d in dirs:
        print(f"[sample_swebench] wrote {d}", file=sys.stderr)


if __name__ == "__main__":
    main()
