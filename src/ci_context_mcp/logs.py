"""Pure functions that turn raw Actions logs into something worth putting in a model's context."""

import re

_TIMESTAMP = re.compile(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ?")
_ANSI = re.compile(r"\x1b\[[0-9;]*m")
# Lines that usually explain a failure, across the tools this repo family uses.
_ERRORISH = re.compile(
    r"##\[error\]|\bFAILED\b|\bError\b|error TS\d+|Traceback|AssertionError|✘|"
    r"Expected:|Received:|\bfailed\b",
)
# pytest-cov's terminal report: "TOTAL   864   29   97%".
_COVERAGE = re.compile(r"^TOTAL\s+\d+\s+\d+(?:\s+\d+\s+\d+)?\s+(\d+(?:\.\d+)?)%")


def clean(log: str) -> list[str]:
    return [_ANSI.sub("", _TIMESTAMP.sub("", line)).rstrip() for line in log.splitlines()]


def tail(lines: list[str], count: int) -> list[str]:
    return lines[-max(count, 0) :] if count else []


def grep(lines: list[str], pattern: str) -> list[str]:
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise ValueError(f"invalid regular expression: {exc}") from exc
    return [line for line in lines if regex.search(line)]


def error_lines(lines: list[str], limit: int = 30) -> list[str]:
    """The most recent error-looking lines, oldest first. Setup noise is skipped."""
    found = [line for line in lines if _ERRORISH.search(line) and not line.startswith("##[group]")]
    return found[-limit:]


def coverage_percent(lines: list[str]) -> float | None:
    for line in reversed(lines):
        match = _COVERAGE.match(line.strip())
        if match:
            return float(match.group(1))
    return None
