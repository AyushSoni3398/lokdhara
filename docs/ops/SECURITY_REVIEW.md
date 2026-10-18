# Security review before the pilot (Milestone 8)

Date: 2026-10-18. Reviewed: the code on `main` plus the Milestone 8 branches (backups, monitoring,
two-step sign-in), the production Compose file and Caddy configuration. This is a review by the
project team, not an outside audit or a certification.

What it covers: the threat model in [PRIVACY_AND_SECURITY.md](../PRIVACY_AND_SECURITY.md) §1
checked against the code, the checklist in §9, and what was found and fixed on the way. Items
marked **on the server** can only be checked once the real server exists (Q-L7, Q-P5); they
are steps in the [runbook](RUNBOOK.md), repeated here so nobody opens the pilot without them.

## 1. Findings

| # | Severity | Finding | Status |
|---|----------|---------|--------|
| F1 | Medium | Export packages were served by object storage without `Content-Disposition: attachment`, so a browser could open them in place instead of saving them. | Fixed: signed links for exports always download, under a checked file name (`attachment_header`). |
| F2 | Medium | The API's access log recorded each visitor's real IP address, because the API trusts Caddy's forwarded address. | Fixed: the API access log is off in production (`--no-access-log`); Caddy logs requests without client addresses. |
| F3 | Medium | Database error messages carried the values of the failed query (names, text, tokens), and errors are logged. | Fixed: every engine uses `hide_parameters=True`. |
| F4 | Medium | The redacting log filter the observability plan describes did not exist. | Fixed: `app/log_privacy.py` masks IP addresses, emails, bearer tokens and `password=`/`token=`/`cookie=`/`sig=`-style values in messages, arguments and tracebacks for the API and worker; tested in `tests/test_log_privacy.py`. |
| F5 | Low | The worker container, which runs FFmpeg on files strangers send, had no CPU, memory or process limits and could starve the database on a 2 vCPU / 4 GB server. | Fixed: 1 CPU, 1 GB and 256 processes by default (`LKD_WORKER_CPUS`, `LKD_WORKER_MEMORY`). |
| F6 | Low | Consent evidence uses the same storage key as the other buckets; the plan asks for separate credentials. Only the API reads it and nothing serves it to users. | Accepted for the pilot. When hosting is chosen, give the consent-evidence bucket its own key if the provider supports per-bucket keys. |
| F7 | Low | If the API process is killed between storing an upload in quarantine and saving its row, the file stays with nothing pointing to it. Every normal error path already deletes it. | Accepted. On the server, add lifecycle rules to the quarantine bucket: delete objects older than 45 days (drafts keep audio for 30) and abort unfinished multipart uploads after 1 day. |
| F8 | Info | Upload rate limits are per person, not per IP address as the plan says. Uploading needs a signed-in account, so a per-person limit covers it. | Accepted; plan corrected. |

No finding involved data already collected: no real data exists yet.

## 2. Threat model against the code

| Threat | Controls in the code | Evidence |
|--------|---------------------|----------|
| Committing data to Git | `.gitignore`, forbidden-files check and gitleaks in CI; synthetic fixtures made at test time | `scripts/check-forbidden-files.sh`, CI job *Repository safety* |
| Public bucket | Buckets are private; audio is reached only through short-lived signed links checked by the effective-access rule | `app/modules/consents/access.py`; **on the server**: §4 |
| Logs holding personal data | No client filenames, text or addresses logged; redacting filter; query values hidden | F2, F3, F4; `tests/test_recording_uploads.py::test_client_filenames_are_not_logged` |
| Wrong release filter | Releases selected by consent flags and effective access; withdrawn items patched out | `tests/test_releases.py`, `tests/test_release_withdrawals.py` |
| Credential stuffing | Argon2id passwords, lockout per account and per (hashed) IP, two-step sign-in required for admins | `tests/test_auth.py`, `tests/test_mfa.py` |
| Malicious uploads | Magic-byte allow-list, server-made keys, size cap while streaming, FFmpeg limited to local files with a time limit, worker runs as a non-root user with no added privileges and capped resources | `tests/test_upload_fuzz.py` (28 broken files), `app/audio/ffmpeg.py`, F5 |
| XSS | React escaping, no `dangerouslySetInnerHTML`, CSP `default-src 'self'` checked in a real browser with no violations | `infra/prod/Caddyfile` |
| CSRF | SameSite cookies and a CSRF token header on every change | `tests/test_auth.py` |
| SSRF | The server fetches no user-supplied URLs; FFmpeg `-protocol_whitelist file` | `app/audio/ffmpeg.py` |
| Injection | SQLAlchemy parameters everywhere; the one built statement uses a fixed list of table names | `app/modules/ops/restore.py` |
| Insider misuse | Export approval step, audit events for identity reads and exports, append-only audit table | `app/modules/speakers/service.py`, `app/modules/releases/exports.py` |
| Missing role checks | Every API path is called signed out (must answer 401) and every admin path as a contributor (must answer 403); the list comes from the app, so new paths are covered automatically | `tests/test_route_access.py` |
| Loss | Encrypted daily backups off-site, hourly withdrawal log, restore check | ADR-023, [restore-drills.md](restore-drills.md) |
| Vulnerable libraries | `pip-audit` and `npm audit` in CI (reports, does not block merging) | CI job *Dependency audit*; 0 known vulnerabilities on 2026-10-18 |

## 3. Checklist (PRIVACY_AND_SECURITY §9)

| Item | Status |
|------|--------|
| Threat model reviewed against implemented code | Done (§2). |
| Permission tests cover the full matrix | Done: `tests/test_route_access.py` for every path, plus the per-role rules in `tests/test_effective_access.py`, `tests/test_catalogue.py` and the module tests. |
| Upload fuzzing with malformed files | Done: 7 formats × 4 kinds of damage; each ends rejected with a code or promoted unchanged, never a stuck job, never a file left in quarantine. |
| Dependency audit clean or triaged | Done: clean on 2026-10-18; CI keeps reporting. |
| Buckets verified non-public from outside | **On the server** (§4). |
| Backup restore drill, including withdrawal re-application | Rehearsed on a test copy on 2026-10-18; **repeat on the server** before the pilot. |
| Admin MFA enabled | Built and required by default; **each admin sets it up** on the server. |
| Incident contacts documented | Template in [RUNBOOK.md](RUNBOOK.md) §8; **names needed** from the project lead. |

## 4. Checks to run on the real server before the pilot

1. From your own computer (not the server), each bucket must refuse anonymous access:
   `curl -sI https://<storage-endpoint>/<bucket>/` and a known object key both answer 403 (or 404), never 200.
2. `curl -sI https://<your-domain>/` shows `Strict-Transport-Security`, `Content-Security-Policy`,
   `X-Content-Type-Options: nosniff` and no `Server` header.
3. Only ports 22, 80 and 443 answer from outside (`nmap -Pn <server>` from your own computer).
4. Run a restore drill (RUNBOOK §5) and record it in [restore-drills.md](restore-drills.md).
5. Every admin signs in once and sets up two-step sign-in; the status page shows no alerts.
6. The quarantine lifecycle rules from F7 are in place.

## 5. Differences from the plan, recorded

- `Referrer-Policy: no-referrer` instead of `same-origin`: stricter, nothing in the app needs the referrer.
- `Permissions-Policy` allows the microphone on the whole site, not only the recording page: the app is a single page, so the browser sees one route.
- IP addresses are stored as a keyed hash with the server's secret key, not a rotating salt: it cannot be reversed without the key, and it lets sign-in limits work across restarts.
- The worker needs outbound access to object storage; FFmpeg itself reads only local files.
- Drafts keep their uploaded audio for 30 days (Q-T7), not 24 hours; decided uploads leave quarantine as soon as they are checked.
- Logs are plain text lines without request IDs, not JSON. This does not affect privacy; revisit if logs are ever shipped to another service.
