# Branch Coverage Baseline — 2026-08-17

The measured starting point for the multi-part branch-coverage effort
(`2026-08-17-branch-coverage-index.md`). Regenerate with the command below;
never edit the numbers here by hand — supersede this file with a new dated one.

## Run metadata

- **Command** (from the repo root, local Postgres up via `make db-up`):

      DATABASE_URL=$(bash scripts/local_postgres.sh url) \
        .venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q \
        --cov=original --cov-branch --cov-report=json:coverage.json --cov-report=term-missing

- **Result:** 2334 passed, 5 skipped, 0 failed in 13m56s (coverage instrumentation
  inflates runtime ~25%; the fusion wiring tests dominate the middle of the run).
  With the local Postgres container up, the postgres-marked suite (166 tests)
  RUNS instead of skipping — only 5 environment-dependent skips remain.
- **Totals:** 11,621 statements (1,936 missing); **3,056 branches — 2,357 covered,
  699 missing, 359 partial**. Branch coverage **77.13%**; combined
  statements+branches percent (what `--cov-fail-under` sees under `--cov-branch`)
  **82.05%**; line-only coverage 83.34%.
- Line-only coverage on the same date WITHOUT Postgres was 78.69% — the delta is
  almost entirely `original/postgres_repository.py` (0% → 70.7%).

## Cluster summary (scripts/branch_coverage_report.py)

    TOTAL branch coverage: 77.13% (2357/3056; 699 missing)

    cluster         branch%  covered   total  missing  files
    other            50.48%      212     420      208     19
    api              68.11%      346     508      162     17
    integrations     72.63%      199     274       75     13
    persistence      79.67%      290     364       74     16
    context          84.18%      298     354       56     10
    features         87.72%      600     684       84     18
    quantum          91.15%      412     452       40     11

    file                                                  branch%  missing   line%
    original/cli/security_audit.py                          0.00%       76    0.0%
    original/postgres_repository.py                        70.67%       44   70.7%
    original/routers/students_baseline.py                  37.93%       36   45.3%
    original/store.py                                      85.48%       27   82.4%
    original/cli/delete_student.py                          0.00%       22    0.0%
    original/lab/runner.py                                  0.00%       22   17.4%
    original/routers/bluebook.py                           62.00%       19   73.1%
    original/routers/students.py                           54.76%       19   61.0%
    original/bbook_client.py                                0.00%       18   36.7%
    original/context/resolvers.py                          81.52%       17   89.7%
    original/api.py                                        55.56%       16   70.1%
    original/core/config.py                                 0.00%       16    0.0%
    original/lti.py                                        66.67%       16   74.8%
    original/tension_arc.py                                77.14%       16   83.1%
    original/context/genre_v2.py                           77.94%       15   88.4%
    original/_env.py                                        0.00%       14    0.0%
    original/quantum/longitudinal.py                       77.42%       14   89.4%
    original/explainer.py                                  59.38%       13   70.5%
    original/features/uniformity.py                        62.50%       12   78.6%
    original/quantum/scoring.py                            93.55%       12   95.6%
    original/routers/admin.py                              77.78%       12   85.0%
    original/routers/auth.py                               63.33%       11   78.5%
    original/student_auth.py                               60.71%       11   69.8%
    original/style_authorship.py                           69.44%       11   84.1%
    original/voice.py                                      76.09%       11   86.1%
    original/core/logging.py                                0.00%       10   35.6%
    original/features/tier7.py                             86.49%       10   90.2%
    original/context/report.py                             84.48%        9   90.4%
    original/features/tier11.py                            71.88%        9   80.0%
    original/core/security.py                               0.00%        8    0.0%
    original/features/prosodic.py                          93.55%        8   93.2%
    original/features/tier5.py                             80.95%        8   87.2%
    original/quantum/state.py                              84.00%        8   89.6%
    original/routers/students_scoring.py                   84.62%        8   80.9%
    original/ai_likelihood.py                              80.56%        7   86.5%
    original/context/baseline_match.py                     85.42%        7   89.9%
    original/context/blend.py                              83.33%        7   90.2%
    original/features/tier10.py                            75.00%        7   76.4%
    original/baseline_requests.py                          76.92%        6   88.3%
    original/features/tier2.py                             92.31%        6   93.1%

## Function-level gap digest

Function-level branch gaps extracted from the coverage JSON's `functions`
records (functions with ≥1 missing branch, per file, worst first).


    ######## CLUSTER api ########

    == original/routers/students_baseline.py (36 missing) ==
       upload_baseline_batch: 24/24 missing
       add_baseline: 6/22 missing
       request_proctored_baseline: 4/4 missing
       _existing_text_hashes: 2/8 missing

    == original/routers/students.py (19 missing) ==
       upload_file: 6/6 missing
       get_sample_text: 4/4 missing
       open_formation: 2/2 missing
       get_student_readiness: 2/18 missing
       advance_formation: 2/2 missing
       student_data_inventory: 1/2 missing
       list_students: 1/4 missing
       delete_student: 1/2 missing

    == original/routers/bluebook.py (19 missing) ==
       bluebook_magic_launch: 8/8 missing
       bluebook_record_submission: 4/16 missing
       bluebook_list_exams: 3/4 missing
       bluebook_list_courses: 3/4 missing
       bluebook_list_submissions: 1/4 missing

    == original/lti.py (16 missing) ==
       _private_key_pem: 4/4 missing
       verify_state: 2/6 missing
       verify_launch: 2/10 missing
       public_jwks: 2/2 missing
       fetch_jwks: 2/2 missing
       principal_from_claims: 1/8 missing
       is_exam_launch: 1/4 missing
       find_platform: 1/4 missing
       build_login_redirect: 1/4 missing

    == original/api.py (16 missing) ==
       lifespan: 12/12 missing
       _resolve_allowed_origins: 2/6 missing
       security_headers: 1/4 missing
       _resolve_app_version: 1/2 missing

    == original/routers/admin.py (12 missing) ==
       submit_correction: 2/12 missing
       admin_list_corrections: 2/4 missing
       admin_list_calibration_runs: 2/4 missing
       test_score: 1/14 missing
       admin_run_suggestions: 1/6 missing
       admin_run_calibration: 1/2 missing
       admin_list_tuned_thresholds: 1/2 missing
       admin_list_manifests: 1/4 missing
       admin_apply_thresholds: 1/4 missing

    == original/routers/auth.py (11 missing) ==
       student_login: 3/6 missing
       demo_login: 3/8 missing
       student_me: 2/2 missing
       auth_register: 2/8 missing
       auth_login: 1/4 missing

    == original/routers/students_scoring.py (8 missing) ==
       score_submission: 5/46 missing
       score_blend: 2/4 missing
       score_submission._all_states: 1/2 missing

    == original/routers/imports.py (6 missing) ==
       import_canvas_baseline: 4/16 missing
       fetch_canvas_submission_text: 2/6 missing

    == original/routers/lti_routes.py (5 missing) ==
       lti_launch: 4/4 missing
       lti_login: 1/2 missing

    == original/routers/_shared.py (4 missing) ==
       _throttle_login: 1/4 missing
       _require_staff: 1/6 missing
       _require_guard: 1/6 missing
       _authorize_provenance: 1/12 missing

    == original/routers/proctor.py (3 missing) ==
       open_park_session: 1/8 missing
       beat: 1/10 missing
       _throttle_beat: 1/4 missing

    == original/routers/me.py (3 missing) ==
       my_formation_advance: 2/2 missing
       my_voice: 1/2 missing

    == original/routers/health.py (3 missing) ==
       admin_health: 3/4 missing

    == original/routers/tenants.py (1 missing) ==
       create_tenant: 1/12 missing

    ######## CLUSTER context ########

    == original/context/resolvers.py (17 missing) ==
       resolve_language: 5/16 missing
       _resolve_genre_v1: 3/20 missing
       resolve_composition_mode: 2/10 missing
       run_resolvers: 1/6 missing
       resolve_topic: 1/8 missing
       resolve_length: 1/8 missing
       resolve_citations: 1/12 missing
       _looks_structured: 1/2 missing
       _estimate_punct_error_ratio: 1/2 missing
       _estimate_comma_splice_rate: 1/2 missing

    == original/context/genre_v2.py (15 missing) ==
       _resolve_by_rules: 7/18 missing
       _load_artifact: 5/20 missing
       extract_signals: 1/4 missing
       _ensure_loaded: 1/6 missing
       _confidence_min: 1/2 missing

    == original/context/report.py (9 missing) ==
       generate_narrative: 4/26 missing
       _flatten_flags: 2/2 missing
       build_report: 1/4 missing
       _baseline_cluster_labels: 1/6 missing
       _anchor_consistency: 1/10 missing

    == original/context/blend.py (7 missing) ==
       detect_blend: 7/20 missing

    == original/context/baseline_match.py (7 missing) ==
       ensure_sample_context_metadata: 3/12 missing
       _ensure_tfidf_vectorizer: 2/6 missing
       match_baseline_cluster: 1/10 missing
       _transform_centroid: 1/2 missing

    == original/context/manifest.py (1 missing) ==
       _derive_directives: 1/18 missing

    ######## CLUSTER features ########

    == original/features/uniformity.py (12 missing) ==
       window_feature_variance_ratio: 2/4 missing
       vocab_introduction_flatness: 2/8 missing
       sentence_length_dispersion_ratio: 2/4 missing
       punctuation_dispersion_ratio: 2/6 missing
       function_word_burstiness_ratio: 2/4 missing
       clause_depth_variance_ratio: 2/6 missing

    == original/features/tier7.py (10 missing) ==
       transition_predictability: 3/10 missing
       _gini_coefficient: 2/6 missing
       vocabulary_introduction_rate: 1/8 missing
       repetition_gap_entropy: 1/18 missing
       perplexity_proxy: 1/6 missing
       burstiness: 1/4 missing
       _load_word_freqs: 1/4 missing

    == original/features/tier11.py (9 missing) ==
       _extract_error_profile: 6/26 missing
       _get_nlp: 2/4 missing
       compute_tier11_comparison: 1/2 missing

    == original/features/tier5.py (8 missing) ==
       _shannon_entropy: 2/6 missing
       _get_nlp: 2/4 missing
       _get_dep_depths: 2/6 missing
       _get_pos_tags: 1/2 missing
       _get_dep_depths._depth: 1/4 missing

    == original/features/prosodic.py (8 missing) ==
       _semantic_field_concentration: 3/12 missing
       _word_stress: 1/4 missing
       _shannon_entropy: 1/2 missing
       _metric_flatness_score: 1/8 missing
       _chiasmus_rate: 1/10 missing
       _article_omission_rate: 1/12 missing

    == original/features/tier10.py (7 missing) ==
       compute_tier10_comparison: 3/12 missing
       _tfidf_encode: 2/4 missing
       _get_st_model: 1/4 missing
       _encode_sentences: 1/4 missing

    == original/features/tier6.py (6 missing) ==
       citation_style_consistency: 5/10 missing
       list_marker_preference: 1/6 missing

    == original/features/tier2.py (6 missing) ==
       paragraph_topic_position: 2/12 missing
       thematic_progression_score: 1/12 missing
       sentence_opener_variety: 1/16 missing
       lexical_chain_density: 1/8 missing
       avg_paragraph_length: 1/2 missing

    == original/features/tier17.py (5 missing) ==
       typing_speed_cv: 1/4 missing
       pause_density: 1/2 missing
       paste_event_rate: 1/2 missing
       deletion_rate: 1/4 missing
       _iki_deltas: 1/10 missing

    == original/features/pipeline.py (5 missing) ==
       _kl_divergence: 2/8 missing
       extract_features: 1/10 missing
       build_aggregate_baseline_profiles: 1/8 missing
       _normalise: 1/2 missing

    == original/features/tier4.py (2 missing) ==
       _shannon_entropy: 2/6 missing

    == original/features/tier16.py (2 missing) ==
       signal_verb_entropy: 1/6 missing
       citation_density_cv: 1/4 missing

    == original/features/tier9.py (1 missing) ==
       _tag_move: 1/18 missing

    == original/features/tier3.py (1 missing) ==
       theological_register_score: 1/6 missing

    == original/features/tier1.py (1 missing) ==
       _split_paragraphs: 1/6 missing

    == original/features/preprocess.py (1 missing) ==
       _extract_citation_data: 1/22 missing

    ######## CLUSTER integrations ########

    == original/lab/runner.py (22 missing) ==
       _filter_report_by_authors: 14/14 missing
       trigger_run: 4/4 missing
       _execute_run: 4/4 missing

    == original/bbook_client.py (18 missing) ==
       request_baseline: 12/12 missing
       fetch_status: 4/4 missing
       _headers: 2/2 missing

    == original/style_authorship.py (11 missing) ==
       _load_artifact: 6/14 missing
       predict_style_authorship: 3/12 missing
       content_reduced_signature: 1/4 missing
       _ensure_loaded: 1/6 missing

    == original/ai_likelihood.py (7 missing) ==
       predict_ai_likelihood_batch: 2/6 missing
       _load_artifact: 2/12 missing
       predict_ai_likelihood: 1/4 missing
       _ensure_loaded: 1/6 missing
       _band: 1/4 missing

    == original/fusion/peers.py (5 missing) ==
       _evict_oldest_locked: 4/8 missing
       build_profile: 1/8 missing

    == original/lab/suggestions.py (4 missing) ==
       generate_suggestions: 3/26 missing
       _per_author_auc: 1/6 missing

    == original/canvas/live_import.py (4 missing) ==
       get_submission_text: 4/10 missing

    == original/fusion/artifact.py (3 missing) ==
       load_artifact: 2/6 missing
       _parse: 1/20 missing

    == original/lab/datasets.py (1 missing) ==
       get_dataset: 1/2 missing

    ######## CLUSTER other ########

    == original/cli/security_audit.py (76 missing) ==
       SecurityAudit.check_raw_sql: 14/14 missing
       SecurityAudit.check_jwt_config: 10/10 missing
       SecurityAudit.check_database_security: 10/10 missing
       SecurityAudit.print_summary: 8/8 missing
       SecurityAudit.check_rate_limiting: 8/8 missing
       SecurityAudit.check_tls_readiness: 6/6 missing
       SecurityAudit.run_all_checks: 4/4 missing
       SecurityAudit.check_pip_audit: 4/4 missing
       SecurityAudit.check_input_validation: 4/4 missing
       SecurityAudit.check_cors_configuration: 4/4 missing
       SecurityAudit._print_info: 2/2 missing
       <module>: 2/2 missing

    == original/cli/delete_student.py (22 missing) ==
       delete_student_data: 14/14 missing
       _confirm_deletion: 4/4 missing
       main: 2/2 missing
       <module>: 2/2 missing

    == original/tension_arc.py (16 missing) ==
       _classify_move: 3/12 missing
       <module>: 3/4 missing
       _authenticity_signal: 2/2 missing
       _arc_flag: 2/8 missing
       _analyze_paragraph: 2/6 missing
       load_models: 1/4 missing
       analyze_tension_arc: 1/4 missing
       _syntactic_tension: 1/6 missing
       _cosine: 1/2 missing

    == original/core/config.py (16 missing) ==
       Settings.validate_production_secrets: 14/14 missing
       Settings.ALLOWED_ORIGINS: 2/2 missing

    == original/_env.py (14 missing) ==
       load_env_file: 14/14 missing

    == original/explainer.py (13 missing) ==
       explain: 10/26 missing
       _delta_intensity: 3/6 missing

    == original/voice.py (11 missing) ==
       project_headline: 3/8 missing
       project_submission_result: 2/14 missing
       _clamp01: 2/4 missing
       project_voice_notes: 1/4 missing
       project_submission_result._get: 1/4 missing
       project_review_opportunities: 1/4 missing
       _short_period: 1/2 missing

    == original/student_auth.py (11 missing) ==
       verify_launch_token: 8/8 missing
       verify_proctor_attestation: 2/10 missing
       verify_session: 1/10 missing

    == original/core/logging.py (10 missing) ==
       JSONFormatter.format: 6/6 missing
       configure_logging: 2/2 missing
       RequestLoggingMiddleware.dispatch: 2/2 missing

    == original/core/security.py (8 missing) ==
       _docs_relaxed_csp: 6/6 missing
       SecurityHeadersMiddleware.dispatch: 2/2 missing

    == original/baseline_requests.py (6 missing) ==
       mark_failed: 2/4 missing
       _persist_snapshot: 2/2 missing
       record: 1/2 missing
       mark_completed_for_student: 1/6 missing

    == original/principal.py (2 missing) ==
       verify_principal_token: 1/8 missing
       tenant_environment: 1/4 missing

    == original/backup.py (2 missing) ==
       latest_backup_age_seconds: 2/8 missing

    == original/users.py (1 missing) ==
       verify_password: 1/2 missing

    ######## CLUSTER persistence ########

    == original/postgres_repository.py (44 missing) ==
       PostgresRepository.roster_for_tenant: 6/6 missing
       PostgresRepository._status_for: 6/6 missing
       PostgresRepository.put_correction: 4/12 missing
       PostgresRepository.get_fused_scores: 4/4 missing
       PostgresRepository.manifest_stats: 3/10 missing
       PostgresRepository.delete_student: 3/8 missing
       PostgresRepository.set_display_name: 2/2 missing
       PostgresRepository.put_manifest: 2/4 missing
       PostgresRepository.list_manifests: 2/12 missing
       PostgresRepository.list_calibration_runs: 2/4 missing
       PostgresRepository.get_ai_likelihood_scores: 2/2 missing
       PostgresRepository.student_data_inventory: 1/4 missing

    == original/store.py (27 missing) ==
       _init_schema: 4/8 missing
       student_data_inventory: 3/6 missing
       put_correction: 3/12 missing
       manifest_stats: 3/10 missing
       _status_for: 3/6 missing
       _latest_actions_for: 3/6 missing
       list_manifests: 2/12 missing
       set_display_name: 1/2 missing
       put_manifest: 1/4 missing
       get_fused_scores: 1/4 missing
       delete_tenant_students: 1/4 missing
       delete_student: 1/6 missing

    == original/db/session.py (2 missing) ==
       get_engine: 2/2 missing

    == original/db/postgres_session.py (1 missing) ==
       get_engine: 1/4 missing

    ######## CLUSTER quantum ########

    == original/quantum/longitudinal.py (14 missing) ==
       analyze_longitudinal_drift: 6/20 missing
       trend_aware_typicality: 2/10 missing
       _parse_datetime: 2/6 missing
       trend_aware_typicality._reference_and_scale: 1/4 missing
       _word_count: 1/2 missing
       _forward_errors: 1/4 missing
       _change_point_diagnostic: 1/8 missing

    == original/quantum/scoring.py (12 missing) ==
       _recommend: 5/38 missing
       _characteristic_weight_factor: 2/16 missing
       score: 1/58 missing
       _llr_deviation: 1/2 missing
       _llr_action_candidates: 1/10 missing
       _length_bucket_for: 1/4 missing
       _decompose: 1/10 missing

    == original/quantum/state.py (8 missing) ==
       _ledoit_wolf_shrink: 4/4 missing
       StudentState.check_drift: 2/14 missing
       StudentState._compute_trajectory: 1/4 missing
       StudentState._build_density_matrix: 1/6 missing

    == original/quantum/amplitude.py (2 missing) ==
       interference_components: 2/12 missing

    == original/quantum/typicality.py (1 missing) ==
       p_central: 1/2 missing

    == original/quantum/professor_narrative.py (1 missing) ==
       build_professor_explanation: 1/12 missing

    == original/quantum/pooled_calibration.py (1 missing) ==
       pooled_reference_stats: 1/2 missing

    == original/quantum/null_pool.py (1 missing) ==
       fit_impostor_gaussian: 1/2 missing
