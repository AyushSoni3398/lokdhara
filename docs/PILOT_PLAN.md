# Pilot plan

Status: **Draft for the professor's review.** The pilot collects the first real Mundari
recordings. It starts only with the supervising professor's (and, if required, the
institution's) **written approval** (ROADMAP M8).

## 1. Goal and size

Check, with a small group, that people can contribute comfortably, that consent is captured
correctly, and that the recordings are usable, before inviting more people.

| | Proposed |
|---|---|
| Length | 4 weeks of collection, then 1 week of review |
| People | 2–3 trained facilitators, 3–5 contributors with their own accounts, 15–25 speakers (adults only) |
| Places | 1–2 villages or neighbourhoods chosen with the professor |
| Volume | About 10–20 hours of audio and a few hundred text entries, far below what the server is sized for (~200 h, [LOAD_TESTING.md](LOAD_TESTING.md)) |
| Releases | None outside the project during the pilot; internal research exports only with the steward's approval |

## 2. What must be true before day 1

| # | Gate | Owner | Where it is tracked |
|---|------|-------|---------------------|
| 1 | Data steward and ownership decided (Q-L1, Q-L2) | Professor, institution | ASSUMPTIONS_AND_OPEN_QUESTIONS.md |
| 2 | Ethics approval, or a written statement that none is needed (Q-L3) | Owner | Done 2026-10-29: none needed (ADR-032) |
| 3 | DPDP position confirmed (Q-L8); minors take part without a guardian (Q-L4, ADR-032) | Legal adviser | same |
| 4 | What is kept after a withdrawal (Q-G8) | Owner | Done 2026-10-29: proof of consent for one month (ADR-032) |
| 5 | Final consent form approved, translated into Mundari/Hindi and loaded into the app | Professor, Claude + owner | app admin |
| 6 | Hosting chosen (Q-L7, Q-P5) and the server set up per [RUNBOOK](ops/RUNBOOK.md) | Owner | RUNBOOK §2 |
| 7 | Server checks in [SECURITY_REVIEW.md](ops/SECURITY_REVIEW.md) §4 pass, including a restore drill on the server | Owner | restore-drills.md |
| 8 | Both admins have two-step sign-in; incident contacts filled in (RUNBOOK §8) | Admins | app, RUNBOOK |
| 9 | Hindi wording of the app checked by a Hindi speaker | Owner | — |
| 10 | Facilitators trained ([FACILITATOR_GUIDE.md](ops/FACILITATOR_GUIDE.md)) | Professor, owner | training record (offline) |
| 11 | Written approval to start | Professor | — |

## 3. Weekly rhythm

- **Week 0:** facilitator training; each facilitator makes test recordings on a test account,
  which are then deleted.
- **Weeks 1–4:** collection. Each facilitator plans their own visits.
- **Every week:** a 30-minute check-in with the professor. An admin reviews the status page
  and the daily digest, the recordings rejected by the automatic checks and why, any reports or
  withdrawal requests, and the questions facilitators bring.
- **Every day (automatic):** backups and the digest email; an admin reads the digest.
- **Week 5:** review (§5) and a written summary for the professor.

## 4. What we measure

All from the app's own data or from facilitators' notes. No extra personal data is collected.

| Question | Measure |
|----------|---------|
| Does uploading work in the field? | Share of drafts sent within a day; recordings stuck or lost |
| Are recordings usable? | Share rejected by the automatic checks, and why (too short, too quiet, damaged) |
| Is consent captured correctly? | Every recording has consent; consent errors found at the weekly check |
| Is the app understandable? | Facilitators' and contributors' notes on confusing screens or words |
| How heavy is the work? | Average time per speaker visit (facilitators' notes) |
| Do withdrawals work? | Each request finished within the agreed time, with no data left behind |

## 5. Stop rules

Collection pauses, and the project lead is told the same day, if any of these happen:

- a recording was made without valid consent, or from someone under 18;
- personal data appears in a log, a release or anywhere public;
- a backup fails twice in a row, or the restore check fails;
- a speaker or community member raises a concern the team cannot answer.

The incident steps are in [PRIVACY_AND_SECURITY.md](PRIVACY_AND_SECURITY.md) §8.

## 6. After the pilot

The review decides, with the professor, whether to widen collection, what to change first in
the app and the facilitator guide, and whether the open governance questions (licences Q-L5,
public releases Q-G1, community advisers Q-G3) are ready for the next stage.
