# Security

Report a vulnerability privately to danxholman@gmail.com, not in a public issue. Only `main` is supported.

In scope: anything that lets a client read a repository outside `CI_CONTEXT_REPOS`, make a non-GET request, or expose the GitHub token (in a request to a non-GitHub host, a tool result, an error, or a log).

Known limitation: CI log text is untrusted and is returned to the model as-is (ANSI codes and timestamps stripped). The server instructions and tool descriptions tell the client to treat it as data, but a log line can still carry a prompt-injection attempt. Give the server a token that can only read the allowlisted repositories.
