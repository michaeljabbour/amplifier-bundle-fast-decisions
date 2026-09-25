"""Tests for scripts/campaign.py -- the resumable hill-climb campaign runner.

Stdlib unittest only. Builds tiny throwaway git repos under tempdirs; never
touches the network or a real Amplifier install. Every environment-probing
helper in campaign.cmd_init (subprocess/network calls) is patched out so
these tests are fully hermetic.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import campaign  # noqa: E402


EVALUATOR_SOURCE = "EVAL = 'v1'\n"


def _git(cwd, *args):
    subprocess.run(['git', *args], cwd=str(cwd), check=True, capture_output=True, text=True)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    _git(path, 'init', '-q')
    _git(path, 'config', 'user.email', 'test@example.com')
    _git(path, 'config', 'user.name', 'Test')
    _git(path, 'config', 'commit.gpgsign', 'false')


def _write_pkg(repo, content, evaluator=EVALUATOR_SOURCE):
    pkg = repo/'src'/'amplifier_fast_decisions'
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg/'mod.py').write_text(content)
    (repo/'scripts').mkdir(parents=True, exist_ok=True)
    (repo/'scripts'/'forge_workloads.py').write_text(evaluator)


def _commit_all(path, message):
    _git(path, 'add', '-A')
    _git(path, 'commit', '-q', '-m', message)
    out = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(path), capture_output=True, text=True, check=True)
    return out.stdout.strip()


def _build_sources(base):
    baseline = base/'baseline'
    _init_repo(baseline)
    _write_pkg(baseline, 'X = 1\n')
    _commit_all(baseline, 'init')

    candidate = base/'candidate'
    _init_repo(candidate)
    _write_pkg(candidate, 'X = 1\n')
    sha_a = _commit_all(candidate, 'a')
    _write_pkg(candidate, 'X = 2\n')
    sha_b = _commit_all(candidate, 'b')

    cache = base/'cache'
    _init_repo(cache)
    _write_pkg(cache, 'X = 0\n')
    _commit_all(cache, 'cache')

    return {'baseline': baseline, 'candidate': candidate, 'sha_a': sha_a, 'sha_b': sha_b, 'cache': cache}


def _hermetic_init(args):
    with patch.object(campaign, '_ollama_tags', return_value=[]), \
         patch.object(campaign, '_try_run', return_value={'stub': True}), \
         patch.object(campaign, '_uv_pip_list', return_value=[]), \
         patch.object(campaign, '_provider_summaries', return_value=[]):
        campaign.cmd_init(args)


def _init_campaign(base, proposal_extra=None):
    src = _build_sources(base)
    root = base/'campaign'
    proposal = {'campaign_name': 'camp', **(proposal_extra or {})}
    proposal_path = base/'proposal.json'
    proposal_path.write_text(json.dumps(proposal))
    args = SimpleNamespace(root=str(root), proposal=str(proposal_path), baseline_source=str(src['baseline']),
                            candidate_worktree=str(src['candidate']), installed_cache=str(src['cache']),
                            evidence_root=None, history_index=str(base/'history.json'),
                            host_python=sys.executable, events_dir=str(base/'events'))
    _hermetic_init(args)
    return root, src


def _prereg_args(root, src, experiment, tasks, reps=1, seed=1, candidate_sha=None, decision_override=None):
    return SimpleNamespace(root=str(root), experiment=experiment, backlog='b1', hypothesis='h', mechanism='m',
                            one_change='oc', candidate_worktree=str(src['candidate']),
                            candidate_sha=candidate_sha or src['sha_b'], tasks=tasks, reps=reps, tier='screen',
                            seed=seed, decision_override=decision_override, falsification=None,
                            baseline_source=None, mechanism_check=None)


class InitTests(unittest.TestCase):
    def test_layout_permissions_evaluator_sha_and_reinit_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base)
            self.assertTrue((root/'campaign.json').exists())
            for sub in ['experiments', 'tasks', 'history', 'reports', 'handoff']:
                self.assertTrue((root/sub).is_dir())
            self.assertEqual(stat.S_IMODE(os.stat(root).st_mode), 0o700)

            protocol = json.loads((root/'protocol.json').read_text())
            expected_sha = hashlib.sha256((src['candidate']/'scripts'/'forge_workloads.py').read_bytes()).hexdigest()
            self.assertEqual(protocol['evaluator']['sha256'], expected_sha)
            self.assertEqual(protocol['schema_version'], 'fast-decisions-protocol/v1')

            args = SimpleNamespace(root=str(root), proposal=str(base/'proposal.json'), baseline_source=str(src['baseline']),
                                    candidate_worktree=str(src['candidate']), installed_cache=str(src['cache']),
                                    evidence_root=None, history_index=str(base/'history.json'),
                                    host_python=sys.executable, events_dir=str(base/'events'))
            with self.assertRaises(SystemExit) as ctx:
                _hermetic_init(args)
            self.assertEqual(ctx.exception.code, 4)


class BudgetTests(unittest.TestCase):
    def test_reserve_allows_within_cap_and_refuses_over(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, _src = _init_campaign(base, {'budgets': {'estimated_total_usd': 20.0}})
            campaign.cmd_budget_reserve(SimpleNamespace(root=str(root), usd=15.0, purpose='p1'))
            with self.assertRaises(SystemExit) as ctx:
                campaign.cmd_budget_reserve(SimpleNamespace(root=str(root), usd=10.0, purpose='p2'))
            self.assertEqual(ctx.exception.code, 3)

    def test_unknown_settlement_counts_reserved_amount_and_supervisor_observation_latest_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, _src = _init_campaign(base, {'budgets': {'estimated_total_usd': 50.0}})
            campaign.cmd_budget_reserve(SimpleNamespace(root=str(root), usd=10.0, purpose='p'))
            rid = campaign._ledger_lines(root)[-1]['id']
            campaign.cmd_budget_settle(SimpleNamespace(root=str(root), reservation=rid, actual_usd=None, unknown=True))
            totals = campaign._budget_totals(root)
            self.assertEqual(totals['unknown_spend'], 10.0)
            self.assertEqual(totals['settled_benchmark'], 0.0)

            session_dir = base/'sessions'/'root'
            session_dir.mkdir(parents=True)
            (session_dir/'metadata.json').write_text(json.dumps({'id': 'root'}))
            (session_dir/'events.jsonl').write_text(
                json.dumps({'event': 'llm:response', 'data': {'usage': {'cost_usd': 1.5}}})+'\n'
                + json.dumps({'event': 'llm:response', 'data': {'usage': {}}})+'\n')
            campaign.cmd_budget_observe_supervisor(SimpleNamespace(root=str(root), session_dir=str(session_dir)))
            totals2 = campaign._budget_totals(root)
            self.assertEqual(totals2['supervisor_usd'], 1.5)
            status = campaign._budget_status_dict(root)
            self.assertEqual(status['cap'], 50.0)


class PreregisterTests(unittest.TestCase):
    def test_frozen_schedule_deterministic_and_covers_both_sides_per_task_rep(self):
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            base1, base2 = Path(tmp1), Path(tmp2)
            root1, src1 = _init_campaign(base1)
            root2, src2 = _init_campaign(base2)
            campaign.cmd_preregister(_prereg_args(root1, src1, 'e1', 'scheduler,reconciler', reps=2, seed=42))
            campaign.cmd_preregister(_prereg_args(root2, src2, 'e1', 'scheduler,reconciler', reps=2, seed=42))
            proposal1 = json.loads((root1/'experiments'/'e1'/'proposal.json').read_text())
            proposal2 = json.loads((root2/'experiments'/'e1'/'proposal.json').read_text())
            names1 = [r['name'] for r in proposal1['frozen_run_schedule']]
            names2 = [r['name'] for r in proposal2['frozen_run_schedule']]
            self.assertEqual(names1, names2)
            self.assertTrue(names1)

            sides_per_task_rep = {}
            for r in proposal1['frozen_run_schedule']:
                sides_per_task_rep.setdefault((r['task'], r['rep']), set()).add(r['side'])
            for key, sides in sides_per_task_rep.items():
                self.assertEqual(sides, {'baseline', 'candidate'}, key)

    def test_refuses_ninth_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {'budgets': {'max_candidates': 8}})
            for i in range(8):
                exp = root/'experiments'/f'x{i}'
                exp.mkdir(parents=True)
                (exp/'proposal.json').write_text('{}')
            with self.assertRaises(SystemExit) as ctx:
                campaign.cmd_preregister(_prereg_args(root, src, 'e9', 'scheduler', reps=1, seed=1))
            self.assertEqual(ctx.exception.code, 4)

    def test_evaluator_drift_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base)
            (src['candidate']/'scripts'/'forge_workloads.py').write_text("EVAL = 'v2'\n")
            sha_c = _commit_all(src['candidate'], 'drift')
            with self.assertRaises(SystemExit) as ctx:
                campaign.cmd_preregister(_prereg_args(root, src, 'edrift', 'scheduler', reps=1, seed=1, candidate_sha=sha_c))
            self.assertEqual(ctx.exception.code, 4)


class RunTests(unittest.TestCase):
    def _success_result(self, cost=0.1):
        return json.dumps({'outcome_passed': True, 'infrastructure_failure': False, 'timed_out': False,
                           'wall_time_ms': 500.0, 'native': {'usage': {'cost_usd': cost}}})

    def test_skips_completed_runs(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {'budgets': {'estimated_total_usd': 1000.0, 'per_launch_usd': 1.0}})
            campaign.cmd_preregister(_prereg_args(root, src, 'run1', 'scheduler', reps=1, seed=7))
            runs_root = root/'experiments'/'run1'/'runs'
            manifest = json.loads((runs_root/'manifest.json').read_text())
            name0 = manifest['run_order'][0]
            (runs_root/name0/'result.json').write_text(self._success_result())

            launched = []

            def fake_launcher(rr, name):
                launched.append(name)

            def fake_waiter(rr, name, timeout):
                (rr/name/'result.json').write_text(self._success_result())
                return True

            campaign.cmd_run(SimpleNamespace(root=str(root), experiment='run1'), launcher=fake_launcher, waiter=fake_waiter)
            self.assertNotIn(name0, launched)
            self.assertEqual(len(launched), 1)

    def test_adopts_live_pid_and_retries_dead_pid_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {'budgets': {'estimated_total_usd': 1000.0, 'per_launch_usd': 1.0}})
            campaign.cmd_preregister(_prereg_args(root, src, 'run1', 'scheduler', reps=1, seed=7))
            runs_root = root/'experiments'/'run1'/'runs'
            manifest = json.loads((runs_root/'manifest.json').read_text())
            names = manifest['run_order']
            self.assertEqual(len(names), 2)
            live_name, dead_name = names[0], names[1]
            (runs_root/live_name/'running.json').write_text(json.dumps({'controller_pid': os.getpid()}))
            (runs_root/dead_name/'running.json').write_text(json.dumps({'controller_pid': 999999}))

            launched = []
            waited = []

            def fake_launcher(rr, name):
                launched.append(name)

            def fake_waiter(rr, name, timeout):
                waited.append(name)
                if name == dead_name:
                    return False
                (rr/name/'result.json').write_text(self._success_result())
                return True

            campaign.cmd_run(SimpleNamespace(root=str(root), experiment='run1'), launcher=fake_launcher, waiter=fake_waiter)

            manifest_after = json.loads((runs_root/'manifest.json').read_text())
            retried = [n for n in manifest_after['run_order'] if n not in names]
            self.assertEqual(len(retried), 1)
            self.assertTrue(retried[0].endswith('-a2'))
            self.assertNotIn(live_name, launched)
            self.assertIn(dead_name, launched)
            self.assertIn(retried[0], launched)
            ledger = campaign._ledger_lines(root)
            self.assertEqual(sum(1 for e in ledger if e.get('type') == 'infrastructure_retry_scheduled'), 1)
            self.assertEqual(sum(1 for e in ledger if e.get('type') == 'adopted_live_worker'), 1)

    def test_stops_at_max_launches(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {'budgets': {'estimated_total_usd': 1000.0, 'per_launch_usd': 1.0,
                                                          'max_benchmark_worker_launches': 1}})
            campaign.cmd_preregister(_prereg_args(root, src, 'run1', 'scheduler,reconciler', reps=1, seed=7))

            def fake_launcher(rr, name):
                pass

            def fake_waiter(rr, name, timeout):
                (rr/name/'result.json').write_text(self._success_result())
                return True

            with self.assertRaises(SystemExit) as ctx:
                campaign.cmd_run(SimpleNamespace(root=str(root), experiment='run1'), launcher=fake_launcher, waiter=fake_waiter)
            self.assertEqual(ctx.exception.code, 3)
            ledger = campaign._ledger_lines(root)
            self.assertTrue(any(e.get('type') == 'paused' and e.get('reason') == 'launch_cap' for e in ledger))

    def test_stops_on_budget_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {'budgets': {'estimated_total_usd': 1.05, 'per_launch_usd': 1.0}})
            campaign.cmd_preregister(_prereg_args(root, src, 'run1', 'scheduler,reconciler', reps=1, seed=7))

            def fake_launcher(rr, name):
                pass

            def fake_waiter(rr, name, timeout):
                (rr/name/'result.json').write_text(self._success_result(cost=0.1))
                return True

            with self.assertRaises(SystemExit) as ctx:
                campaign.cmd_run(SimpleNamespace(root=str(root), experiment='run1'), launcher=fake_launcher, waiter=fake_waiter)
            self.assertEqual(ctx.exception.code, 3)
            ledger = campaign._ledger_lines(root)
            self.assertTrue(any(e.get('type') == 'paused' and e.get('reason') == 'budget' for e in ledger))
            self.assertEqual(sum(1 for e in ledger if e.get('type') == 'run_launched'), 1)


class EvaluateTests(unittest.TestCase):
    def _write_result(self, runs_root, name, **overrides):
        base = {'outcome_passed': True, 'timed_out': False, 'wall_time_ms': 1000.0,
                'infrastructure_failure': False, 'source_match': True,
                'native': {'usage': {'cost_usd': 1.0}},
                'protected_files_unchanged': {'README.md': True, 'test_public.py': True}}
        base.update(overrides)
        (runs_root/name/'result.json').write_text(json.dumps(base))

    def test_penalized_deadline_for_failures_and_new_failure_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {'evaluation': {'deadline_seconds': 100}})
            campaign.cmd_preregister(_prereg_args(root, src, 'e1', 'scheduler,reconciler,event_reducer', reps=1, seed=3))
            runs_root = root/'experiments'/'e1'/'runs'
            manifest = json.loads((runs_root/'manifest.json').read_text())
            for name, item in manifest['runs'].items():
                if item['side'] == 'baseline':
                    self._write_result(runs_root, name, wall_time_ms=1000.0)
                elif item['task'] == 'scheduler':
                    self._write_result(runs_root, name, outcome_passed=False, timed_out=True, wall_time_ms=99000.0)
                else:
                    self._write_result(runs_root, name, wall_time_ms=500.0)
            campaign.cmd_evaluate(SimpleNamespace(root=str(root), experiment='e1', tier='screen'))
            comparison = json.loads((root/'experiments'/'e1'/'comparison.json').read_text())
            self.assertEqual(comparison['per_task']['scheduler']['candidate_penalized_ms_mean'], 100*1000)
            self.assertIsNotNone(comparison['primary']['point'])
            decision = json.loads((root/'experiments'/'e1'/'decision.json').read_text())
            self.assertEqual(decision['decision'], 'reject')
            self.assertEqual(decision['gates']['G1'], 'fail')

    def test_ci_not_estimable_with_two_task_clusters(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {'evaluation': {'deadline_seconds': 200}})
            campaign.cmd_preregister(_prereg_args(root, src, 'e2', 'scheduler,reconciler', reps=1, seed=5))
            runs_root = root/'experiments'/'e2'/'runs'
            manifest = json.loads((runs_root/'manifest.json').read_text())
            for name, item in manifest['runs'].items():
                ms = 1000.0 if item['side'] == 'baseline' else 800.0
                self._write_result(runs_root, name, wall_time_ms=ms)
            campaign.cmd_evaluate(SimpleNamespace(root=str(root), experiment='e2', tier='screen'))
            comparison = json.loads((root/'experiments'/'e2'/'comparison.json').read_text())
            self.assertIsNone(comparison['primary']['ci95'])
            self.assertEqual(comparison['primary']['ci95_reason'], 'not_estimable_fewer_than_3_task_clusters')
            decision = json.loads((root/'experiments'/'e2'/'decision.json').read_text())
            self.assertEqual(decision['decision'], 'keep_as_experimental_incumbent')

    def test_secondary_none_when_cost_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {'evaluation': {'deadline_seconds': 200}})
            campaign.cmd_preregister(_prereg_args(root, src, 'e3', 'scheduler,reconciler,event_reducer', reps=1, seed=9))
            runs_root = root/'experiments'/'e3'/'runs'
            manifest = json.loads((runs_root/'manifest.json').read_text())
            for name, item in manifest['runs'].items():
                self._write_result(runs_root, name, wall_time_ms=900.0, native={'usage': {'cost_usd': None}})
            campaign.cmd_evaluate(SimpleNamespace(root=str(root), experiment='e3', tier='screen'))
            comparison = json.loads((root/'experiments'/'e3'/'comparison.json').read_text())
            self.assertIsNone(comparison['secondary']['point'])

    def test_mechanism_counts_zero_observation_abstention_and_fast_tool_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {'evaluation': {'deadline_seconds': 200}})
            campaign.cmd_preregister(_prereg_args(root, src, 'e4', 'scheduler,reconciler,event_reducer', reps=1, seed=11))
            runs_root = root/'experiments'/'e4'/'runs'
            manifest = json.loads((runs_root/'manifest.json').read_text())
            candidate_name = None
            for name, item in manifest['runs'].items():
                self._write_result(runs_root, name, wall_time_ms=900.0)
                if item['side'] == 'candidate' and candidate_name is None:
                    candidate_name = name
            self.assertIsNotNone(candidate_name)
            receipts = [
                {'event': 'fast_decisions:requested', 'decision_id': 'd1', 'timestamp': '2026-09-18T00:00:00',
                 'data': {'observation_count': 0, 'truncation_reason': 'budget'}},
                {'event': 'fast_decisions:requested', 'decision_id': 'd2', 'timestamp': '2026-09-18T00:00:01',
                 'data': {'observation_count': 3, 'truncation_reason': 'none'}},
                {'event': 'fast_decisions:scored', 'decision_id': 'd1', 'timestamp': '2026-09-18T00:00:02',
                 'data': {'choice': 'read_x'}},
                {'event': 'fast_decisions:routed', 'decision_id': 'd1', 'timestamp': '2026-09-18T00:00:02',
                 'data': {'route': 'slow', 'reason_code': 'model_abstained'}},
                {'event': 'fast_decisions:tool_end', 'decision_id': 'd1', 'timestamp': '2026-09-18T00:00:03',
                 'data': {'success': True}},
            ]
            receipts_path = runs_root/candidate_name/'receipts.jsonl'
            receipts_path.write_text('\n'.join(json.dumps(e) for e in receipts) + '\n')
            campaign.cmd_evaluate(SimpleNamespace(root=str(root), experiment='e4', tier='screen'))
            comparison = json.loads((root/'experiments'/'e4'/'comparison.json').read_text())
            mechanism = comparison['mechanism']
            self.assertEqual(mechanism['zero_observation_requests'], 1)
            self.assertEqual(mechanism['requests_with_observation_stats'], 2)
            self.assertEqual(mechanism['truncation_reasons'], {'budget': 1, 'none': 1})
            self.assertEqual(mechanism['scored_abstained'], 1)
            self.assertEqual(mechanism['fast_tool_end_success'], 1)


class CheckpointTests(unittest.TestCase):
    def test_atomic_write_and_report_headings_and_handoff_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, _src = _init_campaign(base)
            checkpoint = campaign._write_checkpoint(root, bottleneck='decision latency', next_experiment='next-1')
            self.assertTrue((root/'checkpoint.json').exists())
            self.assertEqual(checkpoint['bottleneck'], 'decision latency')
            self.assertEqual(checkpoint['next_experiment'], 'next-1')

            latest = (root/'reports'/'LATEST.md').read_text()
            for heading in ['## Revisions', '## Current bottleneck', '## Experiments completed',
                            '## Measured gains and quality', '## Spend and reservations',
                            '## Remaining budget', '## Next experiment', '## Evidence limits']:
                self.assertIn(heading, latest)

            continue_md = (root/'handoff'/'CONTINUE.md').read_text()
            self.assertIn(str(root), continue_md)
            self.assertIn('next-1', continue_md)




class LaunchFailureTests(unittest.TestCase):
    def test_launch_exception_settles_zero_and_retries_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root, src = _init_campaign(base, {})
            campaign.cmd_preregister(_prereg_args(root, src, 'lf', 'scheduler', reps=1, seed=3))
            runs_root = root/'experiments'/'lf'/'runs'
            calls = []
            def _write_fake_result(rr, name):
                (rr/name).mkdir(parents=True, exist_ok=True)
                (rr/name/'result.json').write_text(json.dumps({
                    'name': name, 'outcome_passed': True, 'timed_out': False, 'wall_time_ms': 1000.0,
                    'native': {'usage': {'cost_usd': 0.5}}, 'quality': {'checks': 1, 'passed': 1, 'failed': 0, 'failure_labels': []},
                    'protected_files_unchanged': {'README.md': True}, 'source_match': True, 'mode_match': True,
                    'infrastructure_failure': False, 'attempt': 2 if name.endswith('-a2') else 1}))
            def launcher(rr, name):
                calls.append(name)
                if name.endswith('-a1') and 'baseline' in name:
                    raise RuntimeError('forge launch failed: Maximum sessions (10) reached')
                _write_fake_result(rr, name)
            def waiter(rr, name, timeout):
                return (rr/name/'result.json').exists()
            campaign.cmd_run(SimpleNamespace(root=str(root), experiment='lf'), launcher=launcher, waiter=waiter, closer=lambda rr, n: None)
            ledger = [json.loads(l) for l in (root/'ledger.jsonl').read_text().splitlines()]
            failed = [e for e in ledger if e['type'] == 'launch_failed']
            self.assertEqual(len(failed), 1)
            zero = [e for e in ledger if e['type'] == 'settlement' and e.get('actual_usd') == 0.0]
            self.assertEqual(len(zero), 1)
            self.assertTrue(any(n.endswith('baseline-a2') for n in calls), calls)
            self.assertTrue((runs_root/[n for n in calls if n.endswith('baseline-a2')][0]/'result.json').exists())


class SupervisorOffsetTests(unittest.TestCase):
    def test_supervisor_offset_is_subtracted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root, _ = _init_campaign(Path(tmp), {})
            campaign._ledger_append(root, {'type': 'supervisor_offset', 'usd': 40.0})
            campaign._ledger_append(root, {'type': 'supervisor_observation', 'usd': 55.0})
            totals = campaign._budget_totals(root)
            self.assertAlmostEqual(totals['supervisor_usd'], 15.0)
            self.assertAlmostEqual(totals['supervisor_offset'], 40.0)

if __name__ == '__main__':
    unittest.main()
