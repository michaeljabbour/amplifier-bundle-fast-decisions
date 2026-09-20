#!/usr/bin/env python3
"""Multidimensional benchmark comparison report across battery.py campaigns.

Reads already-produced `battery.py` campaign artifacts (runs/manifest.json,
runs/<name>/result.json or runs/amplifier/<name>/result.json, plus
receipts.jsonl/measurements.json for amplifier-* harnesses) and renders a
plain-language comparison across one or more "series" -- each series being one
harness within one experiment within one campaign root.

Every number in the report is derived directly from those result files; this
tool never invents a figure and never calls an LLM, a harness, or the network.
Stdlib only.

CLI:
    python3 scripts/battery_report.py --out <dir> \
        --series "Codex=~/dev/afast-campaign-battery20-20260918:BASE:codex" \
        --series "Amplifier + fast-decisions=~/dev/afast-campaign-corrected-polyglot-20260919:FIX-BASE:amplifier-fd" \
        [--title "..."] [--task-filter REGEX] [--family-map family=Label ...] \
        [--exclude-startup / --no-exclude-startup]

Writes <out>/report.md and <out>/report.json, exits 0.
"""
from __future__ import annotations

import argparse
import collections
import json
import math
import re
import statistics
import sys
from pathlib import Path

# --------------------------------------------------------------------------
# small stdlib-only stats helpers (deliberately reimplemented rather than
# imported from battery.py -- this tool must stay a standalone, dependency-
# free brick; see docstring above)
# --------------------------------------------------------------------------


def _mean(xs):
    return statistics.mean(xs) if xs else None


def _median(xs):
    return statistics.median(xs) if xs else None


def _iqr(xs):
    """Tukey hinges: median of the lower half and median of the upper half
    (excluding the overall median itself when n is odd), Q3-Q1."""
    if not xs:
        return None
    s = sorted(xs)
    n = len(s)
    mid = n // 2
    lower = s[:mid]
    upper = s[mid:] if n % 2 == 0 else s[mid + 1:]
    if not lower or not upper:
        return 0.0
    return statistics.median(upper) - statistics.median(lower)


def _geomean(values):
    if not values:
        return None
    return math.exp(sum(math.log(v) for v in values) / len(values))


def _sign_test_p(diffs):
    """Exact two-sided binomial sign test at p=0.5, stdlib math.comb only.

    diffs: a-minus-b style values; negative means a won (was faster/lower),
    positive means a lost, zero is a tie (excluded from n)."""
    wins = sum(1 for d in diffs if d < 0)
    losses = sum(1 for d in diffs if d > 0)
    n = wins + losses
    if n == 0:
        return None
    k = min(wins, losses)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n) * 2
    return min(1.0, p)


def _time_ms(result, exclude_startup=True):
    """The time-metric ms value for one result, honoring --exclude-startup.

    exclude_startup=True: exec_time_ms, falling back to wall_time_ms.
    exclude_startup=False: wall_time_ms, falling back to exec_time_ms.
    None when neither field is present."""
    if not result:
        return None
    if exclude_startup:
        ms = result.get('exec_time_ms')
        if ms is None:
            ms = result.get('wall_time_ms')
    else:
        ms = result.get('wall_time_ms')
        if ms is None:
            ms = result.get('exec_time_ms')
    return ms


# --------------------------------------------------------------------------
# CLI parsing helpers
# --------------------------------------------------------------------------


def parse_series_spec(spec):
    """'Label=campaign_root:experiment:harness' -> (label, root, experiment, harness).

    Uses rsplit(':', 2) so campaign_root itself may contain colons; only the
    trailing two ':'-separated fields (experiment, harness) are peeled off."""
    if '=' not in spec:
        raise ValueError(f'invalid --series (expected label=root:experiment:harness): {spec!r}')
    label, rest = spec.split('=', 1)
    parts = rest.rsplit(':', 2)
    if len(parts) != 3 or not all(p.strip() for p in parts):
        raise ValueError(f'invalid --series (expected label=root:experiment:harness): {spec!r}')
    root, experiment, harness = (p.strip() for p in parts)
    label = label.strip()
    if not label:
        raise ValueError(f'invalid --series (empty label): {spec!r}')
    return label, root, experiment, harness


def parse_family_map(pairs):
    mapping = {}
    for kv in pairs or []:
        if '=' not in kv:
            raise ValueError(f'invalid --family-map (expected family=Label): {kv!r}')
        k, v = kv.split('=', 1)
        mapping[k.strip()] = v.strip()
    return mapping


# --------------------------------------------------------------------------
# loading campaign artifacts (read-only)
# --------------------------------------------------------------------------


def _run_dir_for(experiment_dir, name, harness):
    """Mirrors battery.py's _run_dir_for: amplifier-* harnesses run under
    runs/amplifier/<name>; everything else runs directly under runs/<name>."""
    if harness.startswith('amplifier'):
        return experiment_dir / 'runs' / 'amplifier' / name
    return experiment_dir / 'runs' / name


def load_series(label, root, experiment, harness, task_filter_re=None):
    """Load one series: the latest-attempt result for every task scheduled
    for `harness` in `experiment` under campaign `root`, filtered by
    `task_filter_re` (matched against the task name) when given."""
    root_path = Path(root).expanduser().resolve()
    experiment_dir = root_path / 'experiments' / experiment
    manifest_path = experiment_dir / 'runs' / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))

    groups = collections.defaultdict(list)
    for name, item in manifest['runs'].items():
        if item.get('harness') != harness:
            continue
        task = item['task']
        if task_filter_re and not task_filter_re.search(task):
            continue
        groups[task].append((item.get('attempt', 1), name))

    tasks = {}
    for task, members in groups.items():
        members.sort()
        max_attempt, name = members[-1]
        run_dir = _run_dir_for(experiment_dir, name, harness)
        result_path = run_dir / 'result.json'
        result = json.loads(result_path.read_text(encoding='utf-8')) if result_path.exists() else None
        tasks[task] = {
            'name': name, 'result': result, 'run_dir': run_dir,
            'attempts': len(members), 'max_attempt': max_attempt,
        }

    return {
        'label': label, 'root': str(root_path), 'experiment': experiment, 'harness': harness,
        'experiment_dir': experiment_dir, 'tasks': tasks,
    }


# --------------------------------------------------------------------------
# section 1: overview
# --------------------------------------------------------------------------


def compute_overview(series, exclude_startup):
    tasks = series['tasks']
    all_results = [info['result'] for info in tasks.values() if info['result']]
    passed_results = [r for r in all_results if r.get('outcome_passed')]

    times_s = [t / 1000.0 for t in
               (_time_ms(r, exclude_startup) for r in passed_results) if t is not None]
    wall_s = [r['wall_time_ms'] / 1000.0 for r in passed_results if r.get('wall_time_ms') is not None]
    costs = [r['cost_usd'] for r in all_results if r.get('cost_usd') is not None]

    return {
        'tasks_attempted': len(tasks),
        'passed': len(passed_results),
        'deadline_failures': sum(1 for r in all_results if r.get('timed_out')),
        'median_working_time_s': _median(times_s),
        'mean_working_time_s': _mean(times_s),
        'iqr_working_time_s': _iqr(times_s),
        'median_time_incl_startup_s': _median(wall_s),
        'mean_cost_usd': _mean(costs),
        'cost_not_billed_count': sum(1 for r in all_results if r.get('cost_billable') is False),
        'cost_estimated_count': sum(1 for r in all_results
                                     if r.get('cost_source') == 'computed_from_tokens_estimate'),
        'cost_unknown_count': sum(1 for r in all_results if r.get('cost_usd') is None),
        'infrastructure_retries': sum(1 for info in tasks.values() if info['attempts'] > 1),
    }


# --------------------------------------------------------------------------
# section 2: by family / language
# --------------------------------------------------------------------------


def compute_family_table(series, family_map, exclude_startup):
    buckets = collections.defaultdict(lambda: {'n': 0, 'passed': 0, 'times_s': []})
    for info in series['tasks'].values():
        result = info['result']
        family = (result.get('family') if result else None) or 'unknown'
        family = family_map.get(family, family)
        bucket = buckets[family]
        bucket['n'] += 1
        if result and result.get('outcome_passed'):
            bucket['passed'] += 1
            ms = _time_ms(result, exclude_startup)
            if ms is not None:
                bucket['times_s'].append(ms / 1000.0)
    return {
        family: {'n': b['n'], 'passed': b['passed'], 'median_working_time_s': _median(b['times_s'])}
        for family, b in buckets.items()
    }


# --------------------------------------------------------------------------
# section 3: head-to-head
# --------------------------------------------------------------------------


def compute_head_to_head(all_series, exclude_startup):
    pairs = {}
    sentences = collections.defaultdict(list)
    for a in all_series:
        for b in all_series:
            if a is b:
                continue
            common = sorted(set(a['tasks']) & set(b['tasks']))
            wins = losses = ties = 0
            ratios, diffs = [], []
            for t in common:
                ra = a['tasks'][t]['result']
                rb = b['tasks'][t]['result']
                if not (ra and ra.get('outcome_passed') and rb and rb.get('outcome_passed')):
                    continue
                ta = _time_ms(ra, exclude_startup)
                tb = _time_ms(rb, exclude_startup)
                if ta is None or tb is None:
                    continue
                if ta < tb:
                    wins += 1
                elif ta > tb:
                    losses += 1
                else:
                    ties += 1
                ratios.append(ta / tb)
                diffs.append(ta - tb)
            n_common_passed = wins + losses + ties
            ratio = _geomean(ratios)
            p_value = _sign_test_p(diffs)
            key = f"{a['label']}__vs__{b['label']}"
            pairs[key] = {
                'a': a['label'], 'b': b['label'], 'n_shared_tasks': len(common),
                'n_common_passed': n_common_passed, 'wins': wins, 'losses': losses, 'ties': ties,
                'typical_ratio_a_over_b': ratio, 'sign_test_p_value': p_value,
            }
            if a['harness'].startswith('amplifier'):
                if n_common_passed and ratio is not None:
                    sentence = (f"{a['label']} is faster on {wins} of {n_common_passed} shared tasks "
                                f"vs {b['label']}; typically {ratio:.2f}x the time; p={_fmt_p(p_value)}")
                else:
                    sentence = f"{a['label']} vs {b['label']}: no shared passing tasks to compare"
                sentences[a['label']].append(sentence)
    return {'pairs': pairs, 'sentences': dict(sentences)}


# --------------------------------------------------------------------------
# section 4: amplifier mechanism dimension
# --------------------------------------------------------------------------


def compute_mechanism(series):
    """None when this series isn't an amplifier-* harness; 'n/a' when it is
    but no run has receipts.jsonl; else a dict of receipt-derived sums."""
    if not series['harness'].startswith('amplifier'):
        return None

    any_receipts = False
    provider_requests_vals = []
    effort_by_phase = collections.defaultdict(collections.Counter)
    model_routed_total = 0
    escalated_total = 0
    escalation_reasons = collections.Counter()
    tasks_with_model_routed = set()
    tasks_escalated = set()
    bypassed_total = 0
    bypassed_known = False

    for task, info in series['tasks'].items():
        result = info['result']
        if result and result.get('provider_requests') is not None:
            provider_requests_vals.append(result['provider_requests'])

        receipts_path = info['run_dir'] / 'receipts.jsonl'
        if receipts_path.exists():
            any_receipts = True
            try:
                lines = receipts_path.read_text(encoding='utf-8').splitlines()
            except OSError:
                lines = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                event = ev.get('event')
                data = ev.get('data') or {}
                if event == 'fast_decisions:effort_routed':
                    phase = data.get('phase') or 'unspecified'
                    effort_label = data.get('requested_effort') or 'unspecified'
                    effort_by_phase[phase][effort_label] += 1
                elif event == 'fast_decisions:model_routed':
                    model_routed_total += 1
                    tasks_with_model_routed.add(task)
                    if data.get('escalated'):
                        escalated_total += 1
                        tasks_escalated.add(task)
                        escalation_reasons[data.get('escalation_reason') or 'unspecified'] += 1

        measurements_path = info['run_dir'] / 'measurements.json'
        if measurements_path.exists():
            try:
                m = json.loads(measurements_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                m = None
            if m is not None:
                bypassed = (m.get('totals') or {}).get('provider_calls_bypassed')
                if bypassed is not None:
                    bypassed_total += bypassed
                    bypassed_known = True

    if not any_receipts:
        return 'n/a'

    total_tasks = len(series['tasks'])
    return {
        'mean_provider_requests_per_task': _mean(provider_requests_vals),
        'effort_routed_by_phase': {phase: dict(counter) for phase, counter in effort_by_phase.items()},
        'model_routed_requests_total': model_routed_total,
        'model_routed_escalations_total': escalated_total,
        'escalation_reasons': dict(escalation_reasons),
        'tasks_with_model_routed': len(tasks_with_model_routed),
        'tasks_escalated': len(tasks_escalated),
        'share_of_tasks_escalated': (len(tasks_escalated) / total_tasks) if total_tasks else None,
        'provider_calls_bypassed_total': bypassed_total if bypassed_known else None,
    }


# --------------------------------------------------------------------------
# section 5: quality detail
# --------------------------------------------------------------------------


def compute_quality(series):
    label_counts = collections.Counter()
    failed_tasks = []
    for task, info in series['tasks'].items():
        result = info['result']
        if result is None:
            continue
        for lbl in (result.get('quality') or {}).get('failure_labels') or []:
            label_counts[lbl] += 1
        if not result.get('outcome_passed'):
            failed_tasks.append(task)
    return {'top_failure_labels': label_counts.most_common(5), 'failed_tasks': sorted(failed_tasks)}


# --------------------------------------------------------------------------
# section 6: evidence limits
# --------------------------------------------------------------------------


def compute_evidence_limits(all_series):
    retried = {}
    for s in all_series:
        n_retried = sum(1 for info in s['tasks'].values() if info['max_attempt'] > 1)
        if n_retried:
            retried[s['label']] = n_retried
    repetition = ('single repetition per task per harness (no retries observed)' if not retried
                  else 'retries observed: ' + '; '.join(f'{label} n={n}' for label, n in retried.items()))

    models_by_series = {}
    for s in all_series:
        vals = [info['result'].get('model') for info in s['tasks'].values()
                if info['result'] and info['result'].get('model')]
        if vals:
            mode_val, mode_n = collections.Counter(vals).most_common(1)[0]
            models_by_series[s['label']] = f'{mode_val} ({mode_n}/{len(vals)})'
        else:
            models_by_series[s['label']] = 'n/a'

    exec_time_source_mix = {}
    for s in all_series:
        vals = [info['result'].get('exec_time_source') or 'unknown'
                for info in s['tasks'].values() if info['result']]
        exec_time_source_mix[s['label']] = dict(collections.Counter(vals))

    distinct_roots = {s['root'] for s in all_series}
    contemporaneity = ('all series drawn from the same campaign root' if len(distinct_roots) <= 1
                        else 'series drawn from different campaign roots; '
                             'runs are non-contemporaneous across campaigns')

    task_counts_by_series = {s['label']: len(s['tasks']) for s in all_series}
    all_tasks = set()
    for s in all_series:
        all_tasks |= set(s['tasks'])

    return {
        'repetition': repetition,
        'models_by_series': models_by_series,
        'exec_time_source_mix': exec_time_source_mix,
        'contemporaneity': contemporaneity,
        'task_counts_by_series': task_counts_by_series,
        'total_distinct_tasks': len(all_tasks),
    }


# --------------------------------------------------------------------------
# report assembly + markdown rendering
# --------------------------------------------------------------------------


def _fmt(x, digits=2):
    return 'n/a' if x is None else f'{x:.{digits}f}'


def _fmt_p(p):
    return 'n/a' if p is None else f'{p:.4g}'


def build_report(series_specs, title=None, task_filter=None, family_map_pairs=None, exclude_startup=True):
    task_filter_re = re.compile(task_filter) if task_filter else None
    family_map = parse_family_map(family_map_pairs)

    all_series = []
    for spec in series_specs:
        label, root, experiment, harness = parse_series_spec(spec)
        all_series.append(load_series(label, root, experiment, harness, task_filter_re))

    report = {
        'title': title or 'Benchmark report',
        'options': {'task_filter': task_filter, 'exclude_startup': exclude_startup, 'family_map': family_map},
        'series': [{'label': s['label'], 'root': s['root'], 'experiment': s['experiment'], 'harness': s['harness']}
                   for s in all_series],
        'overview': {s['label']: compute_overview(s, exclude_startup) for s in all_series},
        'by_family': {s['label']: compute_family_table(s, family_map, exclude_startup) for s in all_series},
        'head_to_head': compute_head_to_head(all_series, exclude_startup),
        'mechanism': {s['label']: compute_mechanism(s) for s in all_series},
        'quality': {s['label']: compute_quality(s) for s in all_series},
        'evidence_limits': compute_evidence_limits(all_series),
    }
    return render_markdown(report), report


def render_markdown(report):
    lines = [f"# {report['title']}", '', '## Series', '']
    for s in report['series']:
        lines.append(f"- **{s['label']}**: `{s['root']}` experiment=`{s['experiment']}` harness=`{s['harness']}`")
    lines.append('')

    lines.append('## 1. Overview')
    lines.append('')
    lines.append('| Series | Attempted | Passed | Deadline failures | Median working time (s) | '
                  'Mean working time (s) | IQR (s) | Median time incl. startup (s) | Mean cost (USD) | '
                  'Infra retries |')
    lines.append('|---|---|---|---|---|---|---|---|---|---|')
    for label, row in report['overview'].items():
        lines.append(
            f"| {label} | {row['tasks_attempted']} | {row['passed']} | {row['deadline_failures']} | "
            f"{_fmt(row['median_working_time_s'])} | {_fmt(row['mean_working_time_s'])} | "
            f"{_fmt(row['iqr_working_time_s'])} | {_fmt(row['median_time_incl_startup_s'])} | "
            f"{_fmt(row['mean_cost_usd'], 4)} | {row['infrastructure_retries']} |"
        )
        notes = []
        if row['cost_not_billed_count']:
            notes.append(f"{row['cost_not_billed_count']} not billed")
        if row['cost_estimated_count']:
            notes.append(f"{row['cost_estimated_count']} estimated")
        if row['cost_unknown_count']:
            notes.append(f"{row['cost_unknown_count']} unknown")
        if notes:
            lines.append(f"  - {label} cost notes: " + ', '.join(notes))
    lines.append('')

    lines.append('## 2. By family / language')
    lines.append('')
    for label, families in report['by_family'].items():
        lines.append(f'### {label}')
        lines.append('')
        lines.append('| Family | Passed/Total | Median working time (s) |')
        lines.append('|---|---|---|')
        for family, row in sorted(families.items()):
            lines.append(f"| {family} | {row['passed']}/{row['n']} | {_fmt(row['median_working_time_s'])} |")
        lines.append('')

    lines.append('## 3. Head-to-head')
    lines.append('')
    lines.append('| A | B | Shared tasks | Common passed | Wins (A faster) | Losses | Ties | '
                  'Typical ratio (A/B) | p-value |')
    lines.append('|---|---|---|---|---|---|---|---|---|')
    for row in report['head_to_head']['pairs'].values():
        lines.append(
            f"| {row['a']} | {row['b']} | {row['n_shared_tasks']} | {row['n_common_passed']} | "
            f"{row['wins']} | {row['losses']} | {row['ties']} | "
            f"{_fmt(row['typical_ratio_a_over_b'])} | {_fmt_p(row['sign_test_p_value'])} |"
        )
    lines.append('')
    for sentences in report['head_to_head']['sentences'].values():
        for sentence in sentences:
            lines.append(f'- {sentence}')
    lines.append('')

    lines.append('## 4. Amplifier mechanism dimension')
    lines.append('')
    for label, mech in report['mechanism'].items():
        lines.append(f'### {label}')
        lines.append('')
        if mech is None:
            lines.append('n/a (not an amplifier series)')
        elif mech == 'n/a':
            lines.append('n/a (no receipts found)')
        else:
            lines.append(f"- Mean provider requests per task: {_fmt(mech['mean_provider_requests_per_task'])}")
            lines.append(f"- Model-routed requests (total): {mech['model_routed_requests_total']}")
            lines.append(f"- Model-routed escalations (total): {mech['model_routed_escalations_total']}")
            lines.append(f"- Tasks with any model routing: {mech['tasks_with_model_routed']}")
            lines.append(f"- Tasks escalated: {mech['tasks_escalated']} "
                         f"(share={_fmt(mech['share_of_tasks_escalated'])})")
            bypassed = mech['provider_calls_bypassed_total']
            lines.append(f"- Provider calls bypassed (total): {bypassed if bypassed is not None else 'n/a'}")
            if mech['escalation_reasons']:
                lines.append(f"- Escalation reasons: {mech['escalation_reasons']}")
            if mech['effort_routed_by_phase']:
                lines.append(f"- Effort routed by phase: {mech['effort_routed_by_phase']}")
        lines.append('')

    lines.append('## 5. Quality detail')
    lines.append('')
    for label, q in report['quality'].items():
        lines.append(f'### {label}')
        lines.append('')
        lines.append('Top failure labels: ' + (
            ', '.join(f'{lbl} ({n})' for lbl, n in q['top_failure_labels']) if q['top_failure_labels'] else 'none'
        ))
        lines.append('Failed tasks: ' + (', '.join(q['failed_tasks']) if q['failed_tasks'] else 'none'))
        lines.append('')

    lines.append('## 6. Evidence limits')
    lines.append('')
    el = report['evidence_limits']
    lines.append(f"- {el['repetition']}")
    lines.append(f"- {el['contemporaneity']}")
    lines.append(f"- Task counts by series: {el['task_counts_by_series']}")
    lines.append(f"- Total distinct tasks across all series: {el['total_distinct_tasks']}")
    lines.append(f"- Models by series: {el['models_by_series']}")
    lines.append(f"- exec_time_source mix by series: {el['exec_time_source_mix']}")
    lines.append('')

    return '\n'.join(lines) + '\n'


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', required=True, help='Output directory for report.md/report.json')
    parser.add_argument('--series', action='append', required=True,
                         help='label=campaign_root:experiment:harness (repeatable, one per column/row)')
    parser.add_argument('--title', help='Report title')
    parser.add_argument('--task-filter', help='Regex filter applied to task names (keep only matches)')
    parser.add_argument('--family-map', action='append',
                         help='family=Label rename for the by-family table (repeatable)')
    parser.add_argument('--exclude-startup', action=argparse.BooleanOptionalAction, default=True,
                         help='Use exec_time_ms, falling back to wall_time_ms (default: on).')
    args = parser.parse_args(argv)

    markdown, report = build_report(
        args.series, title=args.title, task_filter=args.task_filter,
        family_map_pairs=args.family_map, exclude_startup=args.exclude_startup,
    )

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    report_md_path = out_dir / 'report.md'
    report_json_path = out_dir / 'report.json'
    report_md_path.write_text(markdown, encoding='utf-8')
    report_json_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    print(json.dumps({'report_md': str(report_md_path), 'report_json': str(report_json_path)}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
