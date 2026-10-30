"""
DEPRECATED entrypoint.

The orchestrator now lives in scripts/agents/orchestrator.py and is run as a
module from the project root:

    python -m scripts.agents.orchestrator [--only NAME] [--agents ...] [--headed] [--dry-run] [--no-reindex]

This shim forwards to that module so existing `python scripts/orchestrator.py ...`
invocations keep working (all flags pass through unchanged).
"""

import runpy
import sys
from pathlib import Path

# Make the project root importable so `scripts.agents...` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if __name__ == "__main__":
    print(
        "[note] scripts/orchestrator.py is deprecated - use "
        "`python -m scripts.agents.orchestrator`",
        file=sys.stderr,
    )
    runpy.run_module("scripts.agents.orchestrator", run_name="__main__", alter_sys=True)
