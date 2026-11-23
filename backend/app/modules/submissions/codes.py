"""Readable recording codes (ADR-034): SPK_7Q3M9A_F_S012_read.

speaker code, then S and the sentence (prompt) number, then how it was recorded. Free speech
answers no sentence, so it is S000. A second take of the same sentence by the same speaker
ends _2, a third _3. The code is given when a submission is sent and changes afterwards only
when the speaker's gender letter does (app.modules.speakers.service.refresh_code).
"""

import re
from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.prompts.models import Prompt
from app.modules.speakers.models import Speaker
from app.modules.submissions.models import Recording, Submission

_TAKE = re.compile(r"_(\d+)$")


def base_code(speaker: Speaker, submission: Submission, prompt_number: int | None) -> str:
    return f"{speaker.speaker_code}_S{prompt_number or 0:03d}_{submission.recording_mode}"


def _take(code: str, base: str) -> int:
    if code == base:
        return 1
    found = _TAKE.search(code[len(base) :])
    return int(found.group(1)) if found else 1


def assign(
    db: Session, speaker: Speaker, submission: Submission, recordings: Sequence[Recording]
) -> None:
    """Gives each recording of the submission its code, numbering repeated takes."""
    if submission.recording_mode is None or not recordings:
        return
    prompt_number = None
    if submission.prompt_id is not None:
        prompt_number = db.scalar(
            select(Prompt.prompt_number).where(Prompt.id == submission.prompt_id)
        )
    base = base_code(speaker, submission, prompt_number)
    # One speaker's takes are numbered one at a time.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(str(speaker.id), 0))))
    taken = db.scalars(
        select(Recording.recording_code).where(
            (Recording.recording_code == base)
            | func.starts_with(Recording.recording_code, f"{base}_")
        )
    ).all()
    last = max((_take(code, base) for code in taken if code), default=0)
    for recording in sorted(recordings, key=lambda r: r.created_at):
        if recording.recording_code is not None and (
            recording.recording_code == base or recording.recording_code.startswith(f"{base}_")
        ):
            continue
        last += 1
        recording.recording_code = base if last == 1 else f"{base}_{last}"
    db.flush()
