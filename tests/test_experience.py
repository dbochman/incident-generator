from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

from incident_generator import experience as experience_module
from incident_generator.experience import build_tail_experience, run_follow_experience, run_tail_experience
from incident_generator.experience_challenge import _prompt_choice_with_selector, build_tail_challenge, run_tail_challenge


ROOT = Path(__file__).resolve().parents[1]


class ExperienceTailTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "incident_generator", *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_minimal_events_ndjson_replays_chronologically_and_redacts_hidden_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            _write_ndjson(
                artifact_dir / "events.ndjson",
                [
                    {
                        "timestamp": "2026-05-06T00:00:02Z",
                        "stream": "evidence",
                        "event_type": "tool_result",
                        "summary": "evidence retained token=super-secret expected_hypotheses=hidden",
                    },
                    {
                        "timestamp": "2026-05-06T00:00:00Z",
                        "stream": "agent",
                        "event_type": "session_start",
                        "summary": "responder starts from alert",
                    },
                    {
                        "timestamp": "2026-05-06T00:00:01Z",
                        "stream": "inspect",
                        "event_type": "tool_request",
                        "summary": "inspect service logs",
                    },
                ],
            )
            output_dir = Path(tmp) / "out"
            result = self.run_cli(
                "experience",
                "--artifact-dir",
                str(artifact_dir),
                "--output-dir",
                str(output_dir),
                "--generated-at",
                "2026-05-06T00:00:00Z",
                "--no-sleep",
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            lines = result.stdout.strip().splitlines()
            self.assertEqual([line.split("] ", 1)[0].split("[", 1)[1] for line in lines], ["agent", "inspect", "evidence"])
            rendered = result.stdout + (output_dir / "timeline.ndjson").read_text(encoding="utf-8")
            self.assertNotIn("expected_hypotheses", rendered)
            self.assertNotIn("super-secret", rendered)
            experience = json.loads((output_dir / "experience.json").read_text(encoding="utf-8"))
            self.assertEqual(experience["source_mode"], "events_ndjson")
            self.assertEqual(experience["event_count"], 3)

    def test_v2_investigation_transcript_is_preferred_over_events_ndjson(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            case_dir = artifact_dir / "cases" / "case-a"
            case_dir.mkdir(parents=True)
            _write_ndjson(
                artifact_dir / "events.ndjson",
                [{"timestamp": "2026-05-06T00:00:00Z", "stream": "agent", "summary": "fallback event"}],
            )
            _write_ndjson(
                case_dir / "investigation-transcript.ndjson",
                [
                    _transcript_event(1, "agent", "session_start", "agent starts from alert"),
                    _transcript_event(2, "inspect", "tool_request", "database.pool_status"),
                    _transcript_event(3, "evidence", "tool_result", "ev-0001 pool status returned"),
                ],
            )

            payload, timeline = build_tail_experience(
                artifact_dir,
                generated_at="2026-05-06T00:00:00Z",
                speed=1.0,
                max_gap_seconds=30,
            )

            self.assertEqual(payload["source_mode"], "sandboxed_investigation_session")
            self.assertEqual([event["stream"] for event in timeline], ["agent", "inspect", "evidence"])
            self.assertNotIn("fallback event", "\n".join(event["line"] for event in timeline))

    def test_gap_lines_are_inserted_and_sleep_is_capped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            _write_ndjson(
                artifact_dir / "events.ndjson",
                [
                    {"timestamp": "2026-05-06T00:00:00Z", "stream": "agent", "summary": "start"},
                    {"timestamp": "2026-05-06T00:02:00Z", "stream": "evidence", "summary": "late evidence"},
                ],
            )

            _payload, timeline = build_tail_experience(
                artifact_dir,
                generated_at="2026-05-06T00:00:00Z",
                speed=2.0,
                max_gap_seconds=30.0,
            )

            self.assertEqual([event["stream"] for event in timeline], ["agent", "gap", "evidence"])
            self.assertIn("2m00s later", timeline[1]["line"])
            self.assertEqual(timeline[2]["sleep_seconds"], 30.0)
            self.assertTrue(all(event["source_ref"] for event in timeline))

    def test_no_play_writes_byte_stable_artifacts_without_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            _write_ndjson(
                artifact_dir / "events.ndjson",
                [{"elapsed_ms": 250, "stream": "agent", "summary": "start"}],
            )
            first = Path(tmp) / "out-1"
            second = Path(tmp) / "out-2"

            for output_dir in [first, second]:
                result = self.run_cli(
                    "experience",
                    "--artifact-dir",
                    str(artifact_dir),
                    "--output-dir",
                    str(output_dir),
                    "--generated-at",
                    "2026-05-06T00:00:00Z",
                    "--no-sleep",
                    "--no-play",
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(result.stdout, "")

            self.assertEqual((first / "experience.json").read_bytes(), (second / "experience.json").read_bytes())
            self.assertEqual((first / "timeline.ndjson").read_bytes(), (second / "timeline.ndjson").read_bytes())

    def test_v1_trace_fallback_is_marked_as_compatibility_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "trace.json").write_text(
                json.dumps(
                    {
                        "schema_version": "incident-generator.benchmark-runner-trace/v1",
                        "cases": [
                            {
                                "case_id": "case-v1",
                                "agent_prompt": {
                                    "source_mode": "redacted_evidence_bundle",
                                    "evidence_items": [
                                        {
                                            "title": "DB pool",
                                            "adapter_id": "database.pool_status",
                                        }
                                    ],
                                },
                                "agent_response": {
                                    "hypotheses_ranked": [
                                        {"summary": "Database pool exhaustion", "confidence": "high"}
                                    ]
                                },
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            lines: list[str] = []
            payload = run_tail_experience(
                artifact_dir,
                generated_at="2026-05-06T00:00:00Z",
                no_sleep=True,
                stream=_ListStream(lines),
            )

            rendered = "\n".join(lines)
            self.assertEqual(payload["source_mode"], "redacted_evidence_bundle")
            self.assertIn("compatibility replay", rendered)
            self.assertNotIn("preassembled evidence bundle", rendered)
            self.assertNotIn("tool_request", rendered)

    def test_v2_benchmark_artifacts_add_action_gate_and_judge_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            case_dir = artifact_dir / "cases" / "case-a"
            case_dir.mkdir(parents=True)
            _write_ndjson(
                case_dir / "investigation-transcript.ndjson",
                [
                    _transcript_event(1, "agent", "session_start", "responder starts from alert"),
                    _transcript_event(2, "inspect", "tool_request", "service.error_logs"),
                    _transcript_event(3, "evidence", "tool_result", "ev-0001 service errors returned"),
                    _transcript_event(4, "agent", "final_response", "canary rollout is causing 5xx"),
                ],
            )
            (artifact_dir / "trace.json").write_text(
                json.dumps(
                    {
                        "schema_version": "incident-generator.benchmark-runner-trace/v1",
                        "cases": [
                            {
                                "case_id": "case-a",
                                "state": "passed",
                                "source_mode": "sandboxed_investigation_session",
                                "session_start_ref": "cases/case-a/session-start.json",
                                "response_ref": "cases/case-a/response.json",
                                "investigation_transcript_ref": "cases/case-a/investigation-transcript.ndjson",
                                "agent_prompt": {
                                    "input_mode": "sandboxed_investigation_session",
                                    "initial_alert": {"symptom": "checkout 5xx spike"},
                                    "tool_catalog": [{"tool_id": "service.error_logs"}],
                                    "expected_hypotheses": ["hidden answer"],
                                },
                                "investigation_transcript": [],
                                "agent_response": {
                                    "hypotheses_ranked": [{"summary": "canary rollout is causing 5xx"}],
                                    "proposed_actions": [
                                        {
                                            "action_id": "inspect_only",
                                            "summary": "Keep investigation read-only",
                                            "action_class": 1,
                                        }
                                    ],
                                },
                                "judge": {
                                    "outcome": {"status": "executed", "verdict": "pass", "score": 1},
                                    "scoring": {"overall_pass": True, "scoring_labels": ["causal"]},
                                },
                            }
                        ],
                    },
                    sort_keys=True,
                ),
                encoding="utf-8",
            )

            payload, timeline = build_tail_experience(
                artifact_dir,
                generated_at="2026-05-06T00:00:00Z",
                speed=1.0,
                max_gap_seconds=30,
            )

            streams = {event["stream"] for event in timeline}
            rendered = "\n".join(event["line"] for event in timeline)
            self.assertEqual(payload["source_mode"], "sandboxed_investigation_session")
            self.assertTrue({"agent", "inspect", "evidence", "action", "gate", "judge"}.issubset(streams))
            self.assertIn("[judge]", rendered)
            self.assertIn("[gate]", rendered)
            self.assertNotIn("expected_hypotheses", rendered)
            self.assertNotIn("causal", rendered)
            self.assertTrue(all(event["source_ref"] for event in timeline))

    def test_benchmark_result_metadata_produces_read_only_inspect_and_evidence_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "result.json").write_text(
                json.dumps(
                    {
                        "schema_version": "incident-generator.benchmark-result/v1",
                        "cases": [
                            {
                                "case_id": "provider-contract-case",
                                "expectations": {
                                    "expected_hypotheses": ["hidden answer"],
                                    "internal_evidence_roles": [{"role": "causal"}],
                                },
                                "generated_incident": {
                                    "collection_mode": "fixture",
                                    "generation_state": "passed",
                                    "artifact_refs": [
                                        {
                                            "kind": "provider_contract",
                                            "ref": "fixtures/provider-contract.json",
                                            "sha256": "abc",
                                        }
                                    ],
                                },
                            }
                        ],
                        "results": [
                            {
                                "case_id": "provider-contract-case",
                                "state": "passed",
                                "agent_output_ref": "cases/provider-contract-case/response.json",
                                "diagnosis": {"evidence_refs": ["ev-0001", "service.error_logs"]},
                                "judge_outcome": {"status": "executed", "verdict": "pass"},
                                "scoring": {"overall_pass": True, "scoring_labels": ["causal"]},
                            }
                        ],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            payload, timeline = build_tail_experience(
                artifact_dir,
                generated_at="2026-05-06T00:00:00Z",
                speed=1.0,
                max_gap_seconds=30,
            )

            streams = {event["stream"] for event in timeline}
            rendered = "\n".join(event["line"] for event in timeline)
            self.assertEqual(payload["source_mode"], "benchmark_result")
            self.assertTrue({"agent", "inspect", "evidence", "gate", "judge"}.issubset(streams))
            self.assertIn("read-only artifact provider_contract", rendered)
            self.assertIn("read-only evidence refs cited", rendered)
            self.assertNotIn("expected_hypotheses", rendered)
            self.assertNotIn("internal_evidence_roles", rendered)
            self.assertNotIn("causal", rendered)
            self.assertTrue(all(event["source_ref"] for event in timeline))

    def test_dashboard_result_and_noisy_metadata_produce_background_streams_without_hidden_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "dashboard.json").write_text(
                json.dumps(
                    {
                        "schema_version": "incident-generator.progress-dashboard/v1",
                        "status": "ok",
                        "failure_class": "none",
                        "elapsed_ms": 4000,
                        "live_look": {
                            "timeline": [
                                {
                                    "elapsed": "00:01",
                                    "phase": "validate",
                                    "status": "ok",
                                    "message": "scenario contract is valid",
                                    "detail": "-",
                                }
                            ],
                            "system_health": [
                                {
                                    "elapsed": "00:02",
                                    "source": "checkout-api",
                                    "signal": "service.error_logs",
                                    "status": "observed",
                                    "detail": "canary returned 503",
                                },
                                {
                                    "elapsed": "00:03",
                                    "source": "checkout-api",
                                    "signal": "http_endpoint_status",
                                    "status": "matched",
                                    "detail": "503",
                                },
                                {
                                    "elapsed": "00:04",
                                    "source": "postgres",
                                    "signal": "database.pool",
                                    "status": "high",
                                    "detail": "pool 100 percent",
                                },
                            ],
                        },
                        "wait_predicates": [
                            {
                                "elapsed": "00:03",
                                "scenario": "service-http-5xx-spike-canary-rollout",
                                "kind": "http_endpoint_status",
                                "status": "observed",
                                "observed": "503",
                            }
                        ],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (artifact_dir / "result.json").write_text(
                json.dumps(
                    {
                        "scenario": "service-http-5xx-spike-canary-rollout",
                        "collection_mode": "real",
                        "environment_archetype": "kind",
                        "service_id": "checkout-api",
                        "generated": True,
                        "blocked": False,
                        "failure_class": "none",
                        "expected_hypotheses": ["hidden answer"],
                        "context": {"provider_profile": "harness-local"},
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (artifact_dir / "loadgen-preview.json").write_text(
                json.dumps(
                    {
                        "duration_seconds": 10,
                        "concurrency": 2,
                        "counts_by_route": {"checkout": 20, "search": 10},
                        "requests": [
                            {"due_ms": 0, "route": "checkout", "url": "http://checkout"},
                            {"due_ms": 50, "route": "search", "url": "http://search"},
                        ],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            (artifact_dir / "noisy-smoke-report.json").write_text(
                json.dumps(
                    {
                        "schema_version": "sre-agent.noisy-smoke-report/v1",
                        "target": {
                            "main_service": "checkout-api",
                            "workload": "kind/ecommerce-lite",
                            "load_generator": {"rps": 24},
                        },
                        "coverage": {"expected_hypotheses": ["hidden answer"]},
                        "scenarios": [
                            {
                                "scenario": "service-http-5xx-spike-canary-rollout",
                                "expected_hypothesis": "hidden answer",
                                "noisy_fixture": {
                                    "evidence_count": 17,
                                    "signal_role_counts": {"causal": 8, "ambient": 9},
                                },
                                "workload_profile": {"noise_profile_id": "api-noise"},
                            }
                        ],
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            payload, timeline = build_tail_experience(
                artifact_dir,
                generated_at="2026-05-06T00:00:00Z",
                speed=1.0,
                max_gap_seconds=30,
            )

            streams = {event["stream"] for event in timeline}
            rendered = "\n".join(event["line"] for event in timeline)
            self.assertEqual(payload["source_mode"], "progress_dashboard")
            self.assertTrue({"logs", "metrics", "traffic", "inspect", "evidence", "gate"}.issubset(streams))
            self.assertIn("background workload", rendered)
            self.assertIn("retained incident symptom context", rendered)
            self.assertNotIn("expected_hypotheses", rendered)
            self.assertNotIn("expected_hypothesis", rendered)
            self.assertNotIn("signal_role_counts", rendered)
            self.assertNotIn("causal", rendered)
            self.assertNotIn("ambient", rendered)
            self.assertTrue(all(event["source_ref"] for event in timeline))

    def test_manual_challenge_prompts_for_multiple_choice_and_retains_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            _write_manual_challenge_artifacts(artifact_dir)
            output_dir = Path(tmp) / "challenge-out"
            payload, timeline = build_tail_experience(
                artifact_dir,
                generated_at="2026-05-06T00:00:00Z",
                speed=1.0,
                max_gap_seconds=30,
            )
            plan = build_tail_challenge(artifact_dir, payload, timeline)
            answers = [
                _choice_number(plan, "primary_diagnosis", plan.answer_key["primary_diagnosis"]),
                1,
                _choice_number(plan, "safest_next_step", plan.answer_key["safest_next_step"]),
            ]
            lines: list[str] = []

            run = run_tail_challenge(
                ROOT,
                artifact_dir,
                output_dir=output_dir,
                generated_at="2026-05-06T00:00:00Z",
                no_sleep=True,
                no_play=False,
                answers=answers,
                stream=_ListStream(lines),
            )

            rendered = "\n".join(lines)
            pre_prompt = rendered.split("Manual response", 1)[0]
            self.assertIn("Answer with a choice number; JSON is not required.", rendered)
            self.assertIn("Expected answers", rendered)
            self.assertIn("Score context", rendered)
            self.assertIn("database connection pool exhaustion is causing checkout failures", rendered)
            self.assertNotIn("{", rendered)
            self.assertNotIn("baseline agent answer should be hidden", pre_prompt)
            self.assertNotIn("[judge]", pre_prompt)
            self.assertNotIn("benchmark gate", pre_prompt)
            for name in [
                "experience.json",
                "timeline.ndjson",
                "challenge.json",
                "answers.json",
                "response.json",
                "challenge-exchange.json",
                "challenge-result.json",
                "transcript.md",
            ]:
                self.assertTrue((output_dir / name).is_file(), name)
            challenge = json.loads((output_dir / "challenge.json").read_text(encoding="utf-8"))
            challenge_rendered = json.dumps(challenge, sort_keys=True)
            self.assertNotIn("expected_hypotheses", challenge_rendered)
            self.assertNotIn("forbidden_hypotheses", challenge_rendered)
            self.assertNotIn("answer_key", challenge_rendered)
            self.assertNotIn("is_correct", challenge_rendered)
            response = json.loads((output_dir / "response.json").read_text(encoding="utf-8"))
            self.assertEqual(response["schema_version"], "incident-generator.agent-investigation-final-response/v2")
            self.assertEqual(response["hypotheses_ranked"][0]["evidence_refs"], ["ev-0001"])
            self.assertEqual([item["evidence_id"] for item in response["evidence_refs"]], ["ev-0001"])
            result = json.loads((output_dir / "challenge-result.json").read_text(encoding="utf-8"))
            self.assertTrue(result["results"][0]["scoring"]["overall_pass"])
            self.assertTrue(run["result"]["results"][0]["scoring"]["evidence_reference_pass"])

    def test_manual_challenge_scores_incorrect_primary_choice_as_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            _write_manual_challenge_artifacts(artifact_dir)
            output_dir = Path(tmp) / "challenge-out"
            payload, timeline = build_tail_experience(
                artifact_dir,
                generated_at="2026-05-06T00:00:00Z",
                speed=1.0,
                max_gap_seconds=30,
            )
            plan = build_tail_challenge(artifact_dir, payload, timeline)
            correct = _choice_number(plan, "primary_diagnosis", plan.answer_key["primary_diagnosis"])
            wrong = 1 if correct != 1 else 2

            run_tail_challenge(
                ROOT,
                artifact_dir,
                output_dir=output_dir,
                generated_at="2026-05-06T00:00:00Z",
                no_sleep=True,
                no_play=True,
                answers=[wrong, 1, _choice_number(plan, "safest_next_step", plan.answer_key["safest_next_step"])],
                stream=_ListStream([]),
            )

            result = json.loads((output_dir / "challenge-result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["results"][0]["state"], "failed")
            self.assertFalse(result["results"][0]["scoring"]["hypothesis_pass"])

    def test_manual_challenge_can_reveal_expected_answers_without_prompting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            _write_manual_challenge_artifacts(artifact_dir)
            output_dir = Path(tmp) / "challenge-out"
            lines: list[str] = []

            run = run_tail_challenge(
                ROOT,
                artifact_dir,
                output_dir=output_dir,
                generated_at="2026-05-06T00:00:00Z",
                no_sleep=True,
                no_play=True,
                reveal_answers=True,
                stream=_ListStream(lines),
            )

            rendered = "\n".join(lines)
            self.assertNotIn("Manual response", rendered)
            self.assertNotIn("Answer with a choice number", rendered)
            self.assertIn("Questions", rendered)
            self.assertIn("Press Enter to reveal answers.", rendered)
            self.assertIn("Answer reveal scored: state=passed overall_pass=True", rendered)
            self.assertIn("Revealed answers", rendered)
            self.assertIn("database connection pool exhaustion is causing checkout failures", rendered)
            self.assertNotIn(": 3 database connection pool exhaustion", rendered)
            answers = json.loads((output_dir / "answers.json").read_text(encoding="utf-8"))
            self.assertEqual(answers["answer_format"], "revealed_expected_choices")
            self.assertEqual(answers["selections"][0]["selection_source"], "revealed_expected_answer")
            result = json.loads((output_dir / "challenge-result.json").read_text(encoding="utf-8"))
            self.assertTrue(result["results"][0]["scoring"]["overall_pass"])
            self.assertTrue(run["result"]["results"][0]["scoring"]["hypothesis_pass"])

    def test_manual_challenge_selector_accepts_arrows_and_numeric_jump(self) -> None:
        choices = [
            {"choice_id": "choice-1", "label": "first"},
            {"choice_id": "choice-2", "label": "second"},
            {"choice_id": "choice-3", "label": "third"},
        ]
        arrow_keys = iter(["down", "down", "up", "enter"])
        arrow_lines: list[str] = []
        selected = _prompt_choice_with_selector(
            sys.stdin,
            _ListStream(arrow_lines),
            choices,
            read_key=lambda: next(arrow_keys),
            use_ansi=False,
        )
        self.assertEqual(selected, 2)
        arrow_rendered = "\n".join(arrow_lines)
        self.assertIn("> 2. second", arrow_rendered)
        self.assertNotIn("\033", arrow_rendered)

        number_keys = iter(["3", "enter"])
        number_lines: list[str] = []
        selected = _prompt_choice_with_selector(
            sys.stdin,
            _ListStream(number_lines),
            choices,
            read_key=lambda: next(number_keys),
            use_ansi=False,
        )
        self.assertEqual(selected, 3)
        self.assertIn("Selected 3. third", "\n".join(number_lines))

    def test_manual_challenge_cli_accepts_numeric_answers_without_json_submission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            _write_manual_challenge_artifacts(artifact_dir)
            output_dir = Path(tmp) / "challenge-out"

            result = self.run_cli(
                "experience",
                "--artifact-dir",
                str(artifact_dir),
                "--mode",
                "challenge",
                "--output-dir",
                str(output_dir),
                "--generated-at",
                "2026-05-06T00:00:00Z",
                "--no-sleep",
                "--no-play",
                "--answers",
                "1,1,1",
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Answer with a choice number; JSON is not required.", result.stdout)
            self.assertTrue((output_dir / "response.json").is_file())

    def test_manual_challenge_cli_can_reveal_answers_without_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            _write_manual_challenge_artifacts(artifact_dir)
            output_dir = Path(tmp) / "challenge-out"

            result = self.run_cli(
                "experience",
                "--artifact-dir",
                str(artifact_dir),
                "--mode",
                "challenge",
                "--output-dir",
                str(output_dir),
                "--generated-at",
                "2026-05-06T00:00:00Z",
                "--no-sleep",
                "--no-play",
                "--reveal-answers",
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("Press Enter to reveal answers.", result.stdout)
            self.assertIn("Answer reveal scored: state=passed overall_pass=True", result.stdout)
            self.assertNotIn("Manual response", result.stdout)
            self.assertNotIn(": 3 database connection pool exhaustion", result.stdout)
            self.assertEqual(
                json.loads((output_dir / "answers.json").read_text(encoding="utf-8"))["answer_format"],
                "revealed_expected_choices",
            )

    def test_follow_mode_streams_appended_events_and_writes_replay_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            events_path = artifact_dir / "events.ndjson"
            _append_ndjson(
                events_path,
                [{"elapsed_ms": 0, "phase": "run", "status": "started", "message": "incident run started"}],
            )
            output_dir = Path(tmp) / "follow-out"
            lines: list[str] = []

            def append_later() -> None:
                time.sleep(0.05)
                _append_ndjson(
                    events_path,
                    [
                        {
                            "elapsed_ms": 100,
                            "phase": "wait",
                            "status": "observed",
                            "message": "service 5xx observed expected_hypotheses=hidden",
                        },
                        {
                            "elapsed_ms": 200,
                            "phase": "run",
                            "status": "ok",
                            "message": "incident generation complete",
                        },
                    ],
                )

            thread = threading.Thread(target=append_later)
            thread.start()
            try:
                payload = run_follow_experience(
                    artifact_dir,
                    output_dir=output_dir,
                    generated_at="2026-05-06T00:00:00Z",
                    poll_interval_seconds=0.01,
                    timeout_seconds=2.0,
                    stream=_ListStream(lines),
                )
            finally:
                thread.join(timeout=1.0)

            rendered = "\n".join(lines)
            self.assertEqual(payload["mode"], "follow")
            self.assertEqual(payload["follow"]["state"], "completed")
            self.assertIn("incident run started", rendered)
            self.assertIn("service 5xx observed", rendered)
            self.assertIn("incident generation complete", rendered)
            self.assertNotIn("expected_hypotheses", rendered)
            self.assertTrue((output_dir / "experience.json").is_file())
            self.assertTrue((output_dir / "timeline.ndjson").is_file())
            experience = json.loads((output_dir / "experience.json").read_text(encoding="utf-8"))
            self.assertEqual(experience["mode"], "follow")
            self.assertEqual(experience["follow"]["state"], "completed")
            self.assertEqual(experience["event_count"], 3)

    def test_follow_mode_falls_back_to_post_run_replay_when_events_are_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            (artifact_dir / "result.json").write_text(
                json.dumps(
                    {
                        "scenario": "service-http-5xx-spike-canary-rollout",
                        "collection_mode": "real",
                        "environment_archetype": "kind",
                        "service_id": "checkout-api",
                        "generated": True,
                        "blocked": False,
                        "failure_class": "none",
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            output_dir = Path(tmp) / "follow-out"

            result = self.run_cli(
                "experience",
                "--artifact-dir",
                str(artifact_dir),
                "--mode",
                "follow",
                "--output-dir",
                str(output_dir),
                "--generated-at",
                "2026-05-06T00:00:00Z",
                "--follow-timeout-seconds",
                "1",
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("retained incident symptom context", result.stdout)
            experience = json.loads((output_dir / "experience.json").read_text(encoding="utf-8"))
            self.assertEqual(experience["mode"], "follow")
            self.assertEqual(experience["follow"]["state"], "fallback_replay")

    def test_follow_mode_retained_state_matches_completion_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()
            _append_ndjson(
                artifact_dir / "events.ndjson",
                [{"elapsed_ms": 0, "phase": "run", "status": "started", "message": "incident run started"}],
            )
            output_dir = Path(tmp) / "follow-out"
            calls = 0
            original = experience_module._follow_is_complete

            def fake_complete(_artifact_dir, _rows):
                nonlocal calls
                calls += 1
                return calls >= 2

            try:
                experience_module._follow_is_complete = fake_complete
                payload = run_follow_experience(
                    artifact_dir,
                    output_dir=output_dir,
                    generated_at="2026-05-06T00:00:00Z",
                    poll_interval_seconds=0,
                    timeout_seconds=1,
                    no_play=True,
                    sleep_func=lambda _seconds: None,
                )
            finally:
                experience_module._follow_is_complete = original

            self.assertEqual(payload["follow"]["state"], "completed")
            experience = json.loads((output_dir / "experience.json").read_text(encoding="utf-8"))
            self.assertEqual(experience["follow"]["state"], "completed")


def _write_ndjson(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def _append_ndjson(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        handle.flush()


def _transcript_event(seq: int, stream: str, event_type: str, summary: str) -> dict:
    return {
        "schema_version": "incident-generator.agent-investigation-transcript-event/v2",
        "type": "transcript_event",
        "event_id": f"evt-{seq:04d}",
        "request_id": "request-1",
        "session_id": "session-1",
        "seq": seq,
        "timestamp": f"2026-05-06T00:00:0{seq}Z",
        "stream": stream,
        "event_type": event_type,
        "summary": summary,
        "source_ref": "investigation-transcript.ndjson",
        "redacted": True,
        "hidden_answer_material_visible": False,
        "data": {},
    }


def _write_manual_challenge_artifacts(artifact_dir: Path) -> None:
    case_dir = artifact_dir / "cases" / "manual-case"
    case_dir.mkdir(parents=True)
    _write_ndjson(
        case_dir / "investigation-transcript.ndjson",
        [
            _transcript_event(1, "agent", "session_start", "responder starts from alert"),
            _transcript_event(2, "inspect", "tool_request", "database.pool_status"),
            {
                **_transcript_event(3, "evidence", "tool_result", "ev-0001 pool saturation returned"),
                "data": {"evidence_id": "ev-0001", "tool_id": "database.pool_status"},
            },
            _transcript_event(4, "agent", "final_response", "baseline agent answer should be hidden"),
        ],
    )
    (artifact_dir / "result.json").write_text(
        json.dumps(
            {
                "schema_version": "incident-generator.benchmark-result/v1",
                "benchmark_set": {
                    "benchmark_set_id": "manual-tail-fixture",
                    "name": "Manual tail fixture",
                    "seed": None,
                    "collection_modes": ["fixture"],
                    "case_count": 1,
                    "source_refs": [],
                },
                "created_at": "2026-05-06T00:00:00Z",
                "cases": [
                    {
                        "case_id": "manual-case",
                        "generated_incident": {
                            "incident_run_id": "incident-manual-case",
                            "scenario_ids": ["database-connection-exhaustion-pool-exhausted"],
                            "combination_size": 1,
                            "archetype": "fixture",
                            "collection_mode": "fixture",
                            "generation_state": "passed",
                            "failure_class": "none",
                            "artifact_refs": [],
                        },
                        "expectations": {
                            "expected_hypotheses": [
                                "database connection pool exhaustion is causing checkout failures"
                            ],
                            "forbidden_hypotheses": ["DNS or TLS failure at the service edge"],
                            "required_abstention": False,
                            "uncertainty_expected": False,
                            "false_attribution_guards": ["do not attribute the incident to DNS or TLS"],
                            "evidence_role_expectations": [{"role": "causal", "expected_count": 1}],
                        },
                    }
                ],
                "entrants": [],
                "results": [
                    {
                        "case_id": "manual-case",
                        "state": "passed",
                        "agent_output_ref": "cases/manual-case/response.json",
                        "diagnosis": {"evidence_refs": ["ev-0001"]},
                        "judge_outcome": {"status": "executed", "verdict": "pass"},
                        "scoring": {"overall_pass": True, "scoring_labels": ["causal"]},
                    }
                ],
                "aggregate": {},
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def _choice_number(plan, question_id: str, choice_id: str) -> int:
    for question in plan.challenge["questions"]:
        if question["question_id"] != question_id:
            continue
        for index, choice in enumerate(question["choices"], start=1):
            if choice["choice_id"] == choice_id:
                return index
    raise AssertionError(f"choice not found: {question_id} {choice_id}")


class _ListStream:
    def __init__(self, lines: list[str]):
        self.lines = lines

    def write(self, value: str) -> int:
        if value.strip():
            self.lines.append(value.rstrip("\n"))
        return len(value)

    def flush(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
