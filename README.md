# RIOC Octagon Tennis Booker

Two modes for booking tennis courts at the Roosevelt Island Octagon via
RIOC CivicPermits:

| Mode | What | When |
|------|------|------|
| **Cron** — `tennis_cron.py` | Rigid daily booker. Court 6, 7–9 PM, today+3 days. | Runs at 8:00 AM ET when the booking window rolls. |
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
1-hour permits (RIOC sometimes caps per-permit duration).

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

Cron expression: `5 8 * * *` (8:05 AM in the routine's timezone — set to
America/New_York). The 5-minute offset gives RIOC's window-roll a beat
to land.

Option B — **macOS launchd** (laptop must be awake at 8 AM):

```xml
<!-- ~/Library/LaunchAgents/com.musa.tennis.plist -->
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.musa.tennis</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/python3</string>
    <string>/Users/musa/public_sandbox/tennis/tennis_cron.py</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/musa/public_sandbox/tennis</string>
  <key>StartCalendarInterval</key><dict>
    <key>Hour</key><integer>8</integer>
    <key>Minute</key><integer>5</integer>
  </dict>
  <key>StandardOutPath</key><string>/Users/musa/Library/Logs/tennis_cron.stdout.log</string>
  <key>StandardErrorPath</key><string>/Users/musa/Library/Logs/tennis_cron.stderr.log</string>
</dict></plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.musa.tennis.plist
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

## Known constraints (as of 2026-05-26)

- **Weekly permit cap** — ~2 active permits per rolling week. Submits 400
  silently if you've hit the cap. Cancel an existing permit to free a slot.
- **2-hour permits sometimes 400** — the cron's fallback handles this.
- **HTTP 200 from submit = booked**. Response body is empty; permit IDs only
  visible in My Permits (client-rendered, can't be scraped from raw GET).

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
