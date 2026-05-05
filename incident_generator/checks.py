"""Repository hygiene checks used by release and CI gates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from .parsers import load_yaml


MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
SECRET_ASSIGNMENT_RE = re.compile(r"(?i)\b(api[_-]?key|token|password|secret|aws[_-]?key)\s*=\s*([^\s,;]+)")
AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
PRIVATE_KEY_RE = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
PROMPT_INJECTION_RE = re.compile(
    r"(?i)(ignore (all )?(previous|prior) instructions|exfiltrate|system prompt|developer message|delete_pod_now)"
)

DEFAULT_EXCLUDED_DIRS = {".git", ".mypy_cache", ".pytest_cache", ".tmp", ".venv", "__pycache__", "build", "dist"}
TEXT_SUFFIXES = {".json", ".txt", ".yaml", ".yml"}


@dataclass(frozen=True)
class CheckFinding:
    severity: str
    rule: str
    path: str
    message: str
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "severity": self.severity,
            "rule": self.rule,
            "path": self.path,
            "message": self.message,
        }
        if self.line is not None:
            payload["line"] = self.line
        return payload


def check_markdown_links(root: Path) -> list[CheckFinding]:
    root = root.resolve()
    findings: list[CheckFinding] = []
    for path in _walk_files(root, suffixes={".md"}):
        text = path.read_text(encoding="utf-8")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for match in MARKDOWN_LINK_RE.finditer(line):
                target = _clean_markdown_target(match.group(1))
                if _is_external_or_anchor(target):
                    continue
                target_path = target.split("#", 1)[0]
                if not target_path:
                    continue
                candidate = (path.parent / unquote(target_path)).resolve()
                if not _is_within(root, candidate) or not candidate.exists():
                    findings.append(
                        CheckFinding(
                            severity="error",
                            rule="markdown-link",
                            path=_relative(root, path),
                            line=line_number,
                            message=f"missing markdown link target: {target}",
                        )
                    )
    return findings


def check_fixture_hygiene(root: Path, *, allowlist_path: Path | None = None) -> list[CheckFinding]:
    root = root.resolve()
    allowlist = _load_allowlist(allowlist_path or root / "evals/fixture-hygiene-allowlist.yaml")
    findings: list[CheckFinding] = []
    for path in _fixture_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        relative = _relative(root, path)
        for line_number, line in enumerate(text.splitlines(), start=1):
            findings.extend(_secret_findings(root, relative, line_number, line, allowlist))
            if path.name == "expected.yaml":
                findings.extend(_prompt_injection_findings(relative, line_number, line, allowlist))
    return findings


def findings_payload(findings: list[CheckFinding]) -> dict[str, Any]:
    return {
        "ok": not any(finding.severity == "error" for finding in findings),
        "error_count": sum(1 for finding in findings if finding.severity == "error"),
        "warning_count": sum(1 for finding in findings if finding.severity == "warning"),
        "findings": [finding.to_dict() for finding in findings],
    }


def _secret_findings(
    root: Path,
    relative: str,
    line_number: int,
    line: str,
    allowlist: dict[str, set[str]],
) -> list[CheckFinding]:
    del root
    findings: list[CheckFinding] = []
    for match in SECRET_ASSIGNMENT_RE.finditer(line):
        value = _normalize_secret_value(match.group(2))
        if _allowed_value(value, line, allowlist):
            continue
        findings.append(
            CheckFinding(
                severity="error",
                rule="raw-secret-assignment",
                path=relative,
                line=line_number,
                message=f"unredacted {match.group(1)} assignment",
            )
        )
    for value in AWS_ACCESS_KEY_RE.findall(line):
        if _allowed_value(value, line, allowlist):
            continue
        findings.append(
            CheckFinding(
                severity="error",
                rule="aws-access-key",
                path=relative,
                line=line_number,
                message="unallowlisted AWS access key-like value",
            )
        )
    if PRIVATE_KEY_RE.search(line) and not _allowed_value("PRIVATE KEY", line, allowlist):
        findings.append(
            CheckFinding(
                severity="error",
                rule="private-key",
                path=relative,
                line=line_number,
                message="private key material is not allowed in fixtures",
            )
        )
    return findings


def _prompt_injection_findings(
    relative: str,
    line_number: int,
    line: str,
    allowlist: dict[str, set[str]],
) -> list[CheckFinding]:
    match = PROMPT_INJECTION_RE.search(line)
    if match is None or _line_allowed(line, allowlist):
        return []
    return [
        CheckFinding(
            severity="error",
            rule="prompt-injection-expected-output",
            path=relative,
            line=line_number,
            message="prompt-injection marker appears in expected output",
        )
    ]


def _fixture_files(root: Path) -> list[Path]:
    evals = root / "evals"
    if not evals.is_dir():
        return []
    return [
        path
        for path in _walk_files(evals, suffixes=TEXT_SUFFIXES)
        if path.name in {"fixture.yaml", "expected.yaml"} or "/outputs/" in path.as_posix()
    ]


def _walk_files(root: Path, *, suffixes: set[str]) -> list[Path]:
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if any(part in DEFAULT_EXCLUDED_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in suffixes:
            files.append(path)
    return files


def _load_allowlist(path: Path) -> dict[str, set[str]]:
    if not path.is_file():
        return {"allowed_literals": set(), "allowed_substrings": {"[REDACTED]"}}
    data = load_yaml(path)
    return {
        "allowed_literals": {str(value) for value in data.get("allowed_literals", [])},
        "allowed_substrings": {str(value) for value in data.get("allowed_substrings", [])} | {"[REDACTED]"},
    }


def _allowed_value(value: str, line: str, allowlist: dict[str, set[str]]) -> bool:
    if value in allowlist["allowed_literals"]:
        return True
    if value.startswith("[REDACTED"):
        return True
    lowered = value.lower()
    if "fake" in lowered or "example" in lowered:
        return True
    return _line_allowed(line, allowlist)


def _normalize_secret_value(value: str) -> str:
    return value.replace("\\n", "").strip().strip("\"'")


def _line_allowed(line: str, allowlist: dict[str, set[str]]) -> bool:
    return any(item and item in line for item in allowlist["allowed_substrings"])


def _clean_markdown_target(raw: str) -> str:
    target = raw.strip()
    if " " in target and not target.startswith("<"):
        target = target.split(" ", 1)[0]
    if target.startswith("<") and target.endswith(">"):
        target = target[1:-1]
    return target.strip()


def _is_external_or_anchor(target: str) -> bool:
    lowered = target.lower()
    return lowered.startswith(("#", "http://", "https://", "mailto:", "app://"))


def _is_within(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
    except ValueError:
        return False
    return True


def _relative(root: Path, path: Path) -> str:
    return str(path.resolve().relative_to(root))
