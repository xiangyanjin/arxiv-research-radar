# Scheduling daily scans

The CLI is designed to be called by an external scheduler. The repository does not install a background service, register a recurring task, or send external messages.

## Schedule a command, not a dashboard session

Use your operating system's scheduler, a task runner, or an authorized coding-agent automation. Configure:

- The repository root as the working directory.
- An absolute path to a Python 3.10+ interpreter.
- A persistent data directory and the intended research profile.
- The command `python3 -m radar scan`.
- A named time zone, if the scheduler supports it.

The dashboard does not need to remain open for a CLI scan. The machine must be running and able to reach arXiv. The browser interface is available only while the local `serve` process is running.

## Be explicit about time zones

For example, **09:00 Asia/Shanghai is 01:00 UTC**. If a scheduler uses UTC, configure that UTC time rather than 09:00 UTC. If it uses the host's local zone, confirm how daylight saving time affects the schedule. Time zone settings belong to the scheduler; the application stores scan timestamps in UTC.

## Inspect the run result

`scan` emits a JSON run record. Exit code `0` includes both `success` and `partial`, so a scheduler must inspect `status` and `coverage` rather than using the process exit code alone.

| Result | Handling |
| --- | --- |
| `success` with complete coverage | Use the discovered records and advance normally |
| `partial` | Use available records with a clear coverage warning; the missing interval remains open |
| `failed` / exit code `2` | Report the source failure; do not report “no relevant papers” |
| Busy / exit code `3` | Another scan owns the lock; skip this invocation |
| Configuration or input error / exit code `1` | Fix the error before retrying |

The scanner overlaps its last complete watermark. A partial run, RSS fallback, or interrupted run does not close an unscanned interval.

## Add optional agent reviews and notifications

An agent-enabled scheduler can follow [the harness contract](agent-harness.md) after retrieval:

1. Export and read the review queue.
2. Generate grounded review JSON and import it.
3. Generate the digest.
4. Export a delivery plan and check `should_notify`.
5. Handle any authorized notification, then update the local acknowledgment ledger with the scope actually covered.

The first scan is a historical backfill. Say “first discovered” rather than “published today.” On later runs, stay quiet when nothing relevant or actionable has changed. For recurring failures, use the ledger and your scheduler's own alert policy to avoid repeatedly sending the same notification.

## Hosting and persistence

This application has a Python backend and a writable SQLite database. GitHub Pages can host static documentation, but it cannot run the scanner or the live dashboard backend.

An ephemeral CI runner also needs an explicit strategy for persisting state and delivering results. The bundled GitHub Actions workflow only runs offline tests; it does not scan arXiv or activate daily monitoring.
