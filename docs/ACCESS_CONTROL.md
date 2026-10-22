# Access Control

Status: **Accepted; the researcher catalogue rule is built (M6).** Two layers, both enforced on the server:

1. **Role permissions** — what *actions* a user may perform.
2. **Data-level filtering** — which *items* a user may see, based on effective consent, restriction flags, status, and ownership.

The SPA hides buttons for convenience only; it never decides access.

## 1. Roles

| Role | Granted by | Notes |
|------|-----------|-------|
| `contributor` | Admin (invitation) | Default for everyone who submits. |
| `facilitator` | Admin | Can create speaker profiles and capture consent for others. Requires training. |
| `reviewer` | Admin | May also be a contributor; never reviews own submissions. |
| `reviewer` + scope `culturally_restricted` | Admin on steward's instruction | Designated community reviewers for restricted content. |
| `researcher` | Admin on steward's approval | Read approved data; request exports. |
| `admin` | Another admin; at least two admins at all times | All operational actions; every action audited. |

Roles are additive. Role grants/revocations are audit-logged.

## 2. Permission matrix

✅ allowed · 🟡 own/assigned only · ❌ denied

| Action | Contributor | Facilitator | Reviewer | Researcher | Admin |
|--------|:-----------:|:-----------:|:--------:|:----------:|:-----:|
| Create submission for self | ✅ | ✅ | ✅ | ❌ | ✅ |
| Create speaker profile for others | ❌ | ✅ | ❌ | ❌ | ✅ |
| View speaker identity details | ❌ | 🟡 (created by them) | ❌ | ❌ | ✅ (audited) |
| Capture consent | 🟡 (self) | ✅ | ❌ | ❌ | ✅ |
| View own submissions | ✅ | ✅ | ✅ | — | ✅ |
| Edit own draft | ✅ | ✅ | ✅ | — | ✅ |
| Add revision to own submission (before approval) | ✅ | ✅ | ✅ | ❌ | ✅ |
| See review queue (unused, ADR-021) | ❌ | ❌ | ✅ (excl. own) | ❌ | ✅ |
| Approve / reject (unused, ADR-021) | ❌ | ❌ | ✅ (excl. own) | ❌ | ✅ |
| Report an item they can see | ✅ | ✅ | ✅ | ✅ | ✅ |
| Hide / show / dismiss reports | ❌ | ❌ | ❌ | ❌ | ✅ (excl. own) |
| Add reviewer revision | ❌ | ❌ | ✅ | ❌ | ✅ |
| Play playback rendition | 🟡 own | 🟡 own + created | ✅ in queue/restricted per scope | ✅ approved + consent allows research | ✅ |
| Download listening copy (one, or all as a zip; ADR-026) | 🟡 sent by them, not hidden | 🟡 sent by them, not hidden | 🟡 sent by them, not hidden | ❌ | 🟡 sent by them, not hidden |
| Download original audio | ❌ | ❌ | ❌ | ❌ | ✅ (audited, reason required) |
| Browse the catalogue (accepted, research consent, not hidden) | ❌ | ❌ | ❌ | ✅ | ✅ |
| Create draft dataset release | ❌ | ❌ | ❌ | ✅ | ✅ |
| Freeze release | ❌ | ❌ | ❌ | ❌ | ✅ |
| Request export | ❌ | ❌ | ❌ | ✅ | ✅ |
| Approve export | ❌ | ❌ | ❌ | ❌ | ✅ |
| Manage users/roles, consent forms | ❌ | ❌ | ❌ | ❌ | ✅ |
| Process withdrawal | ❌ | ❌ | ❌ | ❌ | ✅ |
| View audit log | ❌ | ❌ | ❌ | ❌ | ✅ |

## 3. Data-level rule

Contributors and facilitators see what they sent or what was recorded of speakers they registered; admins see everything (`visible_to` in `app/modules/submissions/service.py`). Researchers and admins also read what the catalogue lists for them, and only read it (`get_visible`). The catalogue rule lives in `app/modules/consents/access.py`:

```python
HIDING_FLAGS = {"sensitive", "third_party_voice", "contains_pii", "minor"}

def in_catalogue(viewer, item) -> bool:
    if not (viewer.is_admin or viewer.is_researcher):
        return False
    if item.status != "accepted" or item.speaker_withdrawn or item.consent_withdrawn:
        return False
    if HIDING_FLAGS & set(item.restriction_flags):
        return False  # hidden after a report, for everyone, admins included
    if "culturally_restricted" in item.restriction_flags and not (
        viewer.is_admin or "culturally_restricted" in viewer.scopes
    ):
        return False
    return research_allowed(item.consent)
```

`research_allowed` starts from the consent record the item was sent under and walks every later record of the speaker: a later record can only narrow research use, unless it says it applies to past contributions (CONSENT_AND_DATA_GOVERNANCE §3.3). Accepted is the only listed status: there is no reviewer, so nothing is ever "approved" (ADR-021).

The same rule is the SQL condition `catalogue_filter`, used by every catalogue search, and both are tested against one shared table of cases (`backend/tests/test_effective_access.py`).

Who may be given the `culturally_restricted` scope, and which content it covers, waits on Q-G3. Until then no one holds it, so culturally restricted items are listed for admins only.

## 4. Technical controls

| Control | Design |
|---------|--------|
| Authentication | Argon2id password hashes; opaque session token (256-bit random) stored hashed; cookie `HttpOnly; Secure; SameSite=Lax; Path=/`; idle timeout 7 days for contributors, 12 hours for reviewers/admins (initial values). |
| CSRF | Double-submit token header on all non-GET requests. |
| Brute force | Failed sign-ins counted per account (5) and per client network (20, higher because facilitators may share one connection) within 15 minutes; reaching a limit locks sign-in for 15 minutes (`429` + `Retry-After`). Values are settings. An admin unlock action is not built yet; the lock expires on its own. |
| Object access | Short-lived signed URLs (≤ 10 min) for playback renditions only (also as attachments for the owner's download, ADR-026); originals via admin endpoint that streams after audit write. |
| Database roles | `app_rw` (normal), `app_erasure` (withdrawal routine only, may delete in append-only tables), `app_readonly` (reporting), `app_backup` (nightly backup: reads everything, writes only `backup_runs`; migration `0015`). Migrations run under a separate owner role. |
| Storage credentials | Separate keys per bucket class; `consent-evidence` key only available to the API, not the worker. |
| Least privilege for staff | At least two admins; admin actions audited; quarterly access review. |
| Access logging | `audit_events` for sign-in, role changes, restricted data access, originals download, exports, withdrawals. |
| MFA | Required for admins outside development (`LKD_REQUIRE_ADMIN_MFA`; ADR-025, built in M8). After the password, an admin enters a 6-digit code from an authenticator app, or one of ten one-time recovery codes. Until an admin has set it up, they have every role except admin. A lost phone is reset with a server command, which signs the user out everywhere. Other roles may turn it on for themselves. |
