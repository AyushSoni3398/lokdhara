# Consent and Data Governance

Status: **Proposed design, not legal advice.** Nothing in this document claims that Lokdhara is compliant with any law or ethics standard. The workflow states below are software controls that *implement* decisions made by the supervising professor, the institution's ethics committee, legal advisers, and community representatives. They are not a substitute for valid, informed consent obtained by trained people.

## 1. Governance roles (to be confirmed — Q-L1, Q-G1)

| Role | Proposed holder | Responsibilities |
|------|-----------------|------------------|
| Data steward (accountable) | Supervising professor or institution | Approves consent forms, release purposes, external access; owns withdrawal SLA. |
| Community advisory group | Representatives nominated by Mundari community organisations | Advises on culturally restricted content, public release, AI-training uses, benefit sharing. |
| Platform administrators | Named team members | Operate the system, process withdrawals, maintain audit trail. |
| Facilitators | Trained collectors | Explain consent in a language the speaker understands; capture it correctly. |
| Ethics committee (IEC) | Institution | Approves the research protocol and consent materials (Q-L3). |

## 2. Guiding frameworks (for reference, not compliance claims)

- **India's Digital Personal Data Protection Act, 2023** and **DPDP Rules, 2025** (notified 13 November 2025, with phased commencement). Voice recordings and linked metadata are likely personal data. The Act contains a research/archiving/statistical exemption (Section 17(2)(b)) whose applicability to Lokdhara must be confirmed by a legal adviser (Q-L8). The Rules require verifiable parental consent for processing children's data (Q-L4).
- **CARE Principles for Indigenous Data Governance** (Collective benefit, Authority to control, Responsibility, Ethics) — <https://www.gida-global.org/care>. Lokdhara adopts them as design values: community authority over sensitive material, benefit to the community, and responsibility for downstream use.
- **FAIR principles** (Findable, Accessible, Interoperable, Reusable) for research data — applied *within* consent limits ("as open as possible, as closed as necessary").
- Institutional ethics guidelines applicable to research with human participants (to be identified by the institution).

## 3. Consent model

### 3.1 What is asked (separately, each defaulting to **No** except the first)

| # | Permission | Field | Plain-language question (draft, to be translated and approved) |
|---|------------|-------|---------------------------------------------------------------|
| 1 | Store and review (**required to participate**) | `allow_store_and_review` | "May we keep your recording safely and let our trained reviewers listen to it and check the writing?" |
| 2 | Research use | `allow_research` | "May approved researchers study your recording for language research?" |
| 3 | Public access | `allow_public_access` | "May anyone on the internet listen to or read your recording in future?" |
| 4 | AI/technology training | `allow_ai_training` | "May your recording be used to build computer tools, such as speech recognition for Mundari?" |
| 5 | Commercial use | `allow_commercial_use` | "May companies use it in products they sell?" |
| 6 | Credit | `attribution_preference` | "Should we show your name, a code instead of your name, or no credit?" |
| 7 | Demographics | `demographics_consented` | "May we record your age group, home area, and languages you speak?" |

The consent explanation must also state: what Lokdhara is, who runs it, where data is stored, who can access it, how long it is kept, how to withdraw, and **that copies already shared with researchers cannot always be fully recalled**.

### 3.2 How consent is captured

| Method | When | Evidence stored |
|--------|------|-----------------|
| `in_app` | Literate adult using their own account | Consent record with form version hash, timestamp, account. |
| `oral_recorded` | Facilitator reads the form; speaker answers aloud | Short audio of the consent exchange in the `consent-evidence` bucket (restricted, separate credentials). |
| `paper_reference` | Institution requires signed paper forms | Only the paper form's reference ID in the system; paper stored by the institution, never scanned into the repository. |

### 3.3 Versioning and change

- Consent forms are versioned and immutable; the exact text shown is hashed.
- Any change of permissions creates a **new** consent record that supersedes the previous one.
- **Narrowing** always applies to all of the speaker's past and future contributions.
- **Widening** applies only to future contributions unless the speaker explicitly agrees that it applies to past ones (`applies_to_past_contributions`).
- Effective permission for an item = permissions in force when it was submitted, narrowed by every later record (and widened only by records with `applies_to_past_contributions = true`).

### 3.4 Minors

Until Q-L4 is answered: **no recordings from speakers under 18 are collected in the pilot.** The schema and flows still support guardian consent (`guardian_involved`, `guardian_relationship`, `minor` flag) so the policy can be enabled once approved, without redesign.

### 3.5 Recording of other people

If someone other than the consenting speaker is identifiably audible, the reviewer flags `third_party_voice`; the item is excluded from all releases until the other person consents (as a new speaker record) or the item is restricted.

## 4. Proposed permission (workflow) states for a contribution

These are **system states**, computed from consent, review status, and restriction flags:

| State | Meaning | Who can access |
|-------|---------|----------------|
| `stored_unreviewed` | Stored securely, not yet reviewed | Submitter (own), admins |
| `reviewer_restricted` | Under review, or restricted by a flag | Assigned reviewers (not own), admins; `culturally_restricted` → designated community reviewers + admins only |
| `approved_research` | Approved; consent allows research | + Researchers with internal access; eligible for research releases |
| `approved_public` | Approved; consent allows public access; public release approved by governance | + Eligible for public releases (no public browsing in MVP) |
| `approved_ai_training` | Approved; consent allows AI training; separately authorised by governance | + Eligible for AI-training releases |
| `withdrawn` | Consent withdrawn | Admins only, until deletion |

A contribution can be in more than one `approved_*` state (e.g., research + AI training). The computation lives in one function (`effective_access()`) with exhaustive tests.

## 5. Sensitive content

- **Culturally restricted content** (e.g., ritual knowledge) is defined by the community advisory group (Q-G3). Lokdhara provides the `culturally_restricted` flag and a restricted reviewer group; it does not decide what is sacred.
- Reviewers receive guidance on what to flag and are encouraged to flag when unsure.
- Restricted items are excluded from releases unless the steward and community advisory group record an explicit exception.

## 6. Data sharing outside the project

| Recipient | Requirement |
|-----------|-------------|
| Internal researchers (project members) | Role `researcher`; acknowledgement of usage rules in-app. |
| External researchers | Data-use agreement (purpose, no re-identification, no onward sharing, honour withdrawals, delete on request, cite release version); steward approval per export. |
| Public | Only through a governance-approved public release with a licence. |
| AI developers | Only `ai_training` releases with separate approval; commercial only with `allow_commercial_use`. |

## 7. Facilitator training checklist (session plan and field card: [ops/FACILITATOR_GUIDE.md](ops/FACILITATOR_GUIDE.md))

1. Explaining each permission without pressure; "No" is always fine.
2. Language: explain in Mundari or Hindi as the speaker prefers.
3. Not recording before consent (or per agreed field protocol, Q-G4).
4. Avoiding third-party voices and personal details in recordings.
5. Handling withdrawal requests received in person.
6. Device hygiene: delete local copies after successful upload; lock phone.

## 8. Decisions required from others

| Question IDs | Decision owner |
|--------------|----------------|
| Q-L1, Q-L2, Q-L3, Q-L4, Q-L8 | Professor, institution, legal adviser, ethics committee |
| Q-G1, Q-G2, Q-G3, Q-G5, Q-G6 | Professor and community representatives |
| Q-L5 (licences) | Professor, institution, community |

No real speaker data is collected until the items marked **Blocks pilot** in [ASSUMPTIONS_AND_OPEN_QUESTIONS.md](ASSUMPTIONS_AND_OPEN_QUESTIONS.md) are answered.
