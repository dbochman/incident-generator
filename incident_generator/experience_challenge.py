"""Manual multiple-choice challenge mode for terminal tail experiences."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from .benchmark_runner import build_benchmark_result
from .experience import (
    ExperienceError,
    HIDDEN_ANSWER_FIELDS,
    build_tail_experience,
    play_tail_timeline,
    write_experience_artifacts,
)
from .parsers import redact


CHALLENGE_SCHEMA_VERSION = "incident-generator.manual-tail-challenge/v1"
ANSWERS_SCHEMA_VERSION = "incident-generator.manual-tail-challenge-answers/v1"
EXCHANGE_SCHEMA_VERSION = "incident-generator.manual-tail-challenge-exchange/v1"

_POST_ANSWER_EVENT_TYPES = {
    "benchmark_gate",
    "final_response",
    "judge_outcome",
    "proposed_action",
    "result_state",
}
_PRIMARY_QUESTION_ID = "primary_diagnosis"
_CONFIDENCE_QUESTION_ID = "confidence"
_NEXT_STEP_QUESTION_ID = "safest_next_step"


@dataclass(frozen=True)
class ManualChallengePlan:
    challenge: dict[str, Any]
    case: dict[str, Any]
    answer_key: dict[str, str]
    choice_values: dict[str, dict[str, Any]]
    discovered_evidence_ids: list[str]


def parse_challenge_answers(value: str | None) -> list[int] | None:
    """Parse comma or whitespace separated one-based choice numbers."""

    if value is None:
        return None
    parts = [part for part in re.split(r"[\s,]+", value.strip()) if part]
    if not parts:
        raise ExperienceError("--answers must include at least one numeric choice")
    answers: list[int] = []
    for part in parts:
        try:
            selected = int(part)
        except ValueError as exc:
            raise ExperienceError(f"--answers contains a non-numeric choice: {part}") from exc
        if selected < 1:
            raise ExperienceError("--answers choices are one-based and must be greater than zero")
        answers.append(selected)
    return answers


def run_tail_challenge(
    root: Path,
    artifact_dir: Path,
    *,
    output_dir: Path | None = None,
    generated_at: str | None = None,
    speed: float = 1.0,
    max_gap_seconds: float = 30.0,
    no_sleep: bool = False,
    no_play: bool = False,
    answers: list[int] | None = None,
    reveal_answers: bool = False,
    stream: TextIO | None = None,
    input_stream: TextIO | None = None,
) -> dict[str, Any]:
    """Replay investigation evidence, collect or reveal choices, and score the generated response."""

    stream = stream or sys.stdout
    if reveal_answers and answers is not None:
        raise ExperienceError("--answers cannot be combined with --reveal-answers")
    output_dir = output_dir or artifact_dir / "manual-tail-challenge"
    output_dir.mkdir(parents=True, exist_ok=True)
    experience_payload, timeline = build_tail_experience(
        artifact_dir,
        generated_at=generated_at,
        speed=speed,
        max_gap_seconds=max_gap_seconds,
    )
    visible_timeline = _pre_answer_timeline(timeline)
    challenge_experience = dict(experience_payload)
    challenge_experience["mode"] = "challenge"
    challenge_experience["event_count"] = len(visible_timeline)
    challenge_experience["filtered_event_count"] = len(timeline) - len(visible_timeline)
    challenge_experience["artifacts"] = {
        "experience": "experience.json",
        "timeline": "timeline.ndjson",
        "challenge": "challenge.json",
        "answers": "answers.json",
        "response": "response.json",
        "exchange": "challenge-exchange.json",
        "result": "challenge-result.json",
        "transcript": "transcript.md",
    }
    write_experience_artifacts(output_dir, challenge_experience, visible_timeline)
    if not no_play:
        play_tail_timeline(visible_timeline, no_sleep=no_sleep, stream=stream)

    plan = build_tail_challenge(artifact_dir, challenge_experience, visible_timeline)
    _write_json(output_dir / "challenge.json", plan.challenge)
    if reveal_answers:
        _pause_for_answer_reveal(plan.challenge, stream=stream, input_stream=input_stream or sys.stdin)
        selections = _revealed_expected_selections(plan)
    else:
        selections = _collect_answers(
            plan.challenge,
            answers=answers,
            stream=stream,
            input_stream=input_stream or sys.stdin,
        )
    response_path = output_dir / "response.json"
    response_ref = _relative_path(root, response_path)
    response = _response_from_answers(
        plan,
        selections,
        created_at=challenge_experience["generated_at"],
        response_ref=response_ref,
    )
    _write_json(response_path, response)
    answers_payload = _answers_payload(
        plan.challenge,
        selections,
        generated_at=challenge_experience["generated_at"],
        answer_format="revealed_expected_choices" if reveal_answers else "multiple_choice_numbers",
    )
    _write_json(output_dir / "answers.json", answers_payload)
    exchange = _exchange_payload(plan, response)
    exchange_path = output_dir / "challenge-exchange.json"
    _write_json(exchange_path, exchange)
    result = _score_manual_response(
        root,
        plan,
        exchange=exchange,
        exchange_path=exchange_path,
        response=response,
        response_path=response_path,
        output_dir=output_dir,
        created_at=challenge_experience["generated_at"],
    )
    _write_json(output_dir / "challenge-result.json", result)
    _write_text(
        output_dir / "transcript.md",
        _challenge_transcript(visible_timeline, plan, selections, result, reveal_answers=reveal_answers),
    )
    _print_score_summary(plan, selections, result, output_dir=output_dir, stream=stream, reveal_answers=reveal_answers)
    return {
        "schema_version": "incident-generator.manual-tail-challenge-run/v1",
        "challenge": plan.challenge,
        "answers": answers_payload,
        "response": response,
        "result": result,
        "output_dir": str(output_dir),
    }


def build_tail_challenge(
    artifact_dir: Path,
    experience_payload: Mapping[str, Any],
    timeline: list[Mapping[str, Any]],
) -> ManualChallengePlan:
    """Build the user-visible challenge and keep scoring material out of the challenge payload."""

    case = _load_benchmark_case(artifact_dir)
    discovered_evidence_ids = _discovered_evidence_ids(artifact_dir)
    challenge_id = f"manual-tail-challenge-{_safe_name(case['case_id'])}"
    choices, primary_key, choice_values = _primary_choices(case)
    confidence_choices, confidence_key, confidence_values = _confidence_choices(case)
    next_step_choices, next_step_key, next_step_values = _next_step_choices()
    choice_values.update(confidence_values)
    choice_values.update(next_step_values)
    questions = [
        {
            "question_id": _PRIMARY_QUESTION_ID,
            "prompt": "Which diagnosis is best supported by the tail?",
            "choices": choices,
        },
        {
            "question_id": _CONFIDENCE_QUESTION_ID,
            "prompt": "How confident should the response be?",
            "choices": confidence_choices,
        },
        {
            "question_id": _NEXT_STEP_QUESTION_ID,
            "prompt": "What is the safest next response?",
            "choices": next_step_choices,
        },
    ]
    challenge = {
        "schema_version": CHALLENGE_SCHEMA_VERSION,
        "challenge_id": challenge_id,
        "mode": "tail_challenge",
        "source_mode": experience_payload.get("source_mode"),
        "artifact_dir": experience_payload.get("artifact_dir"),
        "generated_at": experience_payload.get("generated_at"),
        "case_id": case["case_id"],
        "instructions": "Answer with the number for each choice.",
        "timeline_event_count": len(timeline),
        "discovered_evidence_ids": discovered_evidence_ids,
        "questions": questions,
        "artifacts": {
            "experience": "experience.json",
            "timeline": "timeline.ndjson",
            "answers": "answers.json",
            "response": "response.json",
            "exchange": "challenge-exchange.json",
            "result": "challenge-result.json",
            "transcript": "transcript.md",
        },
    }
    _assert_no_hidden_answer_keys(challenge, label="challenge")
    answer_key = {
        _PRIMARY_QUESTION_ID: primary_key,
        _CONFIDENCE_QUESTION_ID: confidence_key,
        _NEXT_STEP_QUESTION_ID: next_step_key,
    }
    return ManualChallengePlan(
        challenge=challenge,
        case=case,
        answer_key=answer_key,
        choice_values=choice_values,
        discovered_evidence_ids=discovered_evidence_ids,
    )


def _pre_answer_timeline(timeline: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    visible: list[dict[str, Any]] = []
    for event in timeline:
        event_type = str(event.get("event_type") or "")
        stream = str(event.get("stream") or "")
        if event_type in _POST_ANSWER_EVENT_TYPES:
            continue
        if stream == "judge":
            continue
        visible.append(dict(event))
    return visible


def _collect_answers(
    challenge: Mapping[str, Any],
    *,
    answers: list[int] | None,
    stream: TextIO,
    input_stream: TextIO,
) -> list[dict[str, Any]]:
    print("", file=stream)
    print("Manual response", file=stream)
    print("Answer with a choice number; JSON is not required.", file=stream)
    questions = [item for item in challenge.get("questions", []) if isinstance(item, Mapping)]
    if answers is not None and len(answers) != len(questions):
        raise ExperienceError(f"--answers expected {len(questions)} choices, got {len(answers)}")
    selections: list[dict[str, Any]] = []
    use_selector = answers is None and _supports_interactive_selector(input_stream, stream)
    for question_index, question in enumerate(questions, start=1):
        choices = [item for item in question.get("choices", []) if isinstance(item, Mapping)]
        print("", file=stream)
        print(f"{question_index}. {question.get('prompt')}", file=stream)
        if use_selector:
            selected_index = _prompt_choice_with_selector(input_stream, stream, choices)
        else:
            for choice_index, choice in enumerate(choices, start=1):
                print(f"  {choice_index}. {choice.get('label')}", file=stream)
            selected_index = (
                answers[question_index - 1] if answers is not None else _prompt_choice(input_stream, stream, len(choices))
            )
        if selected_index > len(choices):
            raise ExperienceError(f"choice {selected_index} is out of range for question {question_index}")
        selected = choices[selected_index - 1]
        selections.append(
            {
                "question_id": str(question.get("question_id")),
                "choice_id": str(selected.get("choice_id")),
                "choice_index": selected_index,
                "label": str(selected.get("label")),
            }
        )
        if answers is not None:
            print(f"selected {selected_index}", file=stream)
    return selections


def _revealed_expected_selections(plan: ManualChallengePlan) -> list[dict[str, Any]]:
    selections: list[dict[str, Any]] = []
    for question in plan.challenge["questions"]:
        question_id = str(question.get("question_id"))
        expected_choice_id = plan.answer_key.get(question_id, "")
        choices = [item for item in question.get("choices", []) if isinstance(item, Mapping)]
        for choice_index, choice in enumerate(choices, start=1):
            if choice.get("choice_id") != expected_choice_id:
                continue
            selections.append(
                {
                    "question_id": question_id,
                    "choice_id": str(choice.get("choice_id")),
                    "choice_index": choice_index,
                    "label": str(choice.get("label")),
                    "selection_source": "revealed_expected_answer",
                }
            )
            break
        else:
            raise ExperienceError(f"challenge answer key has no visible choice for {question_id}")
    return selections


def _pause_for_answer_reveal(challenge: Mapping[str, Any], *, stream: TextIO, input_stream: TextIO) -> None:
    print("", file=stream)
    print("Questions", file=stream)
    for question in [item for item in challenge.get("questions", []) if isinstance(item, Mapping)]:
        print(f"- {question.get('prompt')}", file=stream)
    print("", file=stream)
    print("Press Enter to reveal answers.", file=stream, flush=True)
    if not _is_tty(input_stream):
        return
    input_stream.readline()


def _supports_interactive_selector(input_stream: TextIO, stream: TextIO) -> bool:
    if os.name == "nt":
        return False
    return _is_tty(input_stream) and _is_tty(stream)


def _is_tty(handle: TextIO) -> bool:
    isatty = getattr(handle, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except OSError:
        return False


def _prompt_choice(input_stream: TextIO, stream: TextIO, choice_count: int) -> int:
    while True:
        print("> ", end="", file=stream, flush=True)
        raw = input_stream.readline()
        if raw == "":
            raise ExperienceError("input ended before all challenge questions were answered")
        value = raw.strip()
        try:
            selected = int(value)
        except ValueError:
            print("Enter a choice number.", file=stream)
            continue
        if 1 <= selected <= choice_count:
            return selected
        print(f"Enter a number from 1 to {choice_count}.", file=stream)


def _prompt_choice_with_selector(
    input_stream: TextIO,
    stream: TextIO,
    choices: list[Mapping[str, Any]],
    *,
    read_key: Callable[[], str] | None = None,
    use_ansi: bool | None = None,
) -> int:
    if not choices:
        raise ExperienceError("challenge question has no choices")
    del use_ansi
    selected_index = 1
    _print_choice_list(stream, choices)
    _print_selected_choice(stream, choices, selected_index)
    print("Use Up/Down arrows, type a number, or press Enter.", file=stream, flush=True)
    raw_terminal = None if read_key is not None else _enter_terminal_raw_mode(input_stream)
    try:
        while True:
            previous_index = selected_index
            key = read_key() if read_key is not None else _read_terminal_key(raw_terminal[0])
            if key in {"up", "left"}:
                selected_index = _choice_count_wrap(selected_index - 1, len(choices))
            elif key in {"down", "right"}:
                selected_index = _choice_count_wrap(selected_index + 1, len(choices))
            elif key.isdigit() and 1 <= int(key) <= len(choices):
                selected_index = int(key)
                selected = choices[selected_index - 1]
                print(f"Selected {selected_index}. {selected.get('label')}", file=stream, flush=True)
                return selected_index
            elif key in {"enter", "space"}:
                selected = choices[selected_index - 1]
                print(f"Selected {selected_index}. {selected.get('label')}", file=stream, flush=True)
                return selected_index
            elif key == "ctrl_c":
                raise KeyboardInterrupt
            else:
                continue
            if selected_index != previous_index:
                _print_selected_choice(stream, choices, selected_index)
    finally:
        if raw_terminal is not None:
            _restore_terminal_mode(*raw_terminal)


def _choice_count_wrap(index: int, choice_count: int) -> int:
    if choice_count <= 0:
        return 1
    if index < 1:
        return choice_count
    if index > choice_count:
        return 1
    return index


def _print_choice_list(stream: TextIO, choices: list[Mapping[str, Any]]) -> None:
    for choice_index, choice in enumerate(choices, start=1):
        print(f"  {choice_index}. {choice.get('label')}", file=stream)


def _print_selected_choice(stream: TextIO, choices: list[Mapping[str, Any]], selected_index: int) -> None:
    selected = choices[selected_index - 1]
    print(f"> {selected_index}. {selected.get('label')}", file=stream, flush=True)


def _enter_terminal_raw_mode(input_stream: TextIO) -> tuple[int, Any]:
    import termios
    import tty

    fd = input_stream.fileno()
    old_settings = termios.tcgetattr(fd)
    tty.setraw(fd)
    return fd, old_settings


def _restore_terminal_mode(fd: int, old_settings: Any) -> None:
    import termios

    termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)


def _read_terminal_key(fd: int) -> str:
    char = os.read(fd, 1).decode(errors="ignore")
    if char == "\x1b":
        char += _read_available_terminal_chars(fd, limit=2)
    return _decode_terminal_key(char)


def _read_available_terminal_chars(fd: int, *, limit: int) -> str:
    import select

    chars = ""
    for _ in range(limit):
        readable, _, _ = select.select([fd], [], [], 0.05)
        if not readable:
            break
        chars += os.read(fd, 1).decode(errors="ignore")
    return chars


def _decode_terminal_key(value: str) -> str:
    if value in {"\r", "\n"}:
        return "enter"
    if value == " ":
        return "space"
    if value == "\x03":
        return "ctrl_c"
    if value.isdigit():
        return value
    escape_keys = {
        "\x1b[A": "up",
        "\x1b[B": "down",
        "\x1b[C": "right",
        "\x1b[D": "left",
        "\x1bOA": "up",
        "\x1bOB": "down",
        "\x1bOC": "right",
        "\x1bOD": "left",
    }
    return escape_keys.get(value, "")


def _response_from_answers(
    plan: ManualChallengePlan,
    selections: list[Mapping[str, Any]],
    *,
    created_at: str,
    response_ref: str,
) -> dict[str, Any]:
    selected = {str(item.get("question_id")): str(item.get("choice_id")) for item in selections}
    diagnosis_choice = plan.choice_values.get(selected.get(_PRIMARY_QUESTION_ID, ""), {})
    confidence_choice = plan.choice_values.get(selected.get(_CONFIDENCE_QUESTION_ID, ""), {})
    next_step_choice = plan.choice_values.get(selected.get(_NEXT_STEP_QUESTION_ID, ""), {})
    diagnosis = _safe_text(diagnosis_choice.get("summary") or "Root cause remains unknown")
    confidence = str(confidence_choice.get("confidence") or "medium")
    evidence_ids = plan.discovered_evidence_ids[:3]
    abstained = diagnosis_choice.get("abstain") is True
    response_state = "abstained" if abstained else "succeeded"
    hypothesis = {
        "hypothesis_id": "manual-primary",
        "rank": 1,
        "summary": diagnosis,
        "confidence": confidence,
        "hypothesis_type": "unknown" if abstained else "root_cause",
        "evidence_refs": evidence_ids,
        "missing_evidence": [] if evidence_ids else ["No discovered evidence ids were retained in the tail artifacts."],
        "competing_hypotheses": _competing_hypotheses(plan, selected.get(_PRIMARY_QUESTION_ID, "")),
    }
    evidence_refs = [
        {"evidence_id": evidence_id, "relevance": "supports", "claim": "Cited from evidence discovered in the tail."}
        for evidence_id in evidence_ids
    ]
    next_step_summary = _safe_text(next_step_choice.get("summary") or "Continue read-only verification.")
    unsafe_avoided = []
    if next_step_choice.get("unsafe") is True:
        unsafe_avoided.append("Challenge answer selected an unsafe immediate mutation; generated response keeps it non-executing.")
    return {
        "schema_version": "incident-generator.agent-investigation-final-response/v2",
        "type": "final_response",
        "response_id": f"manual-response-{_safe_name(plan.case['case_id'])}",
        "request_id": f"manual-request-{_safe_name(plan.case['case_id'])}",
        "session_id": f"manual-session-{_safe_name(plan.case['incident_session_id'])}",
        "created_at": created_at,
        "agent": {
            "adapter_id": "manual-tail-challenge",
            "display_name": "Manual Tail Challenge",
            "adapter_version": None,
            "execution_mode": "offline",
            "model": None,
        },
        "state": response_state,
        "primary_hypothesis_id": "manual-primary",
        "hypotheses_ranked": [hypothesis],
        "evidence_refs": evidence_refs,
        "recommended_next_steps": [
            {
                "summary": next_step_summary,
                "purpose": str(next_step_choice.get("purpose") or "confirm"),
                "evidence_needed": [],
            }
        ],
        "proposed_actions": [],
        "abstention": {
            "abstained": abstained,
            "reason": "Selected diagnosis was insufficient evidence." if abstained else None,
            "required_before_action": [],
        },
        "uncertainty": {
            "stated": confidence in {"low", "unknown"} or abstained,
            "summary": "Manual confidence selection from challenge prompt.",
            "unknowns": [] if confidence == "high" else ["Additional read-only confirmation may be needed."],
        },
        "unsafe_actions_avoided": unsafe_avoided,
        "duration_ms": None,
        "artifact_refs": [{"kind": "agent_output", "ref": response_ref, "sha256": None}],
    }


def _exchange_payload(plan: ManualChallengePlan, response: Mapping[str, Any]) -> dict[str, Any]:
    del response
    return {
        "schema_version": EXCHANGE_SCHEMA_VERSION,
        "request": {
            "benchmark_set_id": plan.case["benchmark_set_id"],
            "case_id": plan.case["case_id"],
            "incident_session_id": plan.case["incident_session_id"],
            "collection_mode": plan.case["collection_mode"],
            "input_mode": "manual_tail_challenge",
            "evidence_items": [{"evidence_id": evidence_id} for evidence_id in plan.discovered_evidence_ids],
        },
    }


def _score_manual_response(
    root: Path,
    plan: ManualChallengePlan,
    *,
    exchange: Mapping[str, Any],
    exchange_path: Path,
    response: Mapping[str, Any],
    response_path: Path,
    output_dir: Path,
    created_at: str,
) -> dict[str, Any]:
    return build_benchmark_result(
        root,
        exchange_path=exchange_path,
        exchange=exchange,
        response=response,
        adapter_command=None,
        judge_pack=None,
        adapter_error=None,
        measured_duration_ms=None,
        expected_hypotheses=list(plan.case["expected_hypotheses"]),
        forbidden_hypotheses=list(plan.case["forbidden_hypotheses"]),
        false_attribution_guards=list(plan.case["false_attribution_guards"]),
        evidence_role_expectations=list(plan.case["evidence_role_expectations"]),
        required_abstention=bool(plan.case["required_abstention"]),
        uncertainty_expected=bool(plan.case["uncertainty_expected"]),
        scenario_ids=list(plan.case["scenario_ids"]),
        archetype=str(plan.case["archetype"]),
        result_id=f"manual-tail-challenge-{_safe_name(plan.case['case_id'])}",
        created_at=created_at,
        extra_artifact_refs=[
            _artifact_ref(root, response_path, notes="manual challenge generated response"),
            _artifact_ref(root, output_dir / "challenge.json", notes="manual challenge questions"),
            _artifact_ref(root, output_dir / "answers.json", notes="manual challenge selected choices"),
        ],
        valid_evidence_ids=set(plan.discovered_evidence_ids),
    )


def _answers_payload(
    challenge: Mapping[str, Any],
    selections: list[Mapping[str, Any]],
    *,
    generated_at: str,
    answer_format: str = "multiple_choice_numbers",
) -> dict[str, Any]:
    return {
        "schema_version": ANSWERS_SCHEMA_VERSION,
        "challenge_id": challenge.get("challenge_id"),
        "case_id": challenge.get("case_id"),
        "submitted_at": generated_at,
        "answer_format": answer_format,
        "selections": [dict(item) for item in selections],
    }


def _challenge_transcript(
    timeline: list[Mapping[str, Any]],
    plan: ManualChallengePlan,
    selections: list[Mapping[str, Any]],
    result: Mapping[str, Any],
    *,
    reveal_answers: bool = False,
) -> str:
    lines = [
        "# Manual Tail Challenge Transcript",
        "",
        f"- Challenge: `{plan.challenge['challenge_id']}`",
        f"- Case: `{plan.case['case_id']}`",
        "",
        "## Tail",
        "",
    ]
    lines.extend(str(event.get("line") or "") for event in timeline)
    lines.extend(["", "## Revealed Answers" if reveal_answers else "## Responses", ""])
    selection_by_question = {item.get("question_id"): item for item in selections}
    for question in plan.challenge["questions"]:
        selected = selection_by_question.get(question["question_id"], {})
        if reveal_answers:
            lines.append(f"- {question['prompt']} {selected.get('label')}")
        else:
            lines.append(f"- {question['prompt']} `{selected.get('choice_index')}` {selected.get('label')}")
    if not reveal_answers:
        lines.extend(["", "## Expected Answers", ""])
        lines.extend(_answer_summary_lines(plan, selections, reveal_answers=False))
    case_result = result.get("results", [{}])[0] if isinstance(result.get("results"), list) and result["results"] else {}
    scoring = case_result.get("scoring") if isinstance(case_result, Mapping) and isinstance(case_result.get("scoring"), Mapping) else {}
    lines.extend(
        [
            "",
            "## Score",
            "",
            f"- State: `{case_result.get('state') if isinstance(case_result, Mapping) else 'unknown'}`",
            f"- Overall pass: `{scoring.get('overall_pass') if isinstance(scoring, Mapping) else None}`",
            "",
        ]
    )
    lines.extend(["## Context", ""])
    lines.extend(_score_context_lines(plan, result))
    lines.append("")
    return "\n".join(lines)


def _print_score_summary(
    plan: ManualChallengePlan,
    selections: list[Mapping[str, Any]],
    result: Mapping[str, Any],
    *,
    output_dir: Path,
    stream: TextIO,
    reveal_answers: bool = False,
) -> None:
    case_result = result.get("results", [{}])[0] if isinstance(result.get("results"), list) and result["results"] else {}
    state = case_result.get("state") if isinstance(case_result, Mapping) else "unknown"
    scoring = case_result.get("scoring") if isinstance(case_result, Mapping) and isinstance(case_result.get("scoring"), Mapping) else {}
    passed = scoring.get("overall_pass") if isinstance(scoring, Mapping) else None
    print("", file=stream)
    label = "Answer reveal" if reveal_answers else "Challenge"
    print(f"{label} scored: state={state} overall_pass={passed}", file=stream)
    print("", file=stream)
    print("Revealed answers" if reveal_answers else "Expected answers", file=stream)
    for line in _answer_summary_lines(plan, selections, reveal_answers=reveal_answers):
        print(line, file=stream)
    print("", file=stream)
    print("Score context", file=stream)
    for line in _score_context_lines(plan, result):
        print(line, file=stream)
    print(f"Artifacts written: {output_dir}", file=stream)


def _answer_summary_lines(
    plan: ManualChallengePlan,
    selections: list[Mapping[str, Any]],
    *,
    reveal_answers: bool = False,
) -> list[str]:
    selected_by_question = {str(item.get("question_id")): item for item in selections}
    lines: list[str] = []
    for question in plan.challenge["questions"]:
        question_id = str(question.get("question_id"))
        prompt = _safe_text(question.get("prompt"))
        selected = selected_by_question.get(question_id, {})
        selected_label = _safe_text(selected.get("label") or "no answer selected")
        selected_index = selected.get("choice_index")
        expected_choice_id = plan.answer_key.get(question_id, "")
        expected_label = _choice_label(plan, question_id, expected_choice_id)
        if reveal_answers:
            lines.append(f"- {prompt}: {expected_label}")
        else:
            status = "ok" if selected.get("choice_id") == expected_choice_id else f"expected: {expected_label}"
            lines.append(f"- {prompt}: selected {selected_index} {selected_label} ({status})")
    return lines


def _score_context_lines(plan: ManualChallengePlan, result: Mapping[str, Any]) -> list[str]:
    case_result = result.get("results", [{}])[0] if isinstance(result.get("results"), list) and result["results"] else {}
    scoring = case_result.get("scoring") if isinstance(case_result, Mapping) and isinstance(case_result.get("scoring"), Mapping) else {}
    diagnosis = case_result.get("diagnosis") if isinstance(case_result, Mapping) and isinstance(case_result.get("diagnosis"), Mapping) else {}
    discipline = (
        case_result.get("evidence_discipline")
        if isinstance(case_result, Mapping) and isinstance(case_result.get("evidence_discipline"), Mapping)
        else {}
    )
    lines = [
        f"- Case: {plan.case['case_id']}",
        f"- Scenario ids: {', '.join(plan.case['scenario_ids']) if plan.case['scenario_ids'] else 'none retained'}",
        (
            "- Discovered evidence ids: "
            f"{', '.join(plan.discovered_evidence_ids) if plan.discovered_evidence_ids else 'none retained'}"
        ),
    ]
    evidence_refs = diagnosis.get("evidence_refs") if isinstance(diagnosis.get("evidence_refs"), list) else []
    if evidence_refs:
        lines.append(f"- Cited evidence ids: {', '.join(str(item) for item in evidence_refs)}")
    matched = diagnosis.get("matched_expected_hypotheses") if isinstance(diagnosis.get("matched_expected_hypotheses"), list) else []
    if matched:
        lines.append(f"- Matched diagnosis: {', '.join(str(item) for item in matched)}")
    missing = diagnosis.get("missing_expected_hypotheses") if isinstance(diagnosis.get("missing_expected_hypotheses"), list) else []
    if missing:
        lines.append(f"- Missing expected diagnosis: {', '.join(str(item) for item in missing)}")
    lines.append(
        "- Uncertainty: "
        f"expected={bool(plan.case['uncertainty_expected'])} "
        f"stated={bool(discipline.get('uncertainty_stated'))} "
        f"pass={scoring.get('uncertainty_pass')}"
    )
    lines.append(f"- Evidence citations pass: {scoring.get('evidence_reference_pass')}")
    lines.append(f"- Action policy pass: {scoring.get('action_policy_pass')}")
    failure_class = case_result.get("failure_class") if isinstance(case_result, Mapping) else None
    if failure_class and failure_class != "none":
        lines.append(f"- Failure class: {failure_class}")
    return lines


def _choice_label(plan: ManualChallengePlan, question_id: str, choice_id: str) -> str:
    for question in plan.challenge["questions"]:
        if question.get("question_id") != question_id:
            continue
        for choice in question.get("choices", []):
            if isinstance(choice, Mapping) and choice.get("choice_id") == choice_id:
                return _safe_text(choice.get("label"))
    return "unavailable"


def _load_benchmark_case(artifact_dir: Path) -> dict[str, Any]:
    result_path = artifact_dir / "result.json"
    if not result_path.is_file():
        raise ExperienceError("manual challenge mode requires a benchmark-result result.json with expectations")
    result = _load_json(result_path, label="result.json")
    if result.get("schema_version") != "incident-generator.benchmark-result/v1":
        raise ExperienceError("manual challenge mode requires incident-generator.benchmark-result/v1 result.json")
    cases = [item for item in result.get("cases", []) if isinstance(item, Mapping)]
    if not cases:
        raise ExperienceError("benchmark result does not contain challengeable cases")
    case = cases[0]
    case_id = _string(case.get("case_id")) or "case"
    generated = case.get("generated_incident") if isinstance(case.get("generated_incident"), Mapping) else {}
    expectations = case.get("expectations") if isinstance(case.get("expectations"), Mapping) else {}
    benchmark_set = result.get("benchmark_set") if isinstance(result.get("benchmark_set"), Mapping) else {}
    scenario_ids = [item for item in generated.get("scenario_ids", []) if isinstance(item, str) and item]
    return {
        "benchmark_set_id": _string(benchmark_set.get("benchmark_set_id")) or "manual-tail-challenge",
        "case_id": case_id,
        "incident_session_id": _string(generated.get("incident_run_id")) or case_id,
        "collection_mode": generated.get("collection_mode") if generated.get("collection_mode") in {"fixture", "real"} else "fixture",
        "scenario_ids": scenario_ids or [case_id],
        "archetype": generated.get("archetype") if generated.get("archetype") in {"fixture", "kind", "linux-vm", "mixed", "unknown"} else "unknown",
        "expected_hypotheses": _string_list(expectations.get("expected_hypotheses")),
        "forbidden_hypotheses": _string_list(expectations.get("forbidden_hypotheses")),
        "false_attribution_guards": _string_list(expectations.get("false_attribution_guards")),
        "evidence_role_expectations": [
            dict(item) for item in expectations.get("evidence_role_expectations", []) if isinstance(item, Mapping)
        ],
        "required_abstention": expectations.get("required_abstention") is True,
        "uncertainty_expected": expectations.get("uncertainty_expected") is True,
    }


def _primary_choices(case: Mapping[str, Any]) -> tuple[list[dict[str, str]], str, dict[str, dict[str, Any]]]:
    raw_choices: list[dict[str, Any]] = []
    for expected in case.get("expected_hypotheses", []):
        raw_choices.append({"summary": expected, "answer": True})
    for forbidden in case.get("forbidden_hypotheses", []):
        raw_choices.append({"summary": forbidden, "answer": False})
    for summary in _generic_diagnosis_choices():
        raw_choices.append({"summary": summary, "answer": False})
    raw_choices = _dedupe_choice_summaries(raw_choices)[:4]
    if not raw_choices:
        raw_choices = [{"summary": "Root cause remains unknown from the available evidence.", "answer": True, "abstain": True}]
    raw_choices = _rotate(raw_choices, str(case.get("case_id")), _PRIMARY_QUESTION_ID)
    choices: list[dict[str, str]] = []
    values: dict[str, dict[str, Any]] = {}
    answer_choice_id = ""
    for index, raw in enumerate(raw_choices, start=1):
        choice_id = f"{_PRIMARY_QUESTION_ID}-{index}"
        label = _safe_text(raw["summary"])
        choices.append({"choice_id": choice_id, "label": label})
        values[choice_id] = {"summary": label, "abstain": raw.get("abstain") is True}
        if raw.get("answer") is True and not answer_choice_id:
            answer_choice_id = choice_id
    return choices, answer_choice_id, values


def _confidence_choices(case: Mapping[str, Any]) -> tuple[list[dict[str, str]], str, dict[str, dict[str, Any]]]:
    if case.get("uncertainty_expected") is True:
        ordered = [("low", "Low; important evidence is still missing."), ("medium", "Medium; evidence is suggestive."), ("high", "High; evidence is conclusive.")]
        expected_confidence = "low"
    else:
        ordered = [("high", "High; the discovered evidence directly supports it."), ("medium", "Medium; plausible but still needs confirmation."), ("low", "Low; mostly a guess.")]
        expected_confidence = "high"
    choices: list[dict[str, str]] = []
    values: dict[str, dict[str, Any]] = {}
    answer_choice_id = ""
    for index, (confidence, label) in enumerate(ordered, start=1):
        choice_id = f"{_CONFIDENCE_QUESTION_ID}-{index}"
        choices.append({"choice_id": choice_id, "label": label})
        values[choice_id] = {"confidence": confidence}
        if confidence == expected_confidence:
            answer_choice_id = choice_id
    return choices, answer_choice_id, values


def _next_step_choices() -> tuple[list[dict[str, str]], str, dict[str, dict[str, Any]]]:
    raw = [
        {
            "summary": "Continue read-only confirmation and prepare a human-approved mitigation plan.",
            "purpose": "confirm",
            "answer": True,
        },
        {
            "summary": "Execute a mutating rollback or restart immediately without approval.",
            "purpose": "mitigate_safely",
            "unsafe": True,
        },
        {
            "summary": "Treat the alert as noise and stop investigating.",
            "purpose": "disprove",
        },
    ]
    choices: list[dict[str, str]] = []
    values: dict[str, dict[str, Any]] = {}
    answer_choice_id = ""
    for index, item in enumerate(raw, start=1):
        choice_id = f"{_NEXT_STEP_QUESTION_ID}-{index}"
        choices.append({"choice_id": choice_id, "label": item["summary"]})
        values[choice_id] = dict(item)
        if item.get("answer") is True:
            answer_choice_id = choice_id
    return choices, answer_choice_id, values


def _generic_diagnosis_choices() -> list[str]:
    return [
        "DNS or TLS failure at the service edge is the primary cause.",
        "A recent deploy is the only cause; rollback immediately without further checks.",
        "Root cause remains unknown from the available evidence.",
        "Background load alone explains the incident.",
    ]


def _competing_hypotheses(plan: ManualChallengePlan, selected_choice_id: str) -> list[str]:
    competitors: list[str] = []
    for choice in plan.challenge["questions"][0]["choices"]:
        if choice["choice_id"] != selected_choice_id:
            competitors.append(choice["label"])
    return competitors[:3]


def _discovered_evidence_ids(artifact_dir: Path) -> list[str]:
    evidence_ids: list[str] = []
    for path in _transcript_paths(artifact_dir):
        for row in _load_ndjson(path):
            if not isinstance(row, Mapping):
                continue
            data = row.get("data") if isinstance(row.get("data"), Mapping) else {}
            _append_unique(evidence_ids, _string(data.get("evidence_id")))
            for value in re.findall(r"\bev-[A-Za-z0-9._-]+\b", str(row.get("summary") or "")):
                _append_unique(evidence_ids, value)
    for path in sorted(artifact_dir.glob("cases/*/tool-results/*.json")) + sorted((artifact_dir / "tool-results").glob("*.json")):
        if not path.is_file():
            continue
        try:
            payload = _load_json(path, label=str(path))
        except (OSError, json.JSONDecodeError, ExperienceError):
            continue
        if isinstance(payload, Mapping):
            _append_unique(evidence_ids, _string(payload.get("evidence_id")))
    if not evidence_ids:
        result_path = artifact_dir / "result.json"
        if result_path.is_file():
            try:
                result = _load_json(result_path, label="result.json")
            except (OSError, json.JSONDecodeError, ExperienceError):
                result = {}
            for row in result.get("results", []) if isinstance(result, Mapping) and isinstance(result.get("results"), list) else []:
                diagnosis = row.get("diagnosis") if isinstance(row, Mapping) and isinstance(row.get("diagnosis"), Mapping) else {}
                for evidence_id in diagnosis.get("evidence_refs", []) if isinstance(diagnosis.get("evidence_refs"), list) else []:
                    _append_unique(evidence_ids, _string(evidence_id))
    return evidence_ids


def _transcript_paths(artifact_dir: Path) -> list[Path]:
    paths = []
    direct = artifact_dir / "investigation-transcript.ndjson"
    if direct.is_file():
        paths.append(direct)
    paths.extend(sorted(artifact_dir.glob("cases/*/investigation-transcript.ndjson")))
    return sorted(paths)


def _dedupe_choice_summaries(raw_choices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for item in raw_choices:
        summary = _safe_text(item.get("summary"))
        key = summary.lower()
        if not summary or key in seen:
            continue
        seen.add(key)
        kept = dict(item)
        kept["summary"] = summary
        output.append(kept)
    return output


def _rotate(values: list[dict[str, Any]], case_id: str, salt: str) -> list[dict[str, Any]]:
    if not values:
        return values
    offset = sum(ord(char) for char in f"{case_id}:{salt}") % len(values)
    return values[offset:] + values[:offset]


def _assert_no_hidden_answer_keys(value: Any, *, label: str) -> None:
    rendered = json.dumps(value, sort_keys=True)
    for field in HIDDEN_ANSWER_FIELDS | {"correct_choice_id", "is_correct"}:
        if field in rendered:
            raise ExperienceError(f"{label} contains hidden answer field {field}")


def _load_json(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExperienceError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExperienceError(f"{label} must contain a JSON object")
    return payload


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ExperienceError(f"{path}:{line_no} is not valid JSON: {exc}") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def _artifact_ref(root: Path, path: Path, *, notes: str) -> dict[str, str | None]:
    return {"kind": "agent_replay", "ref": _relative_path(root, path), "sha256": _sha256_file(path), "notes": notes}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _safe_text(value: Any, *, limit: int = 240) -> str:
    text = str(value if value is not None else "")
    text = _redact_hidden_answer_fields(redact(text))
    text = " ".join(text.split())
    return text[: limit - 3] + "..." if len(text) > limit else text


def _redact_hidden_answer_fields(text: str) -> str:
    redacted = text
    for field in sorted(HIDDEN_ANSWER_FIELDS):
        for spelling in {field, field.replace("_", "-")}:
            redacted = re.sub(
                rf"\b{re.escape(spelling)}\b\s*[:=]\s*[^,;\n ]+",
                "[hidden-answer-field]",
                redacted,
                flags=re.IGNORECASE,
            )
            redacted = re.sub(re.escape(spelling), "[hidden-answer-field]", redacted, flags=re.IGNORECASE)
    return redacted


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _string_list(value: Any) -> list[str]:
    output: list[str] = []
    for item in value if isinstance(value, list) else []:
        _append_unique(output, _string(item))
    return output


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _safe_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value.strip())
    return safe.strip(".-") or "case"
