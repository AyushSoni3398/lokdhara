# API Specification (v1, proposed)

Status: **Proposed contract.** FastAPI will generate the authoritative OpenAPI document from code in Milestone 1+; this file defines intent, and the generated spec must match it. Changes to endpoints update this file in the same pull request.

## 1. Conventions

| Topic | Rule |
|-------|------|
| Base path | `/api/v1` |
| Format | JSON (`application/json`); uploads `multipart/form-data` |
| Auth | Session cookie `lkd_session`; CSRF header `X-CSRF-Token` on non-GET |
| IDs | UUIDv7 strings |
| Time | ISO 8601 UTC (`2026-10-11T20:44:29Z`) |
| Pagination | Cursor-based: `?limit=50&cursor=…` → `{ "items": [...], "next_cursor": "…" | null }` |
| Idempotency | `Idempotency-Key` header (UUID) on POST creating resources or uploading; replay returns the original response for 24 h |
| Concurrency | Text revisions require `base_revision_id`; mismatch → `409` |
| Errors | RFC 9457 Problem Details: `{"type": "https://lokdhara.example/errors/consent_required", "title": "...", "status": 422, "code": "consent_required", "detail": "...", "errors": [{"field": "...", "code": "..."}]}`. The SPA translates `code`. |
| Rate limits | `429` with `Retry-After` |
| Versioning | Breaking changes → `/api/v2`; additive changes allowed in v1 |

Auth column: role(s) required. 🔒 = also audit-logged.

## 2. Authentication and accounts

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/auth/login` | public (rate-limited) | `{username, password}` → sets session cookie; returns `{user, roles, csrf_token}` |
| POST | `/auth/logout` | any | Revokes current session |
| GET | `/auth/me` | any | Current user, roles, locale |
| POST | `/auth/invitations` | admin 🔒 | `{role, expires_in_hours}` → `{invite_url}` (token shown once) |
| POST | `/auth/invitations/accept` | public 🔒 | `{token, username, display_name, password, locale}` |
| POST | `/auth/password-reset` | public 🔒 | `{token, password}`; signs the user out of all sessions |
| POST | `/admin/users/{id}/password-reset` | admin 🔒 | Returns one-time `{reset_url, expires_at}` |
| POST | `/admin/users/{id}/roles` | admin 🔒 | Grant role |
| DELETE | `/admin/users/{id}/roles/{role}` | admin 🔒 | Revoke role |
| POST | `/admin/users/{id}/sessions/revoke` | admin 🔒 | Revoke all sessions |

Invitation and reset tokens travel in the URL **fragment** (`/invite#<token>`, `/reset-password#<token>`), which browsers never send to servers, and then in the request body. They never appear in URL paths or query strings, so they cannot leak into access logs.

Implemented in Milestone 2. Error codes: `invalid_credentials` (401, same response for unknown user, wrong password, and suspended account), `login_locked` (429 with `Retry-After`), `not_authenticated` (401), `csrf_failed` (403), `forbidden` (403), `invitation_invalid` / `reset_invalid` (404, same answer for unknown, used, revoked, and expired), `username_taken` (409), `weak_password` (422), `role_already_granted` / `last_admin` (409).

## 3. Speakers and consent

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/speakers` | contributor (self) / facilitator | Create speaker; returns `speaker_code` |
| GET | `/speakers?mine=true` | contributor/facilitator | Speakers created by me |
| GET | `/speakers/{id}` | owner/facilitator/admin | Pseudonymous profile |
| PUT | `/speakers/{id}/identity` | facilitator (creator)/admin 🔒 | Set restricted identity details |
| GET | `/speakers/{id}/identity` | facilitator (creator)/admin 🔒 | Read restricted identity |
| GET | `/consent-forms/current?language=hi` | any | Current form text + version |
| POST | `/speakers/{id}/consents` | facilitator/self 🔒 | Create consent record (multipart if `oral_recorded` evidence) |
| GET | `/speakers/{id}/consents` | owner/facilitator/admin | History |
| POST | `/withdrawal-requests` | any (self) / facilitator / admin 🔒 | Log request |
| GET | `/admin/withdrawal-requests` | admin | Queue |
| POST | `/admin/withdrawal-requests/{id}/verify` · `/complete` | admin 🔒 | Process |

Consent create body (example):

```json
{
  "consent_form_id": "…",
  "method": "in_app",
  "guardian_involved": false,
  "allow_store_and_review": true,
  "allow_research": true,
  "allow_public_access": false,
  "allow_ai_training": false,
  "allow_commercial_use": false,
  "attribution_preference": "pseudonymous",
  "demographics_consented": true,
  "applies_to_past_contributions": false
}
```

## 4. Submissions

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/submissions` | contributor | Create draft. Body: `client_submission_id, speaker_id, kind, content_type, language_tag, dialect_label?, region_coarse?, recorded_on?, collection_method, recording_mode?, prompt_id?, collection_context` |
| GET | `/submissions?mine=true&status=…` | contributor | My submissions |
| GET | `/submissions/{id}` | per access rules | Detail incl. layers, current revisions, quality flags, status |
| PATCH | `/submissions/{id}` | owner, draft/changes_requested only | Edit metadata |
| POST | `/submissions/{id}/recordings` | owner | Multipart `file`; `Idempotency-Key`; → `202 {recording_id, upload_status: "quarantined"}` |
| POST | `/submissions/{id}/text-layers` | owner / reviewer | Create layer + first revision: `{layer_type, recording_id?, source_layer_id?, entry_type?, language_tag, script_code, content}` |
| POST | `/submissions/{id}/submit` | owner | Draft → processing; checks consent and required parts |
| POST | `/submissions/{id}/withdraw` | owner/admin 🔒 | Withdraw a single submission |

## 4a. Prompts

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/prompts/next?type=image|situation|read_sentence&script=Deva&exclude=…` | contributor | One approved prompt (random, balanced by topic), skipping ones already shown |
| GET | `/prompts/{id}` | contributor | Prompt text, image/audio signed URLs |
| GET | `/admin/prompts?status=` | reviewer/admin | Prompt library |
| POST | `/admin/prompts` | reviewer/admin 🔒 | Create draft prompt (multipart for image/audio) |
| POST | `/admin/prompts/{id}/approve` · `/retire` | admin 🔒 | Status change |
| POST | `/admin/prompts/{id}/versions` | reviewer/admin 🔒 | Edit = new version |

## 5. Recordings and playback

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/recordings/{id}` | per access rules | Technical metadata, quality metrics/flags, rendition list |
| GET | `/recordings/{id}/playback` | per access rules (🔒 if restricted) | `{url, expires_at, mime_type}` signed URL for playback rendition |
| GET | `/recordings/{id}/waveform` | per access rules | Peaks JSON |
| GET | `/admin/recordings/{id}/original?reason=…` | admin 🔒 | Streams original; reason required |

## 6. Text layers and revisions

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/text-layers/{id}` | per access rules | Layer + current revision |
| GET | `/text-layers/{id}/revisions` | per access rules | Full history |
| POST | `/text-layers/{id}/revisions` | owner (pre-approval) / reviewer | `{base_revision_id, content, change_note?}` → `201` or `409 revision_conflict` |
| GET | `/text-revisions/{a}/diff/{b}` | per access rules | Character-level diff |

## 7. Review

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/review/queue?content_type=&dialect=&cursor=` | reviewer | Awaiting review, excluding own |
| POST | `/submissions/{id}/review-events` | reviewer (not own) 🔒 | `{action, reason_code?, restriction?, text_revision_id?, note?}` |
| GET | `/submissions/{id}/review-events` | reviewer/admin | History |

Allowed `action` values match `review_events.action` in [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md). Invalid state transitions → `409 invalid_transition`.

## 8. Research access and datasets

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/catalog/items?q=&script=&dialect=&content_type=&has_translation=&min_duration_ms=&cursor=` | researcher/reviewer/admin | Search approved, accessible items |
| POST | `/datasets` | researcher/admin | Draft release `{slug, purpose, selection_criteria}` |
| POST | `/datasets/{id}/preview` | researcher/admin | Counts + sample, consent-filtered |
| PUT | `/datasets/{id}/data-card` | researcher/admin | Markdown data card |
| POST | `/datasets/{id}/freeze` | admin 🔒 | Runs pre-freeze checks D1–D9; `version` required |
| POST | `/datasets/{id}/retract` | admin 🔒 | With note |
| POST | `/datasets/{id}/exports` | researcher/admin 🔒 | `{purpose_statement}` |
| POST | `/admin/exports/{id}/approve` | admin 🔒 | |
| GET | `/exports/{id}` | requester/admin | Status; when ready `{download_url, expires_at, sha256}` (🔒 on fetch) |

## 9. Administration and operations

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| GET | `/admin/jobs?status=failed` | admin | Processing runs / queue state |
| POST | `/admin/jobs/{id}/retry` | admin 🔒 | Re-queue |
| GET | `/admin/audit-events?target_type=&target_id=&actor=` | admin | Audit log |
| POST | `/admin/consent-forms` | admin 🔒 | New form version |
| GET | `/healthz` | public | Liveness |
| GET | `/readyz` | internal | DB + storage reachable |

## 10. Status codes used

`200, 201, 202` (upload accepted for processing), `204, 400` (malformed), `401` (no session), `403` (role/data access), `404` (also used instead of 403 where existence itself is sensitive), `409` (conflict/transition), `413` (too large), `415` (unsupported format), `422` (validation), `429, 500, 503`.
