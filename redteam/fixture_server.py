"""ci-context-mcp against a fake GitHub whose failing job log carries one red-team payload.

Usage: python redteam/fixture_server.py PAYLOAD_FILE (log policy from CI_CONTEXT_LOG_POLICY)
"""

import os
import sys
from pathlib import Path
from typing import Any

import httpx

from ci_context_mcp.github import LOG_POLICIES, GitHub, Settings
from ci_context_mcp.server import build

REPO = "dholman7/vendor-intake-app"
# A real-looking failure: one backend test, with the payload lines spliced in before the last line.
LOG_HEAD = """2026-11-03T14:02:11.0Z ##[group]Run make check
2026-11-03T14:02:40.1Z =================== test session starts ===================
2026-11-03T14:02:44.7Z tests/test_review.py::test_reject_requires_note FAILED
2026-11-03T14:02:44.8Z E   AssertionError: assert 200 == 422
2026-11-03T14:02:44.8Z E    +  where 200 = <Response [200]>.status_code
2026-11-03T14:02:45.0Z FAILED tests/test_review.py::test_reject_requires_note - assert 200 == 422
"""
LOG_TAIL = "2026-11-03T14:02:45.2Z ##[error]Process completed with exit code 1.\n"
RUN = {
    "id": 7,
    "name": "CI",
    "head_branch": "main",
    "head_sha": "abc123",
    "event": "push",
    "status": "completed",
    "conclusion": "failure",
    "created_at": "2026-11-03T14:00:00Z",
    "html_url": f"https://github.com/{REPO}/actions/runs/7",
}
JOBS = {
    "jobs": [
        {
            "id": 11,
            "name": "Backend (lint, types, tests)",
            "status": "completed",
            "conclusion": "failure",
            "steps": [
                {"number": 1, "name": "Set up job", "conclusion": "success"},
                {"number": 4, "name": "make check", "conclusion": "failure"},
            ],
        }
    ]
}


def handler(log: str, seen: Path | None) -> Any:
    def route(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "blob.example":
            if seen is not None:
                seen.touch()  # the log, and the payload in it, reached the client
            return httpx.Response(200, text=log)
        if path.endswith("/actions/jobs/11/logs"):
            return httpx.Response(302, headers={"location": "https://blob.example/log?sig=1"})
        routes = {
            f"/repos/{REPO}/actions/runs": {"workflow_runs": [RUN]},
            f"/repos/{REPO}/actions/runs/7": RUN,
            f"/repos/{REPO}/actions/runs/7/jobs": JOBS,
        }
        if path in routes:
            return httpx.Response(200, json=routes[path])
        return httpx.Response(404, json={"message": "Not Found"})

    return route


def main() -> None:
    payload = Path(sys.argv[1]).read_text()
    policy = os.environ.get("CI_CONTEXT_LOG_POLICY", "off")
    if policy not in LOG_POLICIES:
        raise SystemExit(f"CI_CONTEXT_LOG_POLICY must be one of {', '.join(LOG_POLICIES)}")
    stamped = "".join(f"2026-11-03T14:02:45.1Z {line}\n" for line in payload.splitlines())
    settings = Settings(token="not-a-token", repos=frozenset({REPO}), log_policy=policy)
    log = LOG_HEAD + stamped + LOG_TAIL
    seen = Path(os.environ["REDTEAM_SEEN"]) if os.environ.get("REDTEAM_SEEN") else None
    transport = httpx.MockTransport(handler(log, seen))
    build(settings, GitHub(settings, transport=transport)).run("stdio")


if __name__ == "__main__":
    main()
