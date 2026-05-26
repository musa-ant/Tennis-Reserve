"""
RIOC Octagon CivicPermits client library.

Shared primitives used by tennis_cron.py (rigid scheduled booker) and the
/tennis Claude Code skill (conversational booker). Single source of truth
for HTTP shapes; both modes import from here.

Conventions:
  - All functions raise on HTTP/transport errors; callers decide what to do.
  - `submit()` returns the raw `requests.Response`; HTTP 200 means RIOC accepted
    the permit. (Verified empirically 2026-05-26: 200 = visible in My Permits.)
  - Times are naive datetimes in America/New_York wall-clock — RIOC expects that.

Credentials come from ~/.tennis_creds (chmod 600), format:
    RIOC_USER=you@example.com
    RIOC_PASS=secret
"""
from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable

import requests

BASE = "https://rioc.civicpermits.com"

COURTS: dict[int, str] = {
    1: "036dfea4-c487-47b0-b7fe-c9cbe52b7c98",
    2: "175bdff8-016e-46ab-a9df-829fe40c0754",
    3: "9bdef00b-afa0-4b6b-bf9a-75899f7f97c7",
    4: "d311851d-ce53-49fc-9662-42adcda26109",
    5: "8a5ca8e8-3be0-4145-a4ef-91a69671295b",
    6: "77c7f42c-8891-4818-a610-d5c1027c62fe",
}

# Permit-request question answers. IDs were captured 2026-05-26 from a
# successful booking; if RIOC changes the form these will need re-capture
# (look at a working POST body in DevTools).
RESPONSES = [
    {"Id": "11e79e5d3daf4712b9e6418d2691b976", "StringValue": "Tennis with friends", "CheckboxValue": []},
    {"Id": "af8966101be44676b4ee564b052e1e87", "StringValue": "4",    "CheckboxValue": []},
    {"Id": "f28f0dbea8b5438495778b0bb0ddcd93", "StringValue": "No",   "CheckboxValue": []},
    {"Id": "d46cb434558845fb9e0318ab6832e427", "StringValue": "No",   "CheckboxValue": []},
    {"Id": "1221940f5cca4abdb5288cfcbe284820", "StringValue": "",     "CheckboxValue": []},
    {"Id": "3754dcef7216446b9cc4bf1cd0f12a2e", "StringValue": "No",   "CheckboxValue": []},
    {"Id": "0ce54956c4b14746ae5d364507da1e85", "StringValue": "No",   "CheckboxValue": []},
    {"Id": "6b1dda4172f840c7879662bcab1819db", "StringValue": "No",   "CheckboxValue": []},
    {"Id": "06b3f73192a84fd6b88758e56a64c3ad", "StringValue": "No",   "CheckboxValue": []},
    {"Id": "a31f4297075e4dab8c0ef154f2b9b1c1", "StringValue": "None", "CheckboxValue": []},
]

ACTIVITY_TEXT = "Tennis"
SLOT_MINUTES_DEFAULT = 60

JSON_HDR = {"Content-Type": "application/json; charset=utf-8",
            "X-Requested-With": "XMLHttpRequest"}

CREDS_PATH = Path.home() / ".tennis_creds"


# --------------------------------------------------------------------- utils

def _read_creds() -> tuple[str, str]:
    """Parse ~/.tennis_creds. Env vars (RIOC_USER/RIOC_PASS) override."""
    user = os.environ.get("RIOC_USER")
    pwd  = os.environ.get("RIOC_PASS")
    if user and pwd:
        return user, pwd
    if not CREDS_PATH.exists():
        sys.exit(f"No credentials. Set RIOC_USER/RIOC_PASS or create {CREDS_PATH} (chmod 600).")
    kv: dict[str, str] = {}
    for line in CREDS_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        kv[k.strip()] = v.strip()
    try:
        return kv["RIOC_USER"], kv["RIOC_PASS"]
    except KeyError:
        sys.exit(f"{CREDS_PATH} missing RIOC_USER or RIOC_PASS.")


def _ms_epoch_to_date(s: str) -> date:
    """Parse ASP.NET '/Date(1779813995860)/' into a date."""
    m = re.search(r"\d+", s)
    if not m:
        raise ValueError(f"unparseable ASP.NET date: {s!r}")
    return datetime.fromtimestamp(int(m.group()) / 1000).date()


def court_name(court: int) -> str:
    return f"Court {court}"


def fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S")


# --------------------------------------------------------------------- session

def login() -> requests.Session:
    """Authenticate against /Account/Login. Returns a Session with .ASPXAUTH set."""
    user, pwd = _read_creds()
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0",
                      "X-Requested-With": "XMLHttpRequest"})
    s.get(BASE + "/")  # seed session cookies
    r = s.post(BASE + "/Account/Login",
               data={"email": user, "password": pwd})
    if ".ASPXAUTH" not in s.cookies:
        sys.exit(f"Login failed (HTTP {r.status_code}). Check ~/.tennis_creds.")
    return s


# --------------------------------------------------------------------- window

@dataclass
class BookingWindow:
    min_date: date
    max_date: date
    blocked_dates: set[date]
    weekdays_blocked_mask: int  # bitfield Sun=1 … Sat=64

    def weekday_blocked(self, d: date) -> bool:
        # Server bits: Sun=1, Mon=2, Tue=4, Wed=8, Thu=16, Fri=32, Sat=64.
        # Python: Mon=0..Sun=6.
        bit = [2, 4, 8, 16, 32, 64, 1][d.weekday()]
        return bool(self.weekdays_blocked_mask & bit)

    def includes(self, d: date) -> bool:
        if not (self.min_date <= d <= self.max_date):
            return False
        if d in self.blocked_dates:
            return False
        if self.weekday_blocked(d):
            return False
        return True


def get_window(s: requests.Session) -> BookingWindow:
    j = s.get(BASE + "/Permits/UseDateRestrictions").json()
    return BookingWindow(
        min_date=_ms_epoch_to_date(j["MinDate"]),
        max_date=_ms_epoch_to_date(j["MaxDate"]),
        blocked_dates={datetime.fromisoformat(d).date() for d in j.get("Dates", [])},
        weekdays_blocked_mask=j.get("WeekDays", 0),
    )


# --------------------------------------------------------------------- availability

def is_free(s: requests.Session, court: int, start: datetime, stop: datetime) -> bool:
    body = {"FacilityNames": ["Tennis Courts"],
            "FacilityIds":   [COURTS[court]],
            "Dates": [{"Start": fmt_dt(start), "Stop": fmt_dt(stop)}]}
    r = s.post(BASE + "/Permits/ConflictCheck",
               data=json.dumps(body), headers=JSON_HDR)
    return r.ok and r.json() == []


@dataclass(frozen=True)
class Slot:
    date: date
    start: datetime
    stop: datetime
    court: int

    def label(self) -> str:
        return f"{self.start:%a %Y-%m-%d %H:%M}-{self.stop:%H:%M} Court {self.court}"


def find_open_slots(
    s: requests.Session,
    window: BookingWindow,
    courts: Iterable[int],
    start_hours: Iterable[int],
    slot_minutes: int = SLOT_MINUTES_DEFAULT,
    *,
    workers: int = 12,
) -> list[Slot]:
    """Fan-out ConflictCheck across (date × court × start_hour). Returns open Slots."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    candidates: list[Slot] = []
    d = window.min_date
    while d <= window.max_date:
        if window.includes(d):
            for h in start_hours:
                start = datetime(d.year, d.month, d.day, h, 0)
                if start <= datetime.now():
                    continue
                stop = start + timedelta(minutes=slot_minutes)
                for c in courts:
                    candidates.append(Slot(d, start, stop, c))
        d += timedelta(days=1)

    free: list[Slot] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {pool.submit(is_free, s, slot.court, slot.start, slot.stop): slot
                for slot in candidates}
        for f in as_completed(futs):
            slot = futs[f]
            try:
                if f.result():
                    free.append(slot)
            except Exception:
                pass
    free.sort(key=lambda x: (x.date, x.start, x.court))
    return free


# --------------------------------------------------------------------- submit

def submit(s: requests.Session, court: int, start: datetime, stop: datetime,
           *, activity: str = ACTIVITY_TEXT) -> requests.Response:
    """POST /Permits. Returns raw Response. HTTP 200 = accepted (verified 2026-05-26)."""
    event = {"FacilityNames": ["Tennis Courts"],
             "FacilityIds":   [COURTS[court]],
             "Dates": [{"Start": fmt_dt(start), "Stop": fmt_dt(stop)}]}
    payload = {"Activity": activity, "Note": "", "Comments": "",
               "IsPrivate": False, "Events": [event], "Responses": RESPONSES}
    return s.post(BASE + "/Permits", data=json.dumps(payload), headers=JSON_HDR)


def book_slot(s: requests.Session, court: int, start: datetime, stop: datetime) -> tuple[bool, str]:
    """High-level: verify free, then submit. Returns (ok, message)."""
    if not is_free(s, court, start, stop):
        return False, "slot is no longer free"
    r = submit(s, court, start, stop)
    if r.ok:
        return True, f"HTTP {r.status_code}"
    return False, f"HTTP {r.status_code}: {r.text[:160]!r}"


def book_with_fallback(
    s: requests.Session,
    court: int,
    start: datetime,
    duration_minutes: int,
) -> list[tuple[bool, str, datetime, datetime]]:
    """Try one permit covering [start, start+duration]. On 400, fall back to back-to-back
    1-hour permits. Returns list of (ok, msg, st, sp) for every submit attempted.
    """
    end = start + timedelta(minutes=duration_minutes)
    attempts: list[tuple[bool, str, datetime, datetime]] = []

    # First attempt: single permit
    ok, msg = book_slot(s, court, start, end)
    attempts.append((ok, msg, start, end))
    if ok or duration_minutes <= 60:
        return attempts

    # Fallback: hour-by-hour
    cursor = start
    while cursor < end:
        nxt = cursor + timedelta(minutes=60)
        ok, msg = book_slot(s, court, cursor, nxt)
        attempts.append((ok, msg, cursor, nxt))
        if not ok:
            break
        cursor = nxt
    return attempts


# --------------------------------------------------------------------- self-test
if __name__ == "__main__":
    # Read-only smoke test: login + show window + count open weekday-evening slots.
    s = login()
    w = get_window(s)
    print(f"Window: {w.min_date} → {w.max_date}  blocked={len(w.blocked_dates)}")
    open_slots = find_open_slots(s, w, courts=range(1, 7), start_hours=[19, 20, 21])
    print(f"Open weekday-evening (7-10pm) slots: {len(open_slots)}")
    for slot in open_slots[:10]:
        print(" ", slot.label())
