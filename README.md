# ci-context-mcp

A read-only [MCP](https://modelcontextprotocol.io) server that gives AI coding assistants what they need to act on CI: recent runs, why a run failed, job logs, coverage, and pull request checks from GitHub Actions. It works with Claude Code, Cursor, or any MCP client.

```text
> why did the first CI run of vendor-intake-app fail?

failure_summary(repo="dholman7/vendor-intake-app", run_id=40583813096)

Backend (lint, types, tests, OpenAPI drift) -> failed steps ['Set up job']
    ##[error]Unable to resolve action `astral-sh/setup-uv@v10`, unable to find version `v10`
Secret scan -> failed steps ['Run gitleaks/gitleaks-action@v3']
    ERR failed to scan Git repository error="stderr is not empty"
```

That's real output from this repo family's own history: the first run failed because `setup-uv` publishes no `v10` tag.

## Tools

| Tool | Returns |
|---|---|
| `list_runs(repo, branch?, limit?)` | Recent workflow runs, newest first |
| `get_run(repo, run_id)` | One run, its jobs, and the steps that failed |
| `failure_summary(repo, run_id)` | For each failed job: failed steps and up to 30 error lines. The place to start on a red build. |
| `job_log(repo, job_id, pattern?, tail?)` | Log lines with timestamps and color codes removed, filtered by regex, capped at 500 |
| `coverage(repo, run_id)` | Total line coverage per job, read from pytest-cov's report |
| `pr_checks(repo, pr)` | Every check on a pull request's latest commit |

Every tool is marked read-only (`readOnlyHint`) and returns typed, structured output.

## Security model

- **Read-only by construction.** The GitHub client only implements GET. Write endpoints aren't merely unused; they don't exist in the code.
- **A repo allowlist.** Every tool checks `CI_CONTEXT_REPOS` before making any request. Any other repo is refused, even if the token can read it.
- **A narrow token.** Use a fine-grained token with *Actions: read* and *Contents: read* on the listed repos only.
- **The token stays with GitHub.** Log downloads redirect to blob storage. The server follows that redirect itself, without the auth header, so the token never reaches another host. Tests check this.
- **No credentials in logs.** httpx's per-request logging is off: log downloads use signed URLs, which are short-lived credentials, and a stdio server's logs end up in the client's log file. Found by running it against real GitHub.
- **No internals in errors.** Expected failures (401, 403, 404, rate limits) become plain error messages. Anything unexpected reaches the model as a generic error, with details kept in the server log.
- **Logs are untrusted.** CI output can contain anything, including text written to manipulate an agent. Tool descriptions tell the model to treat log text as data, and output is size-capped.

## Set up

```bash
uv sync
```

**Claude Code:**

```bash
claude mcp add ci-context \
  -e GITHUB_TOKEN=github_pat_... \
  -e CI_CONTEXT_REPOS=owner/app,owner/lib \
  -- uv run --project /path/to/ci-context-mcp ci-context-mcp
```

**Cursor** (`.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "ci-context": {
      "command": "uv",
      "args": ["run", "--project", "/path/to/ci-context-mcp", "ci-context-mcp"],
      "env": { "GITHUB_TOKEN": "github_pat_...", "CI_CONTEXT_REPOS": "owner/app,owner/lib" }
    }
  }
}
```

## Tests

`uv run pytest` drives the server through the MCP SDK's in-process client, with GitHub replaced by a mock transport. That covers every tool, the allowlist, error mapping, credential handling on redirects, and logging. No network or token is needed, and CI runs the same suite.

## Not in v1

- Write tools (re-run a job, comment on a PR), and with them per-tool scopes and GitHub App authentication
- Remote HTTP transport with OAuth
- Parsing test reports from artifacts (JUnit, Playwright JSON) instead of logs
- Wiring into [Storywright](https://github.com/dholman7/storywright) as its CI tool layer

## License

[MIT](LICENSE)
