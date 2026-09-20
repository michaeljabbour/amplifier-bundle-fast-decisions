"""Tests for scripts/battery_report.py -- the multidimensional benchmark report tool.

Stdlib unittest only. Builds two synthetic fake campaign roots (temp dirs) with
manifest.json + result.json files (plus receipts.jsonl/measurements.json for
the amplifier-fd series) and exercises battery_report.py entirely against
those fixtures. Never reads real campaign data, never invokes an LLM/harness.
"""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import battery_report as br  # noqa: E402


def _write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _base_result(**overrides):
    result = {
        'task': None, 'family': None, 'split': 'dev', 'kind': 'code',
        'harness': None, 'model': None,
        'wall_time_ms': None, 'exec_time_ms': None, 'exec_time_source': 'unknown',
        'cost_usd': None, 'cost_billable': None, 'cost_source': 'unknown',
        'timed_out': False, 'outcome_passed': True, 'infrastructure_failure': False,
        'quality': {'checks': 1, 'passed': 1, 'failed': 0, 'failure_labels': []},
        'notes': [],
    }
    result.update(overrides)
    return result


class BuildFixturesMixin(unittest.TestCase):
    """Builds rootA (experiment EXPA: codex + amplifier-fd, 3 tasks) and
    rootB (experiment EXPB: opencode, 2 tasks) once per test."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root_a = Path(self._tmp.name) / 'campaign-a'
        self.root_b = Path(self._tmp.name) / 'campaign-b'
        self._build_root_a()
        self._build_root_b()

    # -- rootA: codex + amplifier-fd, tasks t1 (repair), t2 (repair), t3 (edit) --
    def _build_root_a(self):
        exp_dir = self.root_a / 'experiments' / 'EXPA'
        runs_root = exp_dir / 'runs'

        manifest_runs = {
            'EXPA-t1-codex-a1': {'task': 't1', 'harness': 'codex', 'attempt': 1},
            'EXPA-t2-codex-a1': {'task': 't2', 'harness': 'codex', 'attempt': 1},
            'EXPA-t3-codex-a1': {'task': 't3', 'harness': 'codex', 'attempt': 1},
            'EXPA-t1-amplifier-fd-a1': {'task': 't1', 'harness': 'amplifier-fd', 'attempt': 1},
            # t2/amplifier-fd: attempt 1 was an infrastructure failure (no result.json),
            # attempt 2 has the real result -- exercises the "latest attempt wins" +
            # infra-retry-counting logic.
            'EXPA-t2-amplifier-fd-a1': {'task': 't2', 'harness': 'amplifier-fd', 'attempt': 1},
            'EXPA-t2-amplifier-fd-a2': {'task': 't2', 'harness': 'amplifier-fd', 'attempt': 2},
            'EXPA-t3-amplifier-fd-a1': {'task': 't3', 'harness': 'amplifier-fd', 'attempt': 1},
        }
        _write_json(runs_root / 'manifest.json', {
            'schema': 'fast-decisions-battery/v1',
            'run_order': list(manifest_runs),
            'runs': manifest_runs,
            'deadline_seconds': 600,
            'prompt': 'do the task',
        })

        # codex results
        _write_json(runs_root / 'EXPA-t1-codex-a1' / 'result.json', _base_result(
            task='t1', family='repair', harness='codex', model='gpt-6-astra',
            wall_time_ms=15000.0, exec_time_ms=10000.0, exec_time_source='harness_duration_ms',
            cost_usd=1.0, cost_billable=True, cost_source='computed_from_tokens_estimate',
        ))
        _write_json(runs_root / 'EXPA-t2-codex-a1' / 'result.json', _base_result(
            task='t2', family='repair', harness='codex', model='gpt-6-astra',
            wall_time_ms=25000.0, exec_time_ms=20000.0, exec_time_source='harness_duration_ms',
            cost_usd=2.0, cost_billable=True, cost_source='harness_reported',
        ))
        _write_json(runs_root / 'EXPA-t3-codex-a1' / 'result.json', _base_result(
            task='t3', family='edit', harness='codex', model='gpt-6-astra',
            wall_time_ms=5000.0, exec_time_ms=None, exec_time_source='wall_includes_startup',
            cost_usd=None, cost_billable=None, cost_source='unknown',
            timed_out=True, outcome_passed=False,
            quality={'checks': 1, 'passed': 0, 'failed': 1, 'failure_labels': ['syntax_error']},
        ))

        # amplifier-fd results (t2 attempt 1 has NO result.json -- infra failure)
        amp_root = runs_root / 'amplifier'
        _write_json(amp_root / 'EXPA-t1-amplifier-fd-a1' / 'result.json', _base_result(
            task='t1', family='repair', harness='amplifier-fd', model='claude-sonnet-5',
            wall_time_ms=12000.0, exec_time_ms=8000.0,
            exec_time_source='native_events_first_request_to_last_response',
            cost_usd=0.5, cost_billable=True, cost_source='harness_reported',
            provider_requests=4,
        ))
        _write_json(amp_root / 'EXPA-t2-amplifier-fd-a2' / 'result.json', _base_result(
            task='t2', family='repair', harness='amplifier-fd', model='claude-sonnet-5',
            wall_time_ms=22000.0, exec_time_ms=18000.0,
            exec_time_source='native_events_first_request_to_last_response',
            cost_usd=0.7, cost_billable=True, cost_source='harness_reported',
            provider_requests=6,
        ))
        _write_json(amp_root / 'EXPA-t3-amplifier-fd-a1' / 'result.json', _base_result(
            task='t3', family='edit', harness='amplifier-fd', model='claude-sonnet-5',
            wall_time_ms=9000.0, exec_time_ms=4000.0,
            exec_time_source='native_events_first_request_to_last_response',
            cost_usd=0.3, cost_billable=True, cost_source='harness_reported',
            provider_requests=5,
        ))

        # receipts.jsonl for the three amplifier-fd run dirs actually used
        def _ev(event, data, seq):
            return json.dumps({
                'event': event, 'event_id': f'e{seq}', 'session_id': 's1',
                'parent_session_id': None, 'turn_id': 't', 'decision_id': f'd{seq}',
                'timestamp': '2026-09-19T00:00:00+00:00', 'seq': seq, 'synthetic': False,
                'data': data,
            })

        t1_receipts = '\n'.join([
            _ev('fast_decisions:effort_routed',
                {'phase': 'orient', 'requested_effort': None}, 1),
            _ev('fast_decisions:effort_routed',
                {'phase': 'explore', 'requested_effort': 'low'}, 2),
            _ev('fast_decisions:model_routed',
                {'phase': 'orient', 'requested_model': 'claude-sonnet-5', 'escalated': False,
                 'escalation_reason': None}, 3),
            _ev('fast_decisions:model_routed',
                {'phase': 'implement', 'requested_model': 'claude-sonnet-5', 'escalated': True,
                 'escalation_reason': 'timeout_risk'}, 4),
        ]) + '\n'
        _write_text(amp_root / 'EXPA-t1-amplifier-fd-a1' / 'receipts.jsonl', t1_receipts)
        _write_json(amp_root / 'EXPA-t1-amplifier-fd-a1' / 'measurements.json',
                     {'totals': {'provider_calls_bypassed': 2}})

        t2_receipts = '\n'.join([
            _ev('fast_decisions:effort_routed',
                {'phase': 'orient', 'requested_effort': 'medium'}, 1),
            _ev('fast_decisions:model_routed',
                {'phase': 'orient', 'requested_model': 'claude-sonnet-5', 'escalated': False,
                 'escalation_reason': None}, 2),
        ]) + '\n'
        _write_text(amp_root / 'EXPA-t2-amplifier-fd-a2' / 'receipts.jsonl', t2_receipts)
        _write_json(amp_root / 'EXPA-t2-amplifier-fd-a2' / 'measurements.json',
                     {'totals': {'provider_calls_bypassed': 1}})

        t3_receipts = '\n'.join([
            _ev('fast_decisions:effort_routed',
                {'phase': 'explore', 'requested_effort': 'low'}, 1),
            _ev('fast_decisions:effort_routed',
                {'phase': 'explore', 'requested_effort': 'low'}, 2),
        ]) + '\n'
        _write_text(amp_root / 'EXPA-t3-amplifier-fd-a1' / 'receipts.jsonl', t3_receipts)
        _write_json(amp_root / 'EXPA-t3-amplifier-fd-a1' / 'measurements.json',
                     {'totals': {'provider_calls_bypassed': 0}})

    # -- rootB: opencode, tasks t1 (repair), t2 (repair) only --
    def _build_root_b(self):
        exp_dir = self.root_b / 'experiments' / 'EXPB'
        runs_root = exp_dir / 'runs'
        manifest_runs = {
            'EXPB-t1-opencode-a1': {'task': 't1', 'harness': 'opencode', 'attempt': 1},
            'EXPB-t2-opencode-a1': {'task': 't2', 'harness': 'opencode', 'attempt': 1},
        }
        _write_json(runs_root / 'manifest.json', {
            'schema': 'fast-decisions-battery/v1',
            'run_order': list(manifest_runs),
            'runs': manifest_runs,
            'deadline_seconds': 600,
            'prompt': 'do the task',
        })
        _write_json(runs_root / 'EXPB-t1-opencode-a1' / 'result.json', _base_result(
            task='t1', family='repair', harness='opencode', model='glm-5.3',
            wall_time_ms=9000.0, exec_time_ms=None, exec_time_source='wall_includes_startup',
            cost_usd=1.5, cost_billable=True, cost_source='unknown',
        ))
        _write_json(runs_root / 'EXPB-t2-opencode-a1' / 'result.json', _base_result(
            task='t2', family='repair', harness='opencode', model='glm-5.3',
            wall_time_ms=21000.0, exec_time_ms=16000.0, exec_time_source='harness_event_timestamps',
            cost_usd=None, cost_billable=None, cost_source='unknown',
        ))

    def _series_specs(self):
        return [
            f'Codex={self.root_a}:EXPA:codex',
            f'FD={self.root_a}:EXPA:amplifier-fd',
            f'OpenCode={self.root_b}:EXPB:opencode',
        ]


class ParseSeriesSpecTests(unittest.TestCase):
    def test_basic(self):
        label, root, experiment, harness = br.parse_series_spec('Codex=/a/b/c:BASE:codex')
        self.assertEqual((label, root, experiment, harness), ('Codex', '/a/b/c', 'BASE', 'codex'))

    def test_root_with_colon_tolerated_by_rsplit(self):
        # rsplit(':', 2) means only the trailing two fields are peeled off the root.
        label, root, experiment, harness = br.parse_series_spec('X=/a:weird:root:EXP:harness')
        self.assertEqual(root, '/a:weird:root')
        self.assertEqual(experiment, 'EXP')
        self.assertEqual(harness, 'harness')

    def test_missing_equals_raises(self):
        with self.assertRaises(ValueError):
            br.parse_series_spec('no-equals-here:BASE:codex')

    def test_wrong_field_count_raises(self):
        with self.assertRaises(ValueError):
            br.parse_series_spec('Label=onlyroot')


class ParseFamilyMapTests(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(br.parse_family_map(['repair=Repair Tasks', 'edit=Edit Tasks']),
                          {'repair': 'Repair Tasks', 'edit': 'Edit Tasks'})

    def test_empty(self):
        self.assertEqual(br.parse_family_map(None), {})
        self.assertEqual(br.parse_family_map([]), {})

    def test_invalid_raises(self):
        with self.assertRaises(ValueError):
            br.parse_family_map(['no-equals'])


class OverviewTests(BuildFixturesMixin):
    def test_codex_overview_exclude_startup(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        row = report['overview']['Codex']
        self.assertEqual(row['tasks_attempted'], 3)
        self.assertEqual(row['passed'], 2)
        self.assertEqual(row['deadline_failures'], 1)
        self.assertAlmostEqual(row['median_working_time_s'], 15.0)
        self.assertAlmostEqual(row['mean_working_time_s'], 15.0)
        self.assertAlmostEqual(row['iqr_working_time_s'], 10.0)
        self.assertAlmostEqual(row['median_time_incl_startup_s'], 20.0)
        self.assertAlmostEqual(row['mean_cost_usd'], 1.5)
        self.assertEqual(row['cost_estimated_count'], 1)
        self.assertEqual(row['cost_unknown_count'], 1)
        self.assertEqual(row['cost_not_billed_count'], 0)
        self.assertEqual(row['infrastructure_retries'], 0)

    def test_fd_overview_exclude_startup_and_infra_retry(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        row = report['overview']['FD']
        self.assertEqual(row['tasks_attempted'], 3)
        self.assertEqual(row['passed'], 3)
        self.assertEqual(row['deadline_failures'], 0)
        self.assertAlmostEqual(row['median_working_time_s'], 8.0)
        self.assertAlmostEqual(row['mean_working_time_s'], 10.0)
        self.assertAlmostEqual(row['iqr_working_time_s'], 14.0)
        self.assertAlmostEqual(row['median_time_incl_startup_s'], 12.0)
        self.assertAlmostEqual(row['mean_cost_usd'], 0.5)
        # t2's attempt-1 infra failure (no result.json) makes this task's
        # attempts > 1 -- the only retried task in the whole fixture set.
        self.assertEqual(row['infrastructure_retries'], 1)

    def test_working_time_switches_with_exclude_startup_flag(self):
        _, report_excl = br.build_report(self._series_specs(), exclude_startup=True)
        _, report_incl = br.build_report(self._series_specs(), exclude_startup=False)
        fd_excl = report_excl['overview']['FD']['median_working_time_s']
        fd_incl = report_incl['overview']['FD']['median_working_time_s']
        self.assertAlmostEqual(fd_excl, 8.0)
        self.assertAlmostEqual(fd_incl, 12.0)
        self.assertNotAlmostEqual(fd_excl, fd_incl)


class FamilyTableTests(BuildFixturesMixin):
    def test_family_table_codex(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        families = report['by_family']['Codex']
        self.assertEqual(families['repair']['n'], 2)
        self.assertEqual(families['repair']['passed'], 2)
        self.assertAlmostEqual(families['repair']['median_working_time_s'], 15.0)
        self.assertEqual(families['edit']['n'], 1)
        self.assertEqual(families['edit']['passed'], 0)
        self.assertIsNone(families['edit']['median_working_time_s'])

    def test_family_map_renames(self):
        _, report = br.build_report(
            self._series_specs(), exclude_startup=True,
            family_map_pairs=['repair=Repair Tasks', 'edit=Edit Tasks'],
        )
        families = report['by_family']['FD']
        self.assertIn('Repair Tasks', families)
        self.assertIn('Edit Tasks', families)
        self.assertNotIn('repair', families)
        self.assertAlmostEqual(families['Repair Tasks']['median_working_time_s'], 13.0)
        self.assertAlmostEqual(families['Edit Tasks']['median_working_time_s'], 4.0)


class HeadToHeadTests(BuildFixturesMixin):
    def test_codex_vs_fd_hand_computed(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        row = report['head_to_head']['pairs']['Codex__vs__FD']
        self.assertEqual(row['n_shared_tasks'], 3)
        self.assertEqual(row['n_common_passed'], 2)
        self.assertEqual(row['wins'], 0)
        self.assertEqual(row['losses'], 2)
        self.assertEqual(row['ties'], 0)
        self.assertAlmostEqual(row['sign_test_p_value'], 0.5)
        expected_ratio = (10000.0 / 8000.0 * 20000.0 / 18000.0) ** 0.5
        self.assertAlmostEqual(row['typical_ratio_a_over_b'], expected_ratio)

    def test_fd_vs_codex_is_the_mirror(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        fwd = report['head_to_head']['pairs']['Codex__vs__FD']
        rev = report['head_to_head']['pairs']['FD__vs__Codex']
        self.assertEqual(rev['wins'], fwd['losses'])
        self.assertEqual(rev['losses'], fwd['wins'])
        self.assertAlmostEqual(rev['typical_ratio_a_over_b'], 1.0 / fwd['typical_ratio_a_over_b'])
        self.assertAlmostEqual(rev['sign_test_p_value'], fwd['sign_test_p_value'])

    def test_fd_vs_opencode_exact_ratio_one(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        row = report['head_to_head']['pairs']['FD__vs__OpenCode']
        # t1: fd exec=8000 vs opencode exec-missing->wall=9000 (fd faster)
        # t2: fd exec=18000 vs opencode exec=16000 (opencode faster)
        # ratio: sqrt((8000/9000)*(18000/16000)) == 1.0 exactly by construction.
        self.assertEqual(row['n_shared_tasks'], 2)
        self.assertEqual(row['n_common_passed'], 2)
        self.assertEqual(row['wins'], 1)
        self.assertEqual(row['losses'], 1)
        self.assertAlmostEqual(row['typical_ratio_a_over_b'], 1.0)

    def test_sentences_only_for_amplifier_series(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        sentences = report['head_to_head']['sentences']
        self.assertIn('FD', sentences)
        self.assertNotIn('Codex', sentences)
        self.assertNotIn('OpenCode', sentences)
        joined = ' '.join(sentences['FD'])
        self.assertIn('Codex', joined)
        self.assertIn('OpenCode', joined)

    def test_no_shared_passing_tasks_sentence(self):
        # Filter down to only t3 (edit); Codex's t3 failed, so FD vs Codex has
        # zero common-passed tasks -- exercise the "no shared passing tasks" branch.
        _, report = br.build_report(self._series_specs(), exclude_startup=True, task_filter='^t3$')
        sentences = report['head_to_head']['sentences']['FD']
        matching = [s for s in sentences if 'Codex' in s]
        self.assertEqual(len(matching), 1)
        self.assertIn('no shared passing tasks to compare', matching[0])


class MechanismTests(BuildFixturesMixin):
    def test_fd_mechanism_hand_computed(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        mech = report['mechanism']['FD']
        self.assertIsInstance(mech, dict)
        self.assertAlmostEqual(mech['mean_provider_requests_per_task'], 5.0)
        self.assertEqual(mech['model_routed_requests_total'], 3)
        self.assertEqual(mech['model_routed_escalations_total'], 1)
        self.assertEqual(mech['escalation_reasons'], {'timeout_risk': 1})
        self.assertEqual(mech['tasks_with_model_routed'], 2)
        self.assertEqual(mech['tasks_escalated'], 1)
        self.assertAlmostEqual(mech['share_of_tasks_escalated'], 1 / 3)
        self.assertEqual(mech['provider_calls_bypassed_total'], 3)
        self.assertEqual(mech['effort_routed_by_phase']['orient'],
                          {'unspecified': 1, 'medium': 1})
        self.assertEqual(mech['effort_routed_by_phase']['explore'], {'low': 3})

    def test_non_amplifier_series_mechanism_is_none(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        self.assertIsNone(report['mechanism']['Codex'])
        self.assertIsNone(report['mechanism']['OpenCode'])

    def test_mechanism_na_when_no_receipts(self):
        # An amplifier-fd series whose run dirs have no receipts.jsonl reports 'n/a'.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            exp_dir = root / 'experiments' / 'EXP'
            runs_root = exp_dir / 'runs'
            manifest_runs = {'EXP-t1-amplifier-fd-a1': {'task': 't1', 'harness': 'amplifier-fd', 'attempt': 1}}
            _write_json(runs_root / 'manifest.json', {'runs': manifest_runs})
            _write_json(runs_root / 'amplifier' / 'EXP-t1-amplifier-fd-a1' / 'result.json',
                        _base_result(task='t1', family='repair', harness='amplifier-fd', model='m',
                                     wall_time_ms=1000.0, exec_time_ms=900.0))
            _, report = br.build_report([f'NoReceipts={root}:EXP:amplifier-fd'], exclude_startup=True)
            self.assertEqual(report['mechanism']['NoReceipts'], 'n/a')


class QualityTests(BuildFixturesMixin):
    def test_codex_failure_labels_and_failed_tasks(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        q = report['quality']['Codex']
        self.assertEqual(q['top_failure_labels'], [('syntax_error', 1)])
        self.assertEqual(q['failed_tasks'], ['t3'])

    def test_fd_has_no_failures(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        q = report['quality']['FD']
        self.assertEqual(q['top_failure_labels'], [])
        self.assertEqual(q['failed_tasks'], [])


class EvidenceLimitsTests(BuildFixturesMixin):
    def test_repetition_and_contemporaneity(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        el = report['evidence_limits']
        self.assertIn('FD n=1', el['repetition'])
        self.assertIn('different campaign roots', el['contemporaneity'])
        self.assertEqual(el['task_counts_by_series'], {'Codex': 3, 'FD': 3, 'OpenCode': 2})
        self.assertEqual(el['total_distinct_tasks'], 3)

    def test_models_by_series(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        el = report['evidence_limits']
        self.assertEqual(el['models_by_series']['Codex'], 'gpt-6-astra (3/3)')
        self.assertEqual(el['models_by_series']['FD'], 'claude-sonnet-5 (3/3)')
        self.assertEqual(el['models_by_series']['OpenCode'], 'glm-5.3 (2/2)')

    def test_exec_time_source_mix(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True)
        mix = report['evidence_limits']['exec_time_source_mix']
        self.assertEqual(mix['Codex'], {'harness_duration_ms': 2, 'wall_includes_startup': 1})
        self.assertEqual(mix['FD'], {'native_events_first_request_to_last_response': 3})
        self.assertEqual(mix['OpenCode'], {'wall_includes_startup': 1, 'harness_event_timestamps': 1})

    def test_single_root_no_retries_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runs_root = root / 'experiments' / 'EXP' / 'runs'
            manifest_runs = {'EXP-t1-codex-a1': {'task': 't1', 'harness': 'codex', 'attempt': 1}}
            _write_json(runs_root / 'manifest.json', {'runs': manifest_runs})
            _write_json(runs_root / 'EXP-t1-codex-a1' / 'result.json',
                        _base_result(task='t1', family='repair', harness='codex', model='m',
                                     wall_time_ms=1000.0, exec_time_ms=900.0))
            _, report = br.build_report([f'Solo={root}:EXP:codex'], exclude_startup=True)
            self.assertIn('no retries observed', report['evidence_limits']['repetition'])
            self.assertIn('same campaign root', report['evidence_limits']['contemporaneity'])


class TaskFilterTests(BuildFixturesMixin):
    def test_task_filter_excludes_non_matching_tasks(self):
        _, report = br.build_report(self._series_specs(), exclude_startup=True, task_filter=r'^t[12]$')
        self.assertEqual(report['overview']['Codex']['tasks_attempted'], 2)
        self.assertEqual(report['overview']['FD']['tasks_attempted'], 2)
        self.assertNotIn('edit', report['by_family']['Codex'])
        self.assertEqual(report['evidence_limits']['total_distinct_tasks'], 2)


class CliAndMarkdownTests(BuildFixturesMixin):
    def test_report_md_contains_labels_and_no_nan(self):
        markdown, _ = br.build_report(self._series_specs(), title='Test Battery Report', exclude_startup=True)
        self.assertIn('Test Battery Report', markdown)
        self.assertIn('Codex', markdown)
        self.assertIn('FD', markdown)
        self.assertIn('OpenCode', markdown)
        self.assertNotIn('nan', markdown.lower())

    def test_cli_writes_report_files(self):
        with tempfile.TemporaryDirectory() as out_tmp:
            out_dir = Path(out_tmp) / 'out'
            argv = ['--out', str(out_dir), '--title', 'CLI Battery Report']
            for spec in self._series_specs():
                argv += ['--series', spec]
            rc = br.main(argv)
            self.assertEqual(rc, 0)
            md_path = out_dir / 'report.md'
            json_path = out_dir / 'report.json'
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            md_text = md_path.read_text(encoding='utf-8')
            self.assertIn('CLI Battery Report', md_text)
            self.assertNotIn('nan', md_text.lower())
            report = json.loads(json_path.read_text(encoding='utf-8'))
            self.assertIn('Codex', [s['label'] for s in report['series']])
            self.assertIn('FD', [s['label'] for s in report['series']])
            self.assertIn('OpenCode', [s['label'] for s in report['series']])

    def test_cli_exclude_startup_flag_roundtrip(self):
        with tempfile.TemporaryDirectory() as out_tmp:
            out_dir = Path(out_tmp) / 'out'
            argv = ['--out', str(out_dir), '--no-exclude-startup']
            for spec in self._series_specs():
                argv += ['--series', spec]
            rc = br.main(argv)
            self.assertEqual(rc, 0)
            report = json.loads((out_dir / 'report.json').read_text(encoding='utf-8'))
            self.assertFalse(report['options']['exclude_startup'])
            self.assertAlmostEqual(report['overview']['FD']['median_working_time_s'], 12.0)


class AggregateRepsTests(unittest.TestCase):
    """3 synthetic repetitions of one cell (harness 'amplifier-fd'), same
    campaign root, 2 tasks. rep1/rep2 pass task 'a' (exec 10s/12s), rep3
    fails it (majority pass=True, median exec=11s from the 2 passing reps).
    task 'b': rep1 fails, rep2/rep3 pass (10s/14s) -- majority pass=True,
    median exec=12s. Consistency: task 'a' has mixed pass/fail (not
    identical), task 'b' also mixed -- consistency=0.0.
    """

    def _write_rep(self, root, exp, rows):
        runs_root = root / 'experiments' / exp / 'runs'
        manifest_runs = {}
        for name, task, passed, exec_ms, cost in rows:
            manifest_runs[name] = {'task': task, 'harness': 'amplifier-fd', 'attempt': 1}
            _write_json(runs_root / 'amplifier' / name / 'result.json', _base_result(
                task=task, family='repair', harness='amplifier-fd', model='m',
                wall_time_ms=exec_ms, exec_time_ms=exec_ms, cost_usd=cost,
                cost_billable=True if cost is not None else None,
                cost_source='harness_reported' if cost is not None else 'unknown',
                outcome_passed=passed,
            ))
        _write_json(runs_root / 'manifest.json', {
            'schema': 'fast-decisions-battery/v1', 'run_order': list(manifest_runs),
            'runs': manifest_runs, 'deadline_seconds': 600, 'prompt': 'do the task',
        })

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / 'campaign'
        self._write_rep(self.root, 'EXP-r1', [
            ('EXP-r1-a-amplifier-fd-a1', 'a', True, 10000.0, 1.0),
            ('EXP-r1-b-amplifier-fd-a1', 'b', False, 9000.0, 1.0),
        ])
        self._write_rep(self.root, 'EXP-r2', [
            ('EXP-r2-a-amplifier-fd-a1', 'a', True, 12000.0, 1.2),
            ('EXP-r2-b-amplifier-fd-a1', 'b', True, 10000.0, 0.9),
        ])
        self._write_rep(self.root, 'EXP-r3', [
            ('EXP-r3-a-amplifier-fd-a1', 'a', False, 20000.0, 2.0),
            ('EXP-r3-b-amplifier-fd-a1', 'b', True, 14000.0, 1.1),
        ])

    def _spec(self):
        return f'FD={self.root}:EXP-r1,EXP-r2,EXP-r3:amplifier-fd'

    def test_parse_aggregate_spec(self):
        label, root, experiments, harness = br.parse_aggregate_spec(self._spec())
        self.assertEqual(label, 'FD')
        self.assertEqual(experiments, ['EXP-r1', 'EXP-r2', 'EXP-r3'])
        self.assertEqual(harness, 'amplifier-fd')

    def test_parse_aggregate_spec_invalid(self):
        with self.assertRaises(ValueError):
            br.parse_aggregate_spec('no-equals-here')
        with self.assertRaises(ValueError):
            br.parse_aggregate_spec('L=root:')

    def test_aggregate_median_exec_and_majority_pass(self):
        series, reps_summary = br.aggregate_reps('FD', self.root, ['EXP-r1', 'EXP-r2', 'EXP-r3'],
                                                   'amplifier-fd', exclude_startup=True)
        a = series['tasks']['a']['result']
        self.assertTrue(a['outcome_passed'])  # 2 of 3 passed
        self.assertAlmostEqual(a['exec_time_ms'], 11000.0)  # median of the 2 passing reps: 10s,12s
        b = series['tasks']['b']['result']
        self.assertTrue(b['outcome_passed'])  # 2 of 3 passed
        self.assertAlmostEqual(b['exec_time_ms'], 12000.0)  # median of the 2 passing reps: 10s,14s

    def test_reps_summary_per_task_and_consistency(self):
        _, reps_summary = br.aggregate_reps('FD', self.root, ['EXP-r1', 'EXP-r2', 'EXP-r3'],
                                             'amplifier-fd', exclude_startup=True)
        self.assertEqual(reps_summary['n_reps'], 3)
        self.assertEqual(len(reps_summary['tasks']['a']['per_rep']), 3)
        self.assertAlmostEqual(reps_summary['tasks']['a']['pass_rate'], 2 / 3)
        self.assertAlmostEqual(reps_summary['tasks']['a']['median_exec_s'], 11.0)
        # neither task has an identical pass/fail outcome across all 3 reps
        self.assertAlmostEqual(reps_summary['consistency'], 0.0)

    def test_aggregate_series_feeds_existing_compute_functions(self):
        _, report = br.build_report([], exclude_startup=True, aggregate_specs=[self._spec()])
        overview = report['overview']['FD']
        self.assertEqual(overview['tasks_attempted'], 2)
        self.assertEqual(overview['passed'], 2)
        self.assertIn('FD', report['reps_summary'])
        self.assertEqual(report['reps_summary']['FD']['n_reps'], 3)
        # mechanism is 'n/a' for an aggregated series -- no single run_dir backs
        # a median-across-reps pseudo-result, so no receipts.jsonl is found.
        self.assertEqual(report['mechanism']['FD'], 'n/a')

    def test_aggregate_reps_cli_end_to_end(self):
        with tempfile.TemporaryDirectory() as out_tmp:
            out_dir = Path(out_tmp) / 'out'
            rc = br.main(['--out', str(out_dir), '--aggregate-reps', self._spec()])
            self.assertEqual(rc, 0)
            report = json.loads((out_dir / 'report.json').read_text(encoding='utf-8'))
            self.assertIn('FD', report['reps_summary'])
            md = (out_dir / 'report.md').read_text(encoding='utf-8')
            self.assertIn('Cross-repetition aggregation', md)


class StatsHelperTests(unittest.TestCase):
    def test_iqr_even_and_odd(self):
        self.assertAlmostEqual(br._iqr([10.0, 20.0]), 10.0)
        self.assertAlmostEqual(br._iqr([4.0, 8.0, 18.0]), 14.0)
        self.assertIsNone(br._iqr([]))

    def test_geomean(self):
        self.assertIsNone(br._geomean([]))
        self.assertAlmostEqual(br._geomean([1.0, 4.0]), 2.0)

    def test_sign_test_p_ties_excluded(self):
        self.assertIsNone(br._sign_test_p([]))
        self.assertAlmostEqual(br._sign_test_p([1, -1, 0]), 1.0)
        self.assertAlmostEqual(br._sign_test_p([-1, -1]), 0.5)


if __name__ == '__main__':
    unittest.main()
