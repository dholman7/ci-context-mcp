"""How often the strip policy removes an ordinary line: run it over real job logs.

Fetch logs with `gh run view --repo OWNER/REPO --job ID --log | cut -f3- > DIR/NAME.log`, then:
uv run python redteam/false_positives.py DIR
"""

import sys
from pathlib import Path

from ci_context_mcp import logs


def main() -> int:
    files = sorted(Path(sys.argv[1]).glob("*.log"))
    total = removed = 0
    for path in files:
        lines = logs.clean(path.read_text(errors="replace").lstrip("﻿"))
        for line, kept in zip(lines, logs.strip_instructions(lines), strict=True):
            total += 1
            if kept == logs.STRIPPED:
                removed += 1
                print(f"{path.name}: {line[:160]}")
    print(
        f"{len(files)} job logs, {total} lines, {removed} removed ({removed / max(total, 1):.3%})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
