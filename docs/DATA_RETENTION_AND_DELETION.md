# Data Retention and Deletion

Status: **Proposed.** Retention periods are placeholders until the data steward and institution approve them (Q-L1, Q-L3). The withdrawal process (§2–3) is **built** (M7 part 2, [ADR-022](ARCHITECTURE_DECISIONS.md#adr-022--withdrawals-deletion-right-after-acceptance-patch-releases-from-the-replaced-release)); see *As built* below.

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

### As built (M7 part 2)

- **Receive:** a contributor asks from an item's page (one item) or from *Take recordings back* (everything of a speaker they act for). An admin logs requests that came by phone, in person, by email or through a facilitator on *Withdrawal requests*. One waiting request per speaker, item and scope.
- **Verify and restrict:** the admin writes how the requester was checked and accepts. In the same step the speaker (for *everything*), their active consent and the submissions become `withdrawn`, and release items are marked (step 4). Or the admin refuses with a reason.
- **Delete:** accepting queues the `withdrawal.erase` job at once (no 30-day wait). It deletes the files and every stored version, empties the text, the title and context, report notes and, for *everything*, the identity details, demographics and consent notes. `erased_at` and `actions_taken` record what was deleted.
- **Close:** once `erased_at` is set, the admin closes the request with how the person was told. The contributor sees each request's state in plain words.
- **Kept:** the request and the consent records. The oral consent recording is kept for one month (`LKD_WITHDRAWAL_CONSENT_EVIDENCE_DAYS=30`, Q-G8), then the daily `withdrawal.expire_consent_evidence` job deletes it. Release manifests stay; the `items.jsonl` and `metadata.csv` of releases with withdrawn items are deleted because they hold their text.
- **Not built yet:** notifying export holders (step 5, waits for Q-G5), the 2-working-day target, legal holds (§5), account deletion (§4).

## 3. Restriction without deletion

Some requests are to narrow, not delete (e.g., "no public use, research is fine"). This creates a new consent record (narrowing), recomputes effective access, and triggers the release steps in §2.4–2.5 only for affected purposes. *As built:* the admin (or the contributor, on the consent page) records the new answers; any new consent record marks frozen releases whose purpose it no longer allows. A logged *fewer uses* request can only be accepted after that new record exists, and deletes nothing.

## 4. Deleting a whole account

- Contributor account deletion deactivates the account, removes contact details, and asks whether their *speaker* contributions should be withdrawn too (separate decision).
- Submissions created by a facilitator for other speakers are **not** deleted when the facilitator account is closed; they belong to the speakers.

## 5. Legal holds

If the institution places a hold (e.g., during an ethics investigation), the admin records it and pauses deletions for the affected scope; restriction still applies immediately.
