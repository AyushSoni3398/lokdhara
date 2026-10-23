# MVP Scope

Status: **Draft for approval**

## The one-sentence MVP

> A web app, open to anyone who signs up, where facilitators and contributors submit consented Mundari audio and text, automatic checks accept it with its text labelled unverified, administrators hide anything reported, and authorised researchers build versioned, consent-filtered datasets from accepted items.

## In scope

| Area | Included in MVP | Requirement IDs |
|------|-----------------|-----------------|
| Accounts | Public sign-up for contributors, invitations for staff roles, five roles, profile asked once, admin-assisted password reset (ADR-028) | FR-A1–A5 |
| Languages of UI | Hindi and English; strings externalised for Mundari later | FR-A7, NFR-4 |
| Speakers | Pseudonymous speaker profiles; optional restricted identity details | FR-C1–C2 |
| Consent | Versioned forms, per-use permissions, three capture methods, guardian consent, withdrawal | FR-C3–C7 |
| Submissions | Audio in three recording modes (free, prompted, read) with a prompt library, text entries, transcription, Hindi/English translation, metadata, on-device drafts | FR-S1–S7, FR-S2a–b |
| Processing | Signature + decode validation, technical metadata, playback and analysis renditions, quality signals, exact-duplicate detection, text Unicode normalisation | FR-P1–P8 |
| Acceptance | Automatic acceptance after checks, unverified text labels, report button, admin hide ([ADR-021](ARCHITECTURE_DECISIONS.md#adr-021--no-human-reviewer-accept-after-automatic-checks-keep-text-unverified)) | FR-R1–R5 |
| Datasets | Search accepted items, frozen releases, export package with manifest + data card | FR-D1–D5 |
| Admin | Users/roles, consent forms, withdrawals, failed jobs, audit log | FR-X1–X2 |
| Ops | Single-server deployment, backups, restore test, basic monitoring | NFR-9 |

## Explicitly out of scope for the MVP

| Item | Why excluded | Revisit when |
|------|--------------|--------------|
| Recipes, artefacts, traditions, general heritage catalogue | Brief limits MVP to language preservation; different data model and consent questions. | After a successful language pilot. |
| ASR / automatic transcription | No validated Mundari model; risk of unverified output treated as truth; cost. | After a checked test set exists to evaluate candidates (see ADR-014). |
| Machine translation | Same as ASR. | Same. |
| Public anonymous browsing / public website of recordings | Requires community and institutional approval of public access; needs governance first. | After Q-G1/Q-L1 are resolved. |
| Native Android/iOS apps | Web app + on-device drafts covers MVP; separate codebase is too costly. | If field testing shows the browser approach fails. |
| Fully offline-first app (service-worker sync of everything) | Complexity; drafts-on-device covers the main loss case. | Milestone after pilot if needed. |
| Time-aligned segmentation UI | Valuable but large; schema reserves space. | Post-MVP milestone. |
| Lexicon / dictionary module with headwords, senses | Different data model; words are collected as text entries first. | Post-MVP. |
| Human review queue, two-reviewer consensus, peer checking | The team has no reviewers (ADR-021). | When Mundari-literate reviewers or enough active contributors are available. |
| Audio redaction tools | Complex; restrict instead. | Post-MVP. |
| SMS/WhatsApp integrations, payments, gamification | Not needed for the core goal. | — |
| Microservices, Kubernetes, message brokers | Overengineering for a small team (ADR-002, ADR-007). | Only with measured scaling need. |

## MVP is "done" when

1. All Milestone 0–8 acceptance criteria in [ROADMAP.md](ROADMAP.md) pass.
2. A pilot group (size agreed with the supervisor) has submitted, been checked automatically, and released at least one dataset end to end.
3. The blocking open questions in [ASSUMPTIONS_AND_OPEN_QUESTIONS.md](ASSUMPTIONS_AND_OPEN_QUESTIONS.md) (marked **Blocks pilot**) are answered and recorded.
