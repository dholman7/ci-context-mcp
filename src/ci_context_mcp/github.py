"""A deliberately read-only GitHub REST client: it can only GET."""

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx
from mcp.server.mcpserver.exceptions import ToolError

API_URL = "https://api.github.com"
MAX_LOG_BYTES = 5_000_000

# httpx logs every request URL at INFO. Log downloads use signed, short-lived URLs that are
# credentials in their own right, and a stdio server's logs land in the client's log file.
logging.getLogger("httpx").setLevel(logging.WARNING)


@dataclass(frozen=True)
class Settings:
    token: str
    repos: frozenset[str]
    api_url: str = API_URL

    @classmethod
    def from_env(cls) -> "Settings":
        token = os.environ.get("GITHUB_TOKEN", "")
        repos = frozenset(
            r.strip().lower()
            for r in os.environ.get("CI_CONTEXT_REPOS", "").split(",")
            if r.strip()
        )
        if not token:
            raise SystemExit(
                "Set GITHUB_TOKEN to a read-only token (Actions: read, Contents: read)."
            )
        if not repos:
            raise SystemExit(
                "Set CI_CONTEXT_REPOS to the repos this server may read, e.g. owner/app,owner/lib."
            )
        return cls(token=token, repos=repos, api_url=os.environ.get("GITHUB_API_URL", API_URL))


class GitHub:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self._api = httpx.Client(
            base_url=settings.api_url,
            headers={
                "Authorization": f"Bearer {settings.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=20,
            transport=transport,
        )
        # Log downloads redirect to blob storage; that host must never see the token.
        self._downloads = httpx.Client(timeout=30, transport=transport)

    def authorize(self, repo: str) -> str:
        """Every tool calls this first. Only repos on the allowlist can be read."""
        normalized = repo.strip().lower()
        if normalized.count("/") != 1:
            raise ToolError(f"repo must look like owner/name, got {repo!r}")
        if normalized not in self.settings.repos:
            raise ToolError(f"{repo} is not on this server's allowlist")
        return normalized

    @staticmethod
    def _check(response: httpx.Response) -> None:
        if response.status_code == 401:
            raise ToolError("GitHub rejected the token (401); it may be expired")
        if response.status_code == 403:
            if response.headers.get("x-ratelimit-remaining") == "0":
                raise ToolError("GitHub API rate limit reached; try again later")
            raise ToolError("the token can't read this (403); it needs Actions: read")
        if response.status_code == 404:
            raise ToolError("not found (404); check the repo, id, and token access")
        if response.status_code >= 400:
            raise ToolError(f"GitHub returned {response.status_code}")

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        try:
            response = self._api.get(
                path, params={k: v for k, v in (params or {}).items() if v is not None}
            )
        except httpx.HTTPError as exc:
            raise ToolError(f"could not reach GitHub: {type(exc).__name__}") from exc
        self._check(response)
        return response.json()

    def get_log(self, path: str) -> str:
        """Job logs: GitHub answers 302 with a short-lived URL, fetched without credentials."""
        try:
            response = self._api.get(path, follow_redirects=False)
            if response.status_code in (301, 302, 307, 308):
                response = self._downloads.get(response.headers["location"])
        except (httpx.HTTPError, KeyError) as exc:
            raise ToolError(f"could not download the log: {type(exc).__name__}") from exc
        self._check(response)
        return response.content[-MAX_LOG_BYTES:].decode("utf-8", errors="replace")
