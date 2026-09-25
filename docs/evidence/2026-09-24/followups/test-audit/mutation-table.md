| id | file | break | caught before? (by) | now caught by (test added) |
|---|---|---|---|---|
| a1 | orchestrator.py | scope gate never fires (> -> <) | yes: test_orchestrator_primary.ScopeGateTests.test_large_workspace_starts_strong_without_asking_the_judge, test_orchestrator_primary.ScopeGateTests.test_small_workspace_defers_to_the_judge | -- |
| a2 | orchestrator.py | judge probability gate inverted | yes: test_orchestrator_primary.DifficultyRouterTests.test_mid_session_default_model_change_is_respected, test_orchestrator_primary.EffortByTierTests.test_mid_session_default_model_change_is_respected (+6) | -- |
| a2b | orchestrator.py | judge 'simple' probability not complemented | yes: test_orchestrator_primary.DifficultyRouterTests.test_mid_session_default_model_change_is_respected, test_orchestrator_primary.EffortByTierTests.test_mid_session_default_model_change_is_respected (+6) | -- |
| a2c | orchestrator.py | complex_min_probability ignored (gate fixed 0.5) | no | **test_orchestrator_primary.RoutingReceiptTests.test_complex_min_probability_is_the_gate** |
| a3 | orchestrator.py | user_model early-return removed | yes: test_orchestrator_primary.DifficultyRouterTests.test_mid_session_default_model_change_is_respected, test_orchestrator_primary.DifficultyRouterTests.test_ui_model_pick_is_respected (+4) | -- |
| a4 | orchestrator.py | rules threshold >= -> > (off by one) | no | **test_orchestrator_primary.RoutingReceiptTests.test_rules_threshold_is_inclusive** |
| a5 | orchestrator.py | judge abstain does not fall back to rules (forces cheap) | yes: test_orchestrator_primary.DifficultyRouterTests.test_judge_failure_falls_back_to_rules, test_orchestrator_primary.EffortByTierTests.test_judge_failure_falls_back_to_rules (+1) | -- |
| b1 | orchestrator.py | start_model not passed via kwargs on cheap turns | no | **test_orchestrator_primary.RoutingReceiptTests.test_cheap_turn_passes_start_model_to_provider_kwargs, test_orchestrator_primary.RoutingReceiptTests.test_no_max_requests_means_no_escalation** |
| b1b | orchestrator.py | start_model not written to request on cheap turns | yes: test_orchestrator_primary.DifficultyRouterTests.test_mid_session_default_model_change_is_respected, test_orchestrator_primary.EffortByTierTests.test_mid_session_default_model_change_is_respected (+6) | -- |
| b2 | orchestrator.py | model override applied on strong turns | yes: test_orchestrator_primary.DifficultyRouterTests.test_judge_complex_starts_strong_and_never_escalates_or_switches, test_orchestrator_primary.DifficultyRouterTests.test_judge_failure_falls_back_to_rules (+6) | -- |
| b2b | orchestrator.py | strong turn still escalates/overrides (strong_turn False) | yes: test_orchestrator_primary.DifficultyRouterTests.test_judge_complex_starts_strong_and_never_escalates_or_switches, test_orchestrator_primary.DifficultyRouterTests.test_judge_failure_falls_back_to_rules (+6) | -- |
| b3 | orchestrator.py | _user_selected_model always None | yes: test_orchestrator_primary.DifficultyRouterTests.test_mid_session_default_model_change_is_respected, test_orchestrator_primary.DifficultyRouterTests.test_ui_model_pick_is_respected (+4) | -- |
| b3b | orchestrator.py | ui.model_override marker ignored | yes: test_orchestrator_primary.DifficultyRouterTests.test_ui_model_pick_is_respected, test_orchestrator_primary.EffortByTierTests.test_ui_model_pick_is_respected (+1) | -- |
| b3c | orchestrator.py | mid-session default_model change ignored | yes: test_orchestrator_primary.DifficultyRouterTests.test_mid_session_default_model_change_is_respected, test_orchestrator_primary.EffortByTierTests.test_mid_session_default_model_change_is_respected (+1) | -- |
| b3d | orchestrator.py | initial default model re-captured every call | yes: test_orchestrator_primary.DifficultyRouterTests.test_mid_session_default_model_change_is_respected, test_orchestrator_primary.EffortByTierTests.test_mid_session_default_model_change_is_respected (+1) | -- |
| b4 | orchestrator.py | host_model dropped from slow_end | no | **test_orchestrator_primary.RoutingReceiptTests.test_slow_end_records_host_model_and_provider_usage** |
| b5 | orchestrator.py | start tier re-decided on every request (not once per turn) | yes: test_orchestrator_primary.DifficultyRouterTests.test_judge_complex_starts_strong_and_never_escalates_or_switches, test_orchestrator_primary.EffortByTierTests.test_judge_complex_starts_strong_and_never_escalates_or_switches (+1) | -- |
| b6 | orchestrator.py | host_pinned model overridden without override_explicit_model | yes: test_model_routing.ModelRoutingEnabledTests.test_explicit_host_model_untouched_by_default | -- |
| b7 | orchestrator.py | provider_match ignored | yes: test_orchestrator_primary.ProviderMatchTests.test_non_matching_provider_keeps_its_model | -- |
| b8 | orchestrator.py | start_effort applied even when effort routing already set one | no | none -- equivalent mutant: whenever effort routing applied an effort, request.reasoning_effort is already set, so the next guard (`reasoning_effort is None`) blocks start_effort anyway |
| c1 | orchestrator.py | max_requests None treated as 6 | no | **test_orchestrator_primary.RoutingReceiptTests.test_no_max_requests_means_no_escalation, test_multi_question.BatchingProducesOneCallTests.test_batching_continues_past_six_requests_without_a_max** |
| c1b | orchestrator.py | judge-due helper treats None max_requests as 6 | no | **test_multi_question.BatchingProducesOneCallTests.test_batching_continues_past_six_requests_without_a_max** |
| c2 | orchestrator.py | max_requests off-by-one (> -> >=) | yes: test_model_routing.ModelRoutingEnabledTests.test_max_requests_escalation | -- |
| c3 | orchestrator.py | escalate_on_test_failure ignored | yes: test_model_routing.ModelRoutingEnabledTests.test_test_failure_escalation, test_decomposed_escalation.DecomposedEscalationTests.test_deterministic_test_failure_floor_preempts_decomposed (+1) | -- |
| c4 | orchestrator.py | escalate_on_provider_error ignored | yes: test_model_routing.ModelRoutingEnabledTests.test_provider_error_escalation | -- |
| d1 | orchestrator.py | by_tier cheap effort not applied | yes: test_orchestrator_primary.EffortByTierTests.test_cheap_turn_holds_one_effort_across_phases | -- |
| d2 | orchestrator.py | by_tier overrides host-pinned effort | no | **test_orchestrator_primary.RoutingReceiptTests.test_host_pinned_effort_is_not_overridden_by_tier** |
| d3 | orchestrator.py | by_tier strong effort not applied | yes: test_orchestrator_primary.EffortByTierTests.test_strong_turn_leaves_provider_default | -- |
| e1 | backends.py | api_key_env ignored (always TYPESAFE_API_KEY) | yes: test_rubric_and_endpoint.JevCompatibleEndpointTests.test_configured_endpoint_skips_the_sdk_even_when_installed, test_rubric_and_endpoint.JevCompatibleEndpointTests.test_rubric_end_to_end_over_http (+2) | -- |
| e2 | backends.py | missing base_url_env does not raise | no | **test_rubric_and_endpoint.JevCompatibleEndpointTests.test_missing_url_env_is_unavailable_not_a_crash** |
| e3 | backends.py | api_key_env alone does not force stdlib transport | no | **test_rubric_and_endpoint.JevCompatibleEndpointTests.test_custom_key_env_alone_skips_the_sdk** |
| e4 | backends.py | base_url trailing slash not stripped | no | none -- equivalent mutant: `_post_keepalive` uses only scheme/host/port of base_url and always posts to `/v1/systemone`, so a trailing slash (or any path prefix) is ignored -- see finding F1 |
| f1 | rubric.py | geometric mean computed as arithmetic | yes: test_rubric_and_endpoint.JevCompatibleEndpointTests.test_rubric_end_to_end_over_http, test_rubric_and_endpoint.RubricTests.test_aggregations (+1) | -- |
| f2 | rubric.py | weights ignored | yes: test_rubric_and_endpoint.JevCompatibleEndpointTests.test_rubric_end_to_end_over_http, test_rubric_and_endpoint.RubricTests.test_weight_makes_one_failure_dominate | -- |
| f3 | rubric.py | harmonic mean computed as geometric | yes: test_rubric_and_endpoint.RubricTests.test_aggregations | -- |
| f4 | rubric.py | non-positive weight accepted | yes: test_rubric_and_endpoint.RubricTests.test_spec_validation | -- |
| g1 | savings.py | cached reads not subtracted from input | yes: test_savings.PriceTests.test_cached_reads_are_split_out_of_input, test_savings.SummarizeTests.test_recorded_host_model_prices_the_counterfactual | -- |
| g2 | savings.py | counterfactual priced at the cheap model | yes: test_savings.SummarizeTests.test_cheap_turn_saved_and_strong_turn_counts_nothing, test_savings.SummarizeTests.test_recorded_host_model_prices_the_counterfactual | -- |
| g3 | savings.py | per-request recorded host_model ignored | no | **test_savings.SummarizeTests.test_each_request_is_priced_at_its_own_recorded_host** |
| g3b | savings.py | file-level host auto-detection ignored | no | **test_savings.SummarizeTests.test_request_without_host_uses_the_file_host** |
| g3c | savings.py | summary host_model ignores recorded hosts | yes: test_savings.SummarizeTests.test_recorded_host_model_prices_the_counterfactual | -- |
| g4 | savings.py | negative savings clamped to zero | yes: test_savings.SummarizeTests.test_recorded_host_model_prices_the_counterfactual | -- |
| g5 | savings.py | provider cost_usd ignored | yes: test_savings.SummarizeTests.test_provider_cost_is_preferred_and_missing_cache_data_is_flagged | -- |
| g6 | savings.py | cache writes priced at input rate | no | **test_savings.PriceTests.test_cache_writes_use_the_cache_write_rate** |
| g7 | savings.py | synthetic events not skipped | yes: test_savings.SummarizeTests.test_since_filter_synthetic_skip_and_cache_reuse | -- |
| g8 | savings.py | failed slow_end requests counted | yes: test_savings.SummarizeTests.test_cheap_turn_saved_and_strong_turn_counts_nothing | -- |
| g9 | savings.py | strong-turn requests priced as savings | yes: test_savings.SummarizeTests.test_cheap_turn_saved_and_strong_turn_counts_nothing, test_savings.SummarizeTests.test_time_estimate_needs_samples_on_both_models | -- |
| g10 | savings.py | dated model ids do not match family rates | yes: test_savings.PriceTests.test_dated_ids_and_unknown_models | -- |
| g11 | savings.py | time ratio inverted | yes: test_savings.SummarizeTests.test_time_estimate_needs_samples_on_both_models | -- |
| g12 | savings.py | since filter ignored | yes: test_savings.SummarizeTests.test_since_filter_synthetic_skip_and_cache_reuse | -- |
| g13 | savings.py | cache signature ignored (stale partial reused) | no | **test_savings.SummarizeTests.test_cache_is_invalidated_when_a_session_file_grows** |
| h1 | observatory.py | stale build reused instead of replaced | yes: test_observatory.EnsureViewerTests.test_replaces_a_live_viewer_from_another_build | -- |
| h2 | observatory.py | pid 1 guard removed (pid > 1 -> pid >= 1; os.kill mocked in tests) | yes: test_observatory.EnsureViewerTests.test_replaces_a_live_viewer_from_another_build | -- |
| h3 | observatory.py | stale viewer state not removed | no | **test_observatory.EnsureViewerTests.test_stale_viewer_is_never_returned_after_replacement** |
| h4 | observatory.py | build_id ignores app.js | no | **test_observatory.EnsureViewerTests.test_build_id_changes_when_any_dashboard_asset_changes** |
| i1 | privacy.py | SAFE_FIELDS drops cost_usd | no | **test_orchestrator_primary.RoutingReceiptTests.test_slow_end_records_host_model_and_provider_usage, test_decisions.PrivacyTests.test_savings_usage_fields_survive_the_allow_list** |
| i2 | privacy.py | SAFE_FIELDS drops host_model | no | **test_orchestrator_primary.RoutingReceiptTests.test_slow_end_records_host_model_and_provider_usage, test_decisions.PrivacyTests.test_savings_usage_fields_survive_the_allow_list** |
| i3 | privacy.py | SAFE_FIELDS drops cache_read_tokens | no | **test_orchestrator_primary.RoutingReceiptTests.test_slow_end_records_host_model_and_provider_usage, test_decisions.PrivacyTests.test_savings_usage_fields_survive_the_allow_list** |
| i4 | privacy.py | string values not scrubbed | no | **test_decisions.PrivacyTests.test_allowed_string_values_are_still_scrubbed** |
| u1 | orchestrator.py | usage_fields drops provider cost_usd | no | **test_orchestrator_primary.RoutingReceiptTests.test_slow_end_records_host_model_and_provider_usage** |
| u2 | orchestrator.py | usage_fields drops served_model | no | **test_orchestrator_primary.RoutingReceiptTests.test_slow_end_records_host_model_and_provider_usage** |
| u3 | orchestrator.py | usage_fields drops cache token counts | no | **test_orchestrator_primary.RoutingReceiptTests.test_slow_end_records_host_model_and_provider_usage** |
| g14 | savings.py | savings ignores served_model (prices requested model) | no | **test_savings.SummarizeTests.test_served_model_is_what_gets_priced** |
| w1 | runtime.py | backend warmup exception not swallowed | no | **test_runtime.BackendWarmupNoRunningLoopTests.test_raising_warmup_in_thread_path_does_not_raise_here, test_runtime.BackendWarmupSchedulingTests.test_raising_warmup_is_swallowed_not_propagated** |
| j1 | app.js | modelView marks escalated calls as faster | yes: provider calls show which model ran and why | -- |
| j2 | app.js | judgmentView swaps easy/hard | yes: provider calls show which model ran and why | -- |
| j2b | app.js | judgmentView % hard shows easy probability | yes: provider calls show which model ran and why | -- |
| j3 | app.js | savingsView money sign dropped | yes: negative savings read as costing more | -- |
| j3b | app.js | savingsView 'costs more' test inverted | yes: savings view explains empty and estimated states, negative savings read as costing more | -- |
| j4 | app.js | modelView usual model ignores host_model | yes: provider calls show which model ran and why | -- |
| j5 | app.js | savingsView time shows cheap seconds instead of saved | no | **savings time shows the time saved, not the time spent** |
| k1 | contracts.py | invalid start_policy accepted | yes: test_orchestrator_primary.DifficultyRouterTests.test_validation, test_orchestrator_primary.ScopeGateTests.test_validation | -- |
| k2 | contracts.py | complex_min_probability out of range accepted | yes: test_orchestrator_primary.DifficultyRouterTests.test_validation, test_orchestrator_primary.ScopeGateTests.test_validation | -- |
| k3 | contracts.py | cheap_max_workspace_files 0 accepted | no | **test_orchestrator_primary.RoutingReceiptTests.test_zero_workspace_file_limit_is_rejected** |
| k4 | contracts.py | max_requests_before_escalation 0 accepted | yes: test_model_routing.ModelRoutingValidationTests.test_invalid_max_requests_raises | -- |
| k5 | contracts.py | unknown model_routing keys accepted | yes: test_model_routing.ModelRoutingValidationTests.test_unknown_keys_raise | -- |
| k6 | contracts.py | by_tier invalid tier key accepted | yes: test_orchestrator_primary.EffortByTierTests.test_validation | -- |
