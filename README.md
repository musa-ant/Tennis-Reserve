# RIOC Octagon Tennis Booker

Two modes for booking tennis courts at the Roosevelt Island Octagon via
RIOC CivicPermits:

| Mode | What | When |
|------|------|------|
| **Cron** — `tennis_cron.py` | Rigid daily booker. Court 6, today+3 days (defaults to 7–9 PM / 120 min — see caveat, use 60 min). | Runs 8:05 AM ET, weekdays, when the booking window rolls. |
| **Skill** — `/tennis` | Conversational. Ask for availability, book ad-hoc slots. | Whenever you want, from any Claude Code session. |

Both modes share `rioc.py` as the single source of truth for HTTP shapes.

## Setup

1. Credentials at `~/.tennis_creds` (chmod 600):
   ```
   RIOC_USER=you@example.com
   RIOC_PASS=secret
   ```
2. `pip3 install requests` (already standard).
3. Smoke-test: `python3 rioc.py` — should print booking window + open slots.

## Mode 1: Rigid cron

```
python3 tennis_cron.py [--target-date YYYY-MM-DD] [--court N] [--start HH:MM]
                       [--duration MINUTES] [--dry-run] [--log-path PATH]
```

Defaults: Court 6, 19:00, 120 minutes, target = today + 3 days. The
script attempts a single 2-hour permit; on HTTP 400 it falls back to two
1-hour permits.

> ⚠️ **The 120-minute default conflicts with the official rules** (see below):
> RIOC allows one-hour permits only, and one reservation per player per day —
> so neither the 2-hour permit nor the two-back-to-back-1-hour fallback can
> actually clear. Run the cron with `--duration 60` for a single 1-hour permit.
> Also schedule it **weekdays only** (`5 8 * * 1-5`): weekend submissions are
> auto-canceled by RIOC. The hardcoded today+3 target tracks what the server
> window actually returns, but RIOC's stated rule is "two days in advance" —
> trust `get_window`/`window.includes()` to reject out-of-range dates rather
> than the offset.

Logs append to `~/Library/Logs/tennis_cron.log`. Exit 0 on success, 1
otherwise.

### Scheduling at 8 AM ET daily

Option A — **CCR via `/schedule`** (recommended; runs in cloud, laptop
can be asleep):

Push this directory to a git repo, then from any Claude Code session run
`/schedule` and create a routine that clones the repo and runs:

```bash
python3 tennis_cron.py
```

Cron expression: `5 8 * * 1-5` (8:05 AM weekdays only, in the routine's
timezone — set to America/New_York). The 5-minute offset gives RIOC's
window-roll a beat to land; weekdays-only matches RIOC's Mon–Fri 8 AM–4 PM
submission window (weekend submissions are auto-canceled).

Option B — **macOS launchd** (laptop must be awake at 8 AM):

```xml
<!-- ~/Library/LaunchAgents/com.example.tennis.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.example.tennis</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>/path/to/tennis/tennis_cron.py</string>
  </array>
  <key>WorkingDirectory</key><string>/path/to/tennis</string>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>8</integer>
    <key>Minute</key><integer>5</integer>
  </dict>
  <key>StandardOutPath</key><string>~/Library/Logs/tennis_cron.stdout.log</string>
  <key>StandardErrorPath</key><string>~/Library/Logs/tennis_cron.stderr.log</string>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.example.tennis.plist
```

## Mode 2: `/tennis` skill

Already installed at `~/.claude/skills/tennis/SKILL.md`. From any Claude
Code session:

```
/tennis what's open this week
/tennis book Friday 7pm court 3
/tennis list my permits
```

The skill loads the library and walks you through availability checks,
booking confirmation, and result reporting.

## Official RIOC rules (rioc.ny.gov, as of 2026-06-29)

These published rules supersede the earlier empirical guesses.

- **One reservation per player per day.** This is the real limit — *not* a
  weekly cap of 2 (that earlier note was a misread of one-per-day plus a short
  booking window). A second same-day request 400s.
- **One-hour reservations only.** No 2-hour, no half-hour. Because of the
  one-per-day limit, you can't stitch two back-to-back 1-hour permits on the
  same day either — a 2-hour session is effectively impossible. See the cron
  caveat below.
- **First come, first serve.** Open to residents and non-residents; no
  lottery, staff discretion, or waitlist — earliest submission wins the slot.
- **Submission window is strict: Mon–Fri, 8 AM–4 PM ET only.** Requests
  submitted outside these hours are *canceled by RIOC*. Same-day requests must
  be in by **3 PM on weekdays**. Monday/Tuesday and holiday reservations are
  submitted on **Fridays**. No weekend submissions. This is why the cron runs
  at 8:05 AM on weekdays.
- **Reservations open two days in advance.** Trust `get_window` for the exact
  bookable range rather than a hardcoded offset.
- **Court hours:** first slot 7:00 AM, last slot *starts* 9:00 PM; courts open
  7 AM–10 PM. **Season: April 1 – November 30**, closed in winter (window is
  empty off-season).
- **HTTP 200 from submit = request accepted on a first-come basis, NOT a
  guaranteed grant.** Response body is empty; permit IDs only visible in My
  Permits (client-rendered, can't be scraped from raw GET). A 200 on a request
  made outside the submission window will still be auto-canceled.
- **Cancellation:** email the **permit number** to **permits@rioc.ny.gov**,
  at least **24 hours ahead** to re-book. No cancel-by-API.
- **In person:** max 4 per court (singles or doubles, all courts); only the
  permitted players — no coaches; bring ID + printed/on-screen confirmation; no
  charging participants; no lessons unless sponsored by NYJTL, RI Tennis
  Association, or RI Racquet Club; **16 and under** must be accompanied by an
  adult 21+.

## What the availability check can (and can't) see

`is_free` / `find_open_slots` hit a single endpoint, `/Permits/ConflictCheck`,
and treat an empty response as "open." It's a binary per-slot yes/no — *does
this time conflict with something the system considers blocking?* — and
nothing more.

- **No demand or queue visibility.** There is no applicant count, waitlist, or
  "popular slot" signal. If 20 people requested 9–10 PM, the check still just
  returns open-or-conflict. That data is not exposed to us at all, so an "open"
  slot is no guarantee you're first in line or that you'll win it.
- **Pending vs. approved is unverified.** It's unknown whether a
  submitted-but-unapproved request flips a slot to "conflict," or whether only
  RIOC-approved permits do. So an "open" slot may already have invisible
  requests sitting against it. Untested as of this writing — to settle it,
  submit a request for a slot, then re-run `is_free` on that same slot and see
  whether your own pending request reads as conflicted.

## Files

```
tennis/
├── rioc.py            ← shared library (login, is_free, submit, find_open_slots)
├── tennis_cron.py     ← rigid daily booker (Mode 1)
└── README.md          ← this file

~/.claude/skills/tennis/
└── SKILL.md           ← /tennis skill (Mode 2)

~/.tennis_creds        ← credentials (chmod 600)
~/Library/Logs/tennis_cron.log  ← cron output
```
