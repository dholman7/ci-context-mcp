"""The server end to end through an in-process MCP client, with GitHub replaced by a mock."""

import json
import logging
from typing import Any

import httpx
import pytest
from mcp import Client

from ci_context_mcp import logs
from ci_context_mcp.github import GitHub, Settings
from ci_context_mcp.server import build

REPO = "dholman7/vendor-intake-app"
TOKEN = "ghp_not_a_real_token"

LOG = """2026-10-28T19:05:48.1Z ##[group]Run make check
2026-10-28T19:05:49.2Z tests/test_review.py::test_reject FAILED
2026-10-28T19:05:49.3Z E   AssertionError: assert 200 == 422
2026-10-28T19:05:50.0Z TOTAL                                           864     29    97%
2026-10-28T19:05:50.1Z ##[error]Process completed with exit code 1.
"""

RUN = {
    "id": 7,
    "name": "CI",
    "head_branch": "main",
    "head_sha": "abc123",
    "event": "push",
    "status": "completed",
    "conclusion": "failure",
    "created_at": "2026-10-28T19:00:00Z",
    "html_url": "https://github.com/x/run/7",
}
JOBS = {
    "jobs": [
        {
            "id": 11,
            "name": "Backend",
            "status": "completed",
            "conclusion": "failure",
            "steps": [
                {"number": 1, "name": "Set up", "conclusion": "success"},
                {"number": 4, "name": "make check", "conclusion": "failure"},
            ],
        },
        {"id": 12, "name": "Frontend", "status": "completed", "conclusion": "success", "steps": []},
    ]
}


class FakeGitHub:
    """Routes like the real API; records every request so tests can check what was sent."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if request.url.host == "blob.example":
            return httpx.Response(200, text=LOG)
        routes: dict[str, Any] = {
            f"/repos/{REPO}/actions/runs": {"workflow_runs": [RUN]},
            f"/repos/{REPO}/actions/runs/7": RUN,
            f"/repos/{REPO}/actions/runs/7/jobs": JOBS,
            f"/repos/{REPO}/pulls/5": {"head": {"sha": "abc123"}},
            f"/repos/{REPO}/commits/abc123/check-runs": {
                "check_runs": [
                    {
                        "name": "Backend",
                        "status": "completed",
                        "conclusion": "failure",
                        "html_url": "u",
                    }
                ]
            },
        }
        if path.startswith(f"/repos/{REPO}/actions/jobs/") and path.endswith("/logs"):
            return httpx.Response(302, headers={"location": "https://blob.example/log.txt?sig=1"})
        if path in routes:
            return httpx.Response(200, json=routes[path])
        return httpx.Response(404, json={"message": "Not Found"})


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def fake() -> FakeGitHub:
    return FakeGitHub()


@pytest.fixture
def server(fake: FakeGitHub) -> Any:
    settings = Settings(token=TOKEN, repos=frozenset({REPO}), api_url="https://api.github.com")
    return build(settings, GitHub(settings, transport=httpx.MockTransport(fake)))


async def _call(server: Any, tool: str, args: dict[str, Any]) -> Any:
    async with Client(server) as client:
        return await client.call_tool(tool, args)


@pytest.mark.anyio
async def test_every_tool_is_marked_read_only(server: Any) -> None:
    async with Client(server) as client:
        tools = (await client.list_tools()).tools

    assert {t.name for t in tools} == {
        "list_runs",
        "get_run",
        "job_log",
        "failure_summary",
        "coverage",
        "pr_checks",
    }
    assert all(t.annotations and t.annotations.read_only_hint for t in tools)


@pytest.mark.anyio
async def test_failure_summary_names_the_failed_step_and_its_errors(server: Any) -> None:
    result = await _call(server, "failure_summary", {"repo": REPO, "run_id": 7})

    assert not result.is_error
    [failure] = result.structured_content["result"]
    assert failure["job"] == "Backend"
    assert failure["failed_steps"] == ["make check"]
    assert "E   AssertionError: assert 200 == 422" in failure["error_lines"]
    assert not any(line.startswith("2026-") for line in failure["error_lines"])  # timestamps gone


@pytest.mark.anyio
async def test_log_download_never_sends_the_token_to_blob_storage(
    server: Any, fake: FakeGitHub
) -> None:
    await _call(server, "job_log", {"repo": REPO, "job_id": 11, "pattern": "FAILED"})

    api = [r for r in fake.requests if r.url.host == "api.github.com"]
    blob = [r for r in fake.requests if r.url.host == "blob.example"]
    assert api and all(r.headers["authorization"] == f"Bearer {TOKEN}" for r in api)
    assert blob and all("authorization" not in r.headers for r in blob)


@pytest.mark.anyio
async def test_repos_off_the_allowlist_are_refused_before_any_request(
    server: Any, fake: FakeGitHub
) -> None:
    result = await _call(server, "list_runs", {"repo": "someone/else"})

    assert result.is_error
    assert "allowlist" in result.content[0].text
    assert fake.requests == []


@pytest.mark.anyio
async def test_github_errors_come_back_as_readable_tool_errors(server: Any) -> None:
    result = await _call(server, "get_run", {"repo": REPO, "run_id": 999})

    assert result.is_error
    assert "not found (404)" in result.content[0].text
    assert TOKEN not in json.dumps(result.model_dump())


@pytest.mark.anyio
async def test_coverage_and_pr_checks(server: Any) -> None:
    cov = await _call(server, "coverage", {"repo": REPO, "run_id": 7})
    checks = await _call(server, "pr_checks", {"repo": REPO, "pr": 5})

    assert {c["job"]: c["percent"] for c in cov.structured_content["result"]}["Backend"] == 97.0
    assert checks.structured_content["head_sha"] == "abc123"
    assert checks.structured_content["checks"][0]["conclusion"] == "failure"


def test_log_helpers() -> None:
    lines = logs.clean(LOG)
    assert lines[0] == "##[group]Run make check"
    assert logs.tail(lines, 2) == lines[-2:]
    assert logs.coverage_percent(lines) == 97.0
    assert logs.grep(lines, r"FAILED") == ["tests/test_review.py::test_reject FAILED"]
    with pytest.raises(ValueError, match="invalid regular expression"):
        logs.grep(lines, "(")


@pytest.mark.anyio
async def test_signed_log_urls_are_not_logged(
    server: Any, caplog: pytest.LogCaptureFixture
) -> None:
    # Regression: httpx logged the signed blob URL (a short-lived credential) at INFO.
    with caplog.at_level(logging.INFO):
        await _call(server, "job_log", {"repo": REPO, "job_id": 11})

    assert "sig=" not in caplog.text
