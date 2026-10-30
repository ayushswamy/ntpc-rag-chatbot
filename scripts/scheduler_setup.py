"""
Scheduler setup helper.

Prints the exact cron line (Linux/macOS) or Windows Task Scheduler XML
needed to run the orchestrator on a schedule, using the current Python
interpreter and the project's absolute paths.

Usage:
    python scripts/scheduler_setup.py --cron "0 12 * * *"       # Linux/macOS
    python scripts/scheduler_setup.py --windows --time 12:00     # Windows
    python scripts/scheduler_setup.py --show                      # Show both

Note: the live Windows job (NTPC_FetchAgents) is already registered to run
daily at 12:00 PM. This helper only PRINTS schedule config for re-creating it.
"""

import argparse
import os
import sys
from pathlib import Path
from textwrap import dedent

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
PYTHON = sys.executable
# The orchestrator is run as a module from the project root (re-indexing is wired in).
ORCHESTRATOR_MODULE = "scripts.agents.orchestrator"


def _cron_snippet(cron_expr: str) -> str:
    log_dir = PROJECT_ROOT / "logs" / "agents"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "cron.log"
    return dedent(f"""\
        # NTPC fetch-agent — add to crontab with: crontab -e
        {cron_expr}  cd "{PROJECT_ROOT}" && "{PYTHON}" -m {ORCHESTRATOR_MODULE} >> "{log_path}" 2>&1
    """)


def _windows_xml(time_str: str) -> str:
    hour, minute = time_str.split(":")
    return dedent(f"""\
        <?xml version="1.0" encoding="UTF-16"?>
        <Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
          <Triggers>
            <CalendarTrigger>
              <StartBoundary>2024-01-01T{time_str}:00</StartBoundary>
              <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
            </CalendarTrigger>
          </Triggers>
          <Actions Context="Author">
            <Exec>
              <Command>{PYTHON}</Command>
              <Arguments>-m {ORCHESTRATOR_MODULE}</Arguments>
              <WorkingDirectory>{PROJECT_ROOT}</WorkingDirectory>
            </Exec>
          </Actions>
          <Settings>
            <ExecutionTimeLimit>PT2H</ExecutionTimeLimit>
            <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
          </Settings>
        </Task>
    """)


def main():
    parser = argparse.ArgumentParser(
        description="Print schedule config for the NTPC fetch-agent orchestrator."
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--cron",
        metavar="EXPR",
        default="0 12 * * *",
        help='Cron expression (default: "0 12 * * *" — 12 PM / noon daily)',
    )
    group.add_argument(
        "--windows",
        action="store_true",
        help="Output Windows Task Scheduler XML instead of cron.",
    )
    parser.add_argument(
        "--time",
        default="12:00",
        help="HH:MM for the Windows XML (default: 12:00 / noon)",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Show both cron and Windows snippets.",
    )
    args = parser.parse_args()

    if args.show:
        print("=== Linux / macOS cron ===")
        print(_cron_snippet(args.cron))
        print("=== Windows Task Scheduler XML ===")
        print(_windows_xml(args.time))
        return

    if args.windows:
        print(_windows_xml(args.time))
        print("\n# Import with:  schtasks /Create /XML ntpc_agents.xml /TN NTPC_FetchAgents")
    else:
        print(_cron_snippet(args.cron))
        print("# Install with:  crontab -e   then paste the line above.")


if __name__ == "__main__":
    main()
