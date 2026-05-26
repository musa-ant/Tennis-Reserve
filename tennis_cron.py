#!/usr/bin/env python3
"""
Rigid scheduled tennis-court booker.

Designed to be invoked once a day at 8:00 AM ET (when RIOC rolls a new
date into the booking window). Books a single, hardcoded slot:

    Court 6, 7:00-9:00 PM, on a target date.

Defaults to "today + 3 days" because the RIOC window opens to that date
at 8 AM. Override via --target-date.

Exits 0 on success, 1 on any failure. Logs to ~/Library/Logs/tennis_cron.log
(or wherever --log-path points).

Examples:
    # Daily 8 AM cron usage (CCR or local launchd):
    python tennis_cron.py

    # Manual / dry-run:
    python tennis_cron.py --target-date 2026-06-05 --dry-run

    # Different court / time:
    python tennis_cron.py --court 3 --start 18:00 --duration 60
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import rioc


def log_line(path: Path, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as f:
            f.write(line + "\n")
    except OSError as e:
        print(f"  (could not write log to {path}: {e})", file=sys.stderr)


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target-date", type=date.fromisoformat,
                    default=date.today() + timedelta(days=3),
                    help="YYYY-MM-DD; default = today + 3 days")
    ap.add_argument("--court", type=int, default=6,
                    help="court number 1-6; default 6")
    ap.add_argument("--start", default="19:00",
                    help="start time HH:MM; default 19:00")
    ap.add_argument("--duration", type=int, default=120,
                    help="duration minutes; default 120 (will fall back to 2x60 on 400)")
    ap.add_argument("--log-path",
                    default=str(Path.home() / "Library/Logs/tennis_cron.log"),
                    help="append-only log file")
    ap.add_argument("--dry-run", action="store_true",
                    help="check availability + plan, but don't submit")
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    log = Path(args.log_path)

    hh, mm = (int(x) for x in args.start.split(":"))
    start = datetime(args.target_date.year, args.target_date.month, args.target_date.day,
                     hh, mm)

    target = f"Court {args.court} {start:%a %Y-%m-%d %H:%M} +{args.duration}min"
    log_line(log, f"=== run: {target}  dry_run={args.dry_run} ===")

    if args.court not in rioc.COURTS:
        log_line(log, f"FAIL: unknown court {args.court}")
        return 1

    try:
        s = rioc.login()
    except SystemExit as e:
        log_line(log, f"FAIL: login error: {e}")
        return 1

    window = rioc.get_window(s)
    if not window.includes(args.target_date):
        log_line(log, f"FAIL: {args.target_date} not in window {window.min_date}..{window.max_date}")
        return 1

    if args.dry_run:
        free = rioc.is_free(s, args.court, start, start + timedelta(minutes=args.duration))
        log_line(log, f"DRY: full {args.duration}min slot free? {free}")
        # Also probe per-hour
        cursor = start
        end = start + timedelta(minutes=args.duration)
        while cursor < end:
            nxt = cursor + timedelta(minutes=60)
            free = rioc.is_free(s, args.court, cursor, nxt)
            log_line(log, f"DRY:   {cursor:%H:%M}-{nxt:%H:%M} free? {free}")
            cursor = nxt
        return 0

    attempts = rioc.book_with_fallback(s, args.court, start, args.duration)
    booked: list[tuple[datetime, datetime]] = []
    for ok, msg, st, sp in attempts:
        prefix = "BOOKED" if ok else "FAIL"
        log_line(log, f"  {prefix}: {st:%H:%M}-{sp:%H:%M}  {msg}")
        if ok:
            booked.append((st, sp))

    if not booked:
        log_line(log, "RESULT: nothing booked")
        return 1

    total_minutes = sum(int((sp - st).total_seconds() // 60) for st, sp in booked)
    log_line(log, f"RESULT: booked {len(booked)} permit(s), {total_minutes} minutes total")
    return 0


if __name__ == "__main__":
    sys.exit(main())
