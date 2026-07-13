"""Command-line entry point.

    python -m selfcorrect_agent path/to/file.py            # opens the review website
    python -m selfcorrect_agent path/to/file.py --mock     # offline demo provider
    python -m selfcorrect_agent path/to/file.py --headless # run cycle, print result
    python -m selfcorrect_agent path/to/file.py --headless --apply
"""
from __future__ import annotations

import argparse
import os
import sys

from .config import Config


def main(argv=None):
    ap = argparse.ArgumentParser(prog="selfcorrect_agent",
                                 description="Self-correcting code agent.")
    ap.add_argument("file", help="path to the file to improve")
    ap.add_argument("--mock", action="store_true", help="use the offline mock provider")
    ap.add_argument("--headless", action="store_true", help="no UI; run the cycle and print")
    ap.add_argument("--apply", action="store_true",
                    help="(headless) apply the change if the cycle is ready")
    ap.add_argument("--no-browser", action="store_true", help="do not auto-open the browser")
    ap.add_argument("--port", type=int, default=None)
    args = ap.parse_args(argv)

    if args.mock:
        os.environ["SELFCORRECT_MOCK"] = "1"
    config = Config()
    if args.port:
        config.port = args.port

    if args.headless:
        from . import run_headless
        s = run_headless(args.file, config)
        print(f"\nStatus: {s.status}  |  attempts: {s.attempts_used}  |  {s.final_summary}")
        print(f"Changed: {s.changed}")
        if s.rationale:
            print(f"Rationale: {s.rationale}")
        print("\n--- proposed diff ---")
        print(s.unified_diff or "(no change)")
        if args.apply and s.status == "ready" and s.changed:
            s.apply()
            print(f"\nApplied. Backup: {s.backup_path}")
            if s.test_path:
                print(f"Tests written: {s.test_path}")
        return 0

    from . import improve_file
    improve_file(args.file, config, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    sys.exit(main())
