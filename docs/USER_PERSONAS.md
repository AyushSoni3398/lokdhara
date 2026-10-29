# User Personas

Status: **Draft** · These personas are *assumptions* built from the project brief, not from user research. They must be checked with community members and the supervising professor during the pilot (see Q-P1 in [ASSUMPTIONS_AND_OPEN_QUESTIONS.md](ASSUMPTIONS_AND_OPEN_QUESTIONS.md)).

## Why personas matter here

Lokdhara's hardest design constraint is that the people with the most valuable knowledge (older native speakers in villages) are often the least likely to use a web app on their own. The personas below make that explicit so the design does not quietly optimise for the technical team.

---

## P1 — Community contributor / native speaker

**Example:** *Sukhram*, 58, farmer near Khunti. Native Mundari speaker; speaks Hindi; reads Devanagari slowly; does not write Mundari regularly. Shares a basic Android phone with family. Mobile data is intermittent.

- **Goals:** Have stories and words from his village recorded properly; know how they will be used; be credited (or not) as he chooses.
- **Frustrations:** Long forms, English-only screens, passwords, being asked to type.
- **Needs from Lokdhara:** Someone to help him record; a consent explanation spoken in Mundari or Hindi; the ability to change his mind later.
- **Design implication:** Most P1 contributions will be captured **through a facilitator (P2)**. Self-service flows must still be simple (few steps, large buttons, icons with text), but the MVP must not depend on P1 using the app alone.

## P1b — Younger self-service contributor

**Example:** *Anita*, 21, college student in Ranchi, bilingual Mundari–Hindi, comfortable with smartphones and WhatsApp, can type Mundari in Devanagari or Latin script.

- **Goals:** Contribute words, sentences, and translations; record family members (which makes her a facilitator for those recordings).
- **Needs:** Fast text entry, ability to add Hindi/English translations, clear status of her submissions.
- **Design implication:** Text-entry and translation flows should be efficient; each speaker gives their own consent. Since 2026-10-29 the app records only the account holder's own voice; recording others for them is open question Q-G12.

## P2 — Facilitator / field collector

**Example:** *Birsa*, 30, community organiser or research assistant who visits villages with a phone and an external microphone.

- **Goals:** Record several speakers per visit, capture consent correctly, upload later when on Wi-Fi.
- **Frustrations:** Losing recordings to failed uploads; re-entering the same speaker details.
- **Needs:** Create pseudonymous speaker profiles, capture consent (including oral consent recordings), queue several drafts offline-ish, bulk upload later.
- **Design implication:** Speaker records and consent are first-class objects separate from user accounts. Drafts must survive network loss. Facilitators carry extra responsibility and need training (see [CONSENT_AND_DATA_GOVERNANCE.md](CONSENT_AND_DATA_GOVERNANCE.md)).

## P3 — Reviewer / moderator

**Example:** *Dr. Purty*, Mundari-literate teacher or linguistics postgraduate, reviews in the evenings on a laptop.

- **Goals:** Check that transcriptions match audio, fix spelling inconsistencies without destroying the original, flag sensitive or off-topic content.
- **Needs:** A queue, keyboard-friendly playback, side-by-side transcript/translation editing, visible revision history, clear reason codes.
- **Design implication:** Reviewer corrections are new revisions, never in-place edits. Reviewers do not need to see speaker names, only consent permissions.

## P4 — Researcher / linguist

**Example:** *Meera*, PhD student in computational linguistics, or the supervising professor.

- **Goals:** Find approved data by dialect, content type, and quality; build reproducible datasets; cite a specific dataset version in a paper.
- **Needs:** Search/filter, dataset releases with stable versions and checksums, data cards, clear statement of permitted uses.
- **Design implication:** Dataset releases are immutable and documented. Researchers never get unfiltered access to raw data or speaker identities.

## P5 — Platform administrator

**Example:** A member of the student team, later possibly institutional IT.

- **Goals:** Keep the system running, manage accounts, process withdrawals promptly, recover from failures.
- **Needs:** User/role management, consent-form versions, withdrawal queue, failed-job dashboard, audit log, backup/restore runbook.
- **Design implication:** Admin tools can be plain and functional, but every privileged action is logged.

## P6 — Community representative (governance stakeholder, not a daily user)

Village or community organisation members who may need to approve how culturally sensitive material is used. They may never log in, but their decisions shape access rules. See Q-G1/Q-G3 in [ASSUMPTIONS_AND_OPEN_QUESTIONS.md](ASSUMPTIONS_AND_OPEN_QUESTIONS.md).

## Persona-to-role mapping

| Persona | System role(s) |
|---------|----------------|
| P1, P1b | `contributor` |
| P2 | `contributor` + `facilitator` |
| P3 | `reviewer` (may also be `contributor`, but cannot approve own work) |
| P4 | `researcher` |
| P5 | `admin` |
| P6 | none in MVP (governance via admins) |
