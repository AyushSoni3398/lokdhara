# Privacy and Security

Status: **Proposed.** This is an engineering design, not a certification. A security review is part of Milestone 8 before any real data is collected.

## 1. What we protect and from whom

| Asset | Why it matters |
|-------|----------------|
| Voice recordings | Biometric-like, identifiable; may contain sensitive content |
| Speaker identity and contact details | Direct identifiers |
| Consent records and evidence | Legal/ethical proof; contains personal data |
| Text content | May include personal or culturally restricted information |
| Accounts and sessions | Gateway to everything above |
| Dataset releases | Bulk copies of data; hardest to recall |

| Threat | Examples |
|--------|----------|
| Accidental disclosure | Committing data to Git; public bucket; logs containing text; wrong release filter |
| External attacker | Credential stuffing, malicious uploads (parser exploits), XSS, SSRF, injection |
| Insider misuse | Researcher exporting beyond purpose; admin browsing identities |
| Loss | Disk failure, deleted bucket, ransomware |
| Misuse downstream | Voice cloning or surveillance using released audio |

## 2. Privacy by design

| Principle | Implementation |
|-----------|----------------|
| Minimisation | Only fields in [DATA_DICTIONARY.md](DATA_DICTIONARY.md); demographics optional and consented; no GPS, no photos, no device IDs. |
| Separation | Speaker identities in a separate, encrypted, admin-only table; consent evidence in a separate bucket with separate credentials. |
| Pseudonymisation | Speaker codes; object keys contain only UUIDs; exports use speaker codes only. |
| Purpose limitation | Release `purpose` gates on consent flags (ADR-012). |
| Transparency | Contributors see their submissions and their consent choices at any time. |
| Control | Withdrawal and narrowing workflows. |

## 3. Storage layout and protection

| Bucket / prefix | Contents | Access | Protection |
|-----------------|----------|--------|------------|
| `quarantine/` | Unvalidated uploads | API write, worker read/delete | Deleted once checked; draft audio after 30 days (Q-T7); 45-day lifecycle rule as a backstop; never served to users |
| `originals/` | Validated originals | Worker write-once; admin download | Versioning on; object lock where supported; no public access |
| `derived/` | Renditions | Worker write; signed-URL read | No public access |
| `consent-evidence/` | Oral consent audio | API only | Separate credentials; no public access |
| `exports/` | Export packages | Worker write; signed-URL read for requester | Auto-expire 7 days |
| Backup bucket | DB dumps (encrypted) | Backup job write-only key; restore key held offline by two admins | Separate account/project where possible |

Encryption: TLS in transit everywhere; provider server-side encryption at rest; DB dumps encrypted client-side (e.g., `age`) before upload; application-level encryption for `speaker_identities` columns with key from environment/secret store.

## 4. Upload security

1. Size limit at proxy and streaming counter in API.
2. Magic-byte allow-list; extension/MIME ignored.
3. Files stored under server-generated keys; client filename never used in paths.
4. Full decode in an isolated worker (non-root, no added privileges, CPU/memory/process and time limits, `-protocol_whitelist file`). The worker reaches only the database and object storage.
5. Never served from the application origin with a sniffable content type; playback via signed URLs with explicit `Content-Type` and `Content-Disposition: attachment` for downloads; `X-Content-Type-Options: nosniff`.
6. Rate limits per user (uploads need an account; sign-in is also limited per IP); idempotency keys to stop duplicate retries from multiplying storage.

## 5. Application security baseline

| Area | Control |
|------|--------|
| Injection | SQLAlchemy parameterised queries only; no string-built SQL. |
| XSS | React escaping; no `dangerouslySetInnerHTML`; strict Content-Security-Policy (`default-src 'self'`; media from storage origin only). |
| CSRF | SameSite cookies + CSRF token header. |
| SSRF | No user-supplied URLs fetched by the server in MVP. |
| Dependencies | Lockfiles (uv, npm); Dependabot alerts; `pip-audit`/`npm audit` in CI (non-blocking at first, triaged weekly). |
| Secrets | Environment variables from the host's secret store; `.env` never committed; gitleaks (or GitHub secret scanning) in CI. |
| Headers | HSTS, CSP, `Referrer-Policy: no-referrer`, `Permissions-Policy` allowing only `microphone` (site-wide: the app is a single page). |
| Errors | Problem+JSON with codes; no stack traces or SQL in responses. |
| Logging | No audio, text content, names, contacts, tokens, or raw IPs in logs; a redacting filter masks addresses, emails and secret values; query values hidden from database errors. IPs stored only as a keyed hash. |

## 6. Repository safety (the most likely accident)

- `.gitignore` blocks audio formats, data/storage/export directories, env files, keys, DB dumps.
- CI job fails if any file with an audio extension or under a forbidden path is committed.
- Secret scanning in CI.
- Test fixtures are synthetic (sine waves, silence, generated text) and generated at test time.
- **If sensitive data is ever committed:** do not just delete it in a new commit. Stop, tell the project lead, treat it as an incident (§8), and plan history rewriting with the repository owner (requires explicit approval; force-push is otherwise prohibited).

## 7. Downstream misuse (voice cloning, surveillance)

Released audio can be used to clone voices. Mitigations: AI-training and public uses are separate consent questions; consent explanation mentions this risk in plain language; external releases require data-use agreements prohibiting re-identification and voice cloning of individuals; public audio releases require governance approval (Q-G1).

## 8. Incident handling

1. **Contain** — revoke sessions/keys, make buckets private, take affected service offline if needed.
2. **Assess** — what data, how many speakers, since when (audit log).
3. **Notify** — project lead and data steward immediately; institution and legal adviser decide on notifying affected speakers and any authority (the DPDP framework includes breach-notification obligations; legal adviser to confirm).
4. **Recover** — rotate credentials, patch, restore from backup if needed.
5. **Learn** — written post-incident review in `docs/incidents/` (no personal data in the write-up).

## 9. Security review checklist before pilot (Milestone 8)

Results and findings: [ops/SECURITY_REVIEW.md](ops/SECURITY_REVIEW.md) (2026-10-18).

- [x] Threat model reviewed against implemented code.
- [x] Permission tests cover the full matrix in [ACCESS_CONTROL.md](ACCESS_CONTROL.md).
- [x] Upload fuzzing with malformed files.
- [x] Dependency audit clean or triaged.
- [ ] Buckets verified non-public from outside (on the real server).
- [ ] Backup restore drill completed, including withdrawal re-application (rehearsed on a test copy; repeat on the server).
- [ ] Admin MFA enabled (built and required; each admin sets it up on the server).
- [ ] Incident contacts documented (template in [ops/RUNBOOK.md](ops/RUNBOOK.md) §8; names needed).
