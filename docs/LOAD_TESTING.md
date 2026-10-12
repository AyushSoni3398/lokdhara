# Load testing

How the submission flow behaves under load, measured with synthetic data on a local machine.
Requested by the owner on 2026-10-12 and run after Milestone 3 ([ROADMAP.md](ROADMAP.md)).

## 1. How to run it

```bash
docker compose -f infra/docker-compose.yml up -d db      # from the repository root
bash backend/loadtest/run.sh 50 5m                       # users, duration
```

`run.sh` installs the `loadtest` dependency group (Locust; not installed by `uv sync` or CI),
then:

1. recreates a separate database, `lokdhara_loadtest`, and migrates it (`loadtest/prepare.py`);
   the development database is never touched;
2. adds the test consent forms and prompts and creates the contributor accounts with random
   passwords (kept in the git-ignored `loadtest/results/`);
3. starts the API (2 uvicorn processes) and one worker, pinned to 2 cores to match the pilot
   VM (2 vCPU, [INFRASTRUCTURE_AND_COSTS.md](INFRASTRUCTURE_AND_COSTS.md)), with uploads going
   to a temporary folder that is deleted afterwards;
4. runs Locust (`loadtest/locustfile.py`) on the other cores and samples the job queue every
   5 seconds (`loadtest/monitor.py`).

Results land in `backend/loadtest/results/`: Locust's `run_stats.csv`, `run_failures.csv`, and
`run_stats_history.csv`, the queue samples in `queue.csv`, and the API and worker logs.

Everything sent is synthetic: recordings are generated tones (`loadtest/audio.py`) and text is
placeholder Hindi. Nothing leaves the machine. Never point the script at staging or production.

### What a simulated contributor does

Each user signs in once, creates their own speaker profile and gives the test consent, then
loops with a 1 to 5 second pause between actions:

| Weight | Action | Requests |
|-------:|--------|----------|
| 4 | Send a recording (30% from a prompt) | create draft, upload, transcription (half the time), submit |
| 1 | Send a text with an English translation | create draft, 2 text layers, submit |
| 3 | Look at "my submissions" | `GET /auth/me`, `GET /submissions` |
| 1 | Ask for a prompt | `GET /prompts/next` |

Recordings are 20 s, 90 s, or 4 min long (weights 6, 3, 1): about 0.3, 1.4, and 3.8 MB,
roughly the size of phone recordings, about 1 MB on average.

**One simulated user is much busier than a real person.** In the 50-user run each one uploaded
about 9 recordings a minute. A real contributor who spends a few minutes on each recording
makes about one upload every 3 minutes, so one simulated user stands for roughly 25 active
people. To let this happen, the run raises the 60-uploads-an-hour limit per account.

## 2. Results (2026-10-12)

Machine: a 4-core Intel Xeon at 2.1 GHz with 15 GB of memory (a cloud container). API and
worker were pinned to 2 cores, Locust to the other 2; PostgreSQL 18.6 ran in Docker without a
CPU limit. Python 3.13, Locust 2.46, objects on the local disk (S3 was not part of this run).
Users were started at 10 a second.

| Users | Length | Requests/s | Errors | Median | 95th pct | 99th pct | Uploads/s |
|------:|-------:|-----------:|-------:|-------:|---------:|---------:|----------:|
| 50 | 5 min | 48 | 0 of 14,228 | 23 ms | 69 ms | 170 ms | 7.2 |
| 150 | 3 min | 118 | 0 of 21,108 | 120 ms | 620 ms | 1.4 s | 17.8 |
| 300 | 3 min | 24 | 214 of 4,273 | 150 ms | 60 s | 120 s | 2.9 |

At 50 users the server took in 2,165 recordings (2.0 GB) in 5 minutes. The pilot plans for
200 hours of audio in the first year ([INFRASTRUCTURE_AND_COSTS.md](INFRASTRUCTURE_AND_COSTS.md),
assumption A3): at about 2 minutes per recording that is roughly 6,000 recordings, which this setup would
receive in about 15 minutes. Upload capacity is not a concern for the pilot.

**Where it breaks.** Between 150 and 300 of these very busy users, the 2 cores are saturated.
Requests then wait for a database connection for 30 seconds and fail with `500`
(`QueuePool limit … reached`). A second run at 300 users with the password-hashing limit
(below) switched off behaved the same way (4,688 requests, 190 errors), so the limit does not
cause this. For comparison, 300 simulated users stand for several thousand people recording at
the same moment.

**Signing in is the most expensive request.** Checking a password (Argon2id, 64 MiB) takes
about 0.25 s of CPU, so 2 cores sign in about 8 people a second. When 50 users all signed in
within 5 seconds the slowest waited 4.3 s (median 2.7 s). That is acceptable: sessions last a
week, so people rarely sign in all at once.

**The worker.** M3 has no audio or text handlers yet (they arrive in M4), so every
`audio.validate` and `text.derive` job ends as `failed` with `no_handler`. The queue machinery
itself kept up: about 12 jobs a second were claimed and closed, and at most 85 (50 users) and
195 (150 users) jobs were waiting at any moment. **When the worker falls behind can only be
measured once M4's real handlers (ffprobe and a full decode of every recording) exist**; this
test should be rerun then.

## 3. Problems found and fixed

| Problem | Seen as | Fix |
|---------|---------|-----|
| uvicorn closes idle connections after 5 s; a client (or Caddy) reusing one at that moment gets a reset | 3 of 14,133 requests failed with "connection reset" at 50 users | `run.sh` uses `--timeout-keep-alive 75`; [DEPLOYMENT.md](DEPLOYMENT.md) §3 now asks for that, with Caddy's upstream keep-alive shorter (60 s) |
| Sign-in kept its database transaction open during the slow password check | At 150 users, 78 errors: other requests timed out waiting for a connection | The read is ended before the check (`identity.service.login`); test `test_password_check_holds_no_database_connection` |
| No limit on simultaneous password checks; each uses 64 MiB | Not seen as an error here, but 80 at once (2 processes × 40 threads) would need about 5 GB on a 4 GB server | At most one check per core per API process (`app.security`); test `test_password_checks_wait_for_a_free_slot` |

With these fixes, sign-in at 50 users went from a 6.9 s to a 2.7 s median, and the 150-user
run went from 78 errors to none.

## 4. Follow-ups before M8

These are not fixed yet. Each should become a GitHub issue:

1. **Fail fast when overloaded.** Waiting 30 s for a connection and then answering `500` is the
   worst outcome for a phone on a slow network. Answer `503` with `Retry-After` quickly instead
   (a shorter pool timeout plus a handler), so the app's existing retry takes over.
2. **Rerun after M4** with the real audio handlers, to find how many recordings an hour one
   worker can validate and when a second worker is needed.
3. **Rerun against S3-compatible storage** before production, since uploads stream to object
   storage there, not to a local disk.
4. **Size the database pool** with the deployment: each API process may open 15 connections,
   so 2 processes, the worker, and backups must stay under PostgreSQL's `max_connections`.
