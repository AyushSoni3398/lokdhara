# Access Control

Status: **Proposed.** Two layers, both enforced on the server:

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
| See review queue | ❌ | ❌ | ✅ (excl. own) | ❌ | ✅ |
| Approve / reject / restrict | ❌ | ❌ | ✅ (excl. own) | ❌ | ✅ |
| Add reviewer revision | ❌ | ❌ | ✅ | ❌ | ✅ |
| Play playback rendition | 🟡 own | 🟡 own + created | ✅ in queue/restricted per scope | ✅ approved + consent allows research | ✅ |
| Download original audio | ❌ | ❌ | ❌ | ❌ | ✅ (audited, reason required) |
| Browse approved data | ❌ | ❌ | ✅ | ✅ | ✅ |
| Create draft dataset release | ❌ | ❌ | ❌ | ✅ | ✅ |
| Freeze release | ❌ | ❌ | ❌ | ❌ | ✅ |
| Request export | ❌ | ❌ | ❌ | ✅ | ✅ |
| Approve export | ❌ | ❌ | ❌ | ❌ | ✅ |
| Manage users/roles, consent forms | ❌ | ❌ | ❌ | ❌ | ✅ |
| Process withdrawal | ❌ | ❌ | ❌ | ❌ | ✅ |
| View audit log | ❌ | ❌ | ❌ | ❌ | ✅ |

## 3. Data-level rule (pseudo-code)

```python
def can_view(user, item) -> bool:
    if item.status == "withdrawn":
        return user.is_admin
    if user.is_admin:
        return True
    if item.submitted_by == user.id:
        return True
    if user.is_facilitator and item.speaker.created_by == user.id:
        return True
    if "culturally_restricted" in item.restriction_flags:
        return user.has_scope("culturally_restricted")
    if user.is_reviewer and item.status in REVIEWABLE_STATES:
        return True
    if user.is_researcher:
        return item.status == "approved" \
            and effective_permissions(item).research \
            and not (EXCLUDING_FLAGS & set(item.restriction_flags))
    return False
```

The same rule is implemented as a SQL predicate used by every list/search query, and both versions are tested against a shared table of cases.

## 4. Technical controls

| Control | Design |
|---------|--------|
| Authentication | Argon2id password hashes; opaque session token (256-bit random) stored hashed; cookie `HttpOnly; Secure; SameSite=Lax; Path=/`; idle timeout 7 days for contributors, 12 hours for reviewers/admins (initial values). |
| CSRF | Double-submit token header on all non-GET requests. |
| Brute force | Failed sign-ins counted per account (5) and per client network (20, higher because facilitators may share one connection) within 15 minutes; reaching a limit locks sign-in for 15 minutes (`429` + `Retry-After`). Values are settings. An admin unlock action is not built yet; the lock expires on its own. |
| Object access | Short-lived signed URLs (≤ 10 min) for playback renditions only; originals via admin endpoint that streams after audit write. |
| Database roles | `app_rw` (normal), `app_erasure` (withdrawal routine only, may delete in append-only tables), `app_readonly` (reporting). Migrations run under a separate owner role. |
| Storage credentials | Separate keys per bucket class; `consent-evidence` key only available to the API, not the worker. |
| Least privilege for staff | At least two admins; admin actions audited; quarterly access review. |
| Access logging | `audit_events` for sign-in, role changes, restricted data access, originals download, exports, withdrawals. |
| MFA | Recommended for admins (TOTP) — Milestone 8 hardening item. |
