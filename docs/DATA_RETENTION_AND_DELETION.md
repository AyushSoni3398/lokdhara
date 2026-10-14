# Data Retention and Deletion

Status: **Proposed.** Retention periods are placeholders until the data steward and institution approve them (Q-L1, Q-L3).

## 1. Retention schedule (proposed)

| Data | Retention | Basis |
|------|-----------|-------|
| Quarantine uploads not promoted | Deleted once validation decides; a draft's upload that is never submitted after **30 days** (Q-T7, `cleanup.expire_drafts`) | Operational |
| Rejected-invalid recordings | 30 days, then deleted (metadata row kept without object) | Lets contributors contest |
| Drafts on server never submitted | 90 days, contributor reminded at 60 | Operational |
| Approved originals and derivatives | For the life of the project/archive while consent stands | Preservation purpose |
| Consent records | As long as any related data exists + period set by institution | Proof of consent |
| Consent evidence (oral/paper refs) | Same as consent records | Proof of consent |
| Speaker identity details | Until no longer needed for contact, or on withdrawal | Minimisation |
| Audit events | 3 years (proposed) | Accountability |
| Session rows | 30 days after expiry | Security |
| Export packages | 7 days after creation | Minimise copies |
| Database backups | 30 daily + 12 monthly (proposed) | Recovery |
| Application logs | 30 days | Debugging; contain no content |

## 2. Withdrawal process

1. **Receive** — via app, facilitator, phone, in person, or email; logged in `withdrawal_requests` immediately.
2. **Verify** — confirm requester is the speaker or authorised representative (method agreed with ethics committee; for facilitator-collected speakers, the facilitator or admin confirms in person or by phone).
3. **Restrict immediately** — on verification, affected submissions become invisible to everyone except admins (`withdrawn`). Target: within 2 working days of receipt (proposed SLA).
4. **Exclude from releases** — mark `withdrawn_after_release_at` on release items; block exports of affected releases; schedule PATCH releases.
5. **Notify** — holders of exports containing the items are notified per data-use agreement.
6. **Delete** — within 30 days (proposed): originals, renditions, text revisions content, speaker identity, consent evidence *unless* the institution requires keeping proof of consent and withdrawal (keep minimal record: speaker code, dates, action taken).
7. **Close** — record actions in `actions_taken`; confirm to requester.

### Deletion mechanics

- Deletion runs as the `app_erasure` database role, the only role allowed to delete from append-only tables.
- Text revision rows are retained as tombstones (IDs, timestamps, origin) with content fields cleared, so release manifests remain interpretable without the data.
- Objects are deleted from all buckets, including **all object versions** in versioned buckets.
- **Backups:** data in backups ages out with the backup retention window (max ~12 months for monthly backups). Restores must re-apply the withdrawal list before the system is reopened (the restore runbook includes this step). This limitation must be stated in the consent explanation.

## 3. Restriction without deletion

Some requests are to narrow, not delete (e.g., "no public use, research is fine"). This creates a new consent record (narrowing), recomputes effective access, and triggers the release steps in §2.4–2.5 only for affected purposes.

## 4. Deleting a whole account

- Contributor account deletion deactivates the account, removes contact details, and asks whether their *speaker* contributions should be withdrawn too (separate decision).
- Submissions created by a facilitator for other speakers are **not** deleted when the facilitator account is closed; they belong to the speakers.

## 5. Legal holds

If the institution places a hold (e.g., during an ethics investigation), the admin records it and pauses deletions for the affected scope; restriction still applies immediately.
