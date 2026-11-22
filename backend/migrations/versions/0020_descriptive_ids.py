"""Speaker and recording IDs that say who, which sentence, and how (ADR-034).

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-22

- speakers.gender_self_described (free text) becomes speakers.gender, one of female, male,
  other, undisclosed. Earlier answers are mapped where they clearly say female or male.
- speaker_code changes from SPK-7Q3M9A to SPK_7Q3M9A_F: the random part never changes, the
  last letter is the gender (M, F, O, or X when not given or not agreed to share).
- prompts.prompt_number: one number per prompt key, shared by all its versions (S001, S002).
- recordings.recording_code: SPK_7Q3M9A_F_S012_read, given when the submission is sent.
  A second take of the same sentence ends _2, a third _3. Free speech has no sentence: S000.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEMOGRAPHICS_OLD = (
    "age_band IS NULL AND gender_self_described IS NULL AND first_language IS NULL "
    "AND other_languages IS NULL AND region_coarse IS NULL"
)
_DEMOGRAPHICS_NEW = _DEMOGRAPHICS_OLD.replace("gender_self_described", "gender")


def upgrade() -> None:
    # ---- gender as a choice
    op.execute("ALTER TABLE speakers DROP CONSTRAINT ck_speakers_demographics_need_consent")
    op.execute("ALTER TABLE speakers DROP CONSTRAINT ck_speakers_gender_length")
    op.execute("ALTER TABLE speakers RENAME COLUMN gender_self_described TO gender")
    op.execute(
        # Female and male in English and Hindi; anything else someone wrote becomes "other".
        """
        UPDATE speakers SET gender = CASE
          WHEN gender IS NULL OR btrim(gender) = '' THEN NULL
          WHEN lower(btrim(gender)) IN
               ('f', 'female', 'woman', 'w', 'महिला', 'स्त्री', 'औरत', 'लड़की') THEN 'female'
          WHEN lower(btrim(gender)) IN
               ('m', 'male', 'man', 'पुरुष', 'आदमी', 'मर्द', 'लड़का') THEN 'male'
          ELSE 'other' END
        """
    )
    op.execute(
        "ALTER TABLE speakers ADD CONSTRAINT ck_speakers_gender "
        "CHECK (gender IN ('female', 'male', 'other', 'undisclosed'))"
    )
    op.execute(
        "ALTER TABLE speakers ADD CONSTRAINT ck_speakers_demographics_need_consent "
        f"CHECK (demographics_consented OR ({_DEMOGRAPHICS_NEW}))"
    )

    # ---- speaker codes: SPK_<random>_<gender letter>
    op.execute("DROP TRIGGER speakers_frozen ON speakers")
    op.execute("ALTER TABLE speakers DROP CONSTRAINT ck_speakers_speaker_code")
    op.execute(
        """
        UPDATE speakers SET speaker_code = 'SPK_' || substr(speaker_code, 5) || '_' ||
          CASE WHEN NOT demographics_consented THEN 'X'
               WHEN gender = 'female' THEN 'F'
               WHEN gender = 'male' THEN 'M'
               WHEN gender = 'other' THEN 'O'
               ELSE 'X' END
        """
    )
    op.execute(
        "ALTER TABLE speakers ADD CONSTRAINT ck_speakers_speaker_code "
        "CHECK (speaker_code ~ '^SPK_[0-9A-Z]{5,12}_[MFOX]$')"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_speakers_code_random ON speakers (split_part(speaker_code, '_', 2))"
    )
    op.execute(
        "CREATE TRIGGER speakers_frozen BEFORE UPDATE OR DELETE ON speakers "
        "FOR EACH ROW EXECUTE FUNCTION lkd_freeze_columns('id', 'created_by')"
    )
    # Only the gender letter may change; the random part is the speaker's for good.
    op.execute(
        """
        CREATE FUNCTION lkd_speaker_code_keeps_random() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          IF split_part(OLD.speaker_code, '_', 2) IS DISTINCT FROM
             split_part(NEW.speaker_code, '_', 2) THEN
            RAISE EXCEPTION 'immutable_columns: the random part of speaker_code cannot change'
              USING ERRCODE = 'insufficient_privilege';
          END IF;
          RETURN NEW;
        END
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER speakers_code_random BEFORE UPDATE OF speaker_code ON speakers "
        "FOR EACH ROW EXECUTE FUNCTION lkd_speaker_code_keeps_random()"
    )

    # ---- sentence numbers for prompts
    op.execute("CREATE SEQUENCE prompts_prompt_number_seq")
    op.execute("ALTER TABLE prompts ADD COLUMN prompt_number integer")
    op.execute("ALTER TABLE prompts DISABLE TRIGGER prompts_guard")
    op.execute(
        """
        UPDATE prompts p SET prompt_number = n.number
        FROM (SELECT prompt_key, row_number() OVER (ORDER BY min(created_at), prompt_key) AS number
              FROM prompts GROUP BY prompt_key) n
        WHERE p.prompt_key = n.prompt_key
        """
    )
    op.execute("ALTER TABLE prompts ENABLE TRIGGER prompts_guard")
    op.execute(
        "SELECT setval('prompts_prompt_number_seq', "
        "(SELECT coalesce(max(prompt_number), 0) + 1 FROM prompts), false)"
    )
    op.execute(
        "ALTER TABLE prompts ALTER COLUMN prompt_number "
        "SET DEFAULT nextval('prompts_prompt_number_seq')"
    )
    op.execute("ALTER SEQUENCE prompts_prompt_number_seq OWNED BY prompts.prompt_number")
    op.execute("ALTER TABLE prompts ALTER COLUMN prompt_number SET NOT NULL")
    op.execute(
        "ALTER TABLE prompts ADD CONSTRAINT ck_prompts_prompt_number CHECK (prompt_number >= 1)"
    )

    # ---- recording codes for everything already sent
    op.execute("ALTER TABLE recordings ADD COLUMN recording_code text")
    op.execute(
        """
        WITH base AS (
          SELECT r.id, r.created_at,
                 sp.speaker_code || '_S' || lpad(coalesce(p.prompt_number, 0)::text, 3, '0')
                   || '_' || s.recording_mode AS code
          FROM recordings r
          JOIN submissions s ON s.id = r.submission_id
          JOIN speakers sp ON sp.id = s.speaker_id
          LEFT JOIN prompts p ON p.id = s.prompt_id
          WHERE s.status <> 'draft' AND s.recording_mode IS NOT NULL
        ), numbered AS (
          SELECT id, code, row_number() OVER (PARTITION BY code ORDER BY created_at, id) AS take
          FROM base
        )
        UPDATE recordings r
        SET recording_code = n.code || CASE WHEN n.take > 1 THEN '_' || n.take ELSE '' END
        FROM numbered n WHERE r.id = n.id
        """
    )
    op.execute(
        "ALTER TABLE recordings ADD CONSTRAINT ck_recordings_recording_code CHECK "
        "(recording_code ~ '^SPK_[0-9A-Z]{5,12}_[MFOX]_S[0-9]{3,}_(free|prompted|read)(_[0-9]+)?$')"
    )
    op.execute("CREATE UNIQUE INDEX uq_recordings_recording_code ON recordings (recording_code)")
    # recordings_frozen names the columns it freezes, so recording_code may follow the
    # speaker's gender letter without changing that trigger.


def downgrade() -> None:
    op.execute("DROP INDEX uq_recordings_recording_code")
    op.execute("ALTER TABLE recordings DROP CONSTRAINT ck_recordings_recording_code")
    op.execute("ALTER TABLE recordings DROP COLUMN recording_code")

    op.execute("ALTER TABLE prompts DROP CONSTRAINT ck_prompts_prompt_number")
    op.execute("ALTER TABLE prompts DROP COLUMN prompt_number")  # drops the owned sequence

    op.execute("DROP TRIGGER speakers_code_random ON speakers")
    op.execute("DROP FUNCTION lkd_speaker_code_keeps_random()")
    op.execute("DROP TRIGGER speakers_frozen ON speakers")
    op.execute("DROP INDEX uq_speakers_code_random")
    op.execute("ALTER TABLE speakers DROP CONSTRAINT ck_speakers_speaker_code")
    op.execute("UPDATE speakers SET speaker_code = 'SPK-' || split_part(speaker_code, '_', 2)")
    op.execute(
        "ALTER TABLE speakers ADD CONSTRAINT ck_speakers_speaker_code "
        "CHECK (speaker_code ~ '^SPK-[0-9A-Z]{5,12}$')"
    )
    op.execute(
        "CREATE TRIGGER speakers_frozen BEFORE UPDATE OR DELETE ON speakers "
        "FOR EACH ROW EXECUTE FUNCTION lkd_freeze_columns('id', 'speaker_code', 'created_by')"
    )

    op.execute("ALTER TABLE speakers DROP CONSTRAINT ck_speakers_demographics_need_consent")
    op.execute("ALTER TABLE speakers DROP CONSTRAINT ck_speakers_gender")
    op.execute("ALTER TABLE speakers RENAME COLUMN gender TO gender_self_described")
    op.execute(
        "ALTER TABLE speakers ADD CONSTRAINT ck_speakers_gender_length "
        "CHECK (char_length(gender_self_described) <= 60)"
    )
    op.execute(
        "ALTER TABLE speakers ADD CONSTRAINT ck_speakers_demographics_need_consent "
        f"CHECK (demographics_consented OR ({_DEMOGRAPHICS_OLD}))"
    )
