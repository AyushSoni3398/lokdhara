"""Speaker codes (ADR-034): SPK_<random>_<gender letter>, e.g. SPK_7Q3M9A_F.

Pure functions, so the export package can use them without a database.
"""

import secrets

# No 0/O, 1/I/L, or U, so codes survive being read aloud or written by hand.
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTVWXYZ"
_CODE_LENGTH = 6


# The letter that ends a speaker code (ADR-034). X: not given, or not agreed to share.
GENDER_LETTERS = {"female": "F", "male": "M", "other": "O"}


def new_speaker_code() -> str:
    """A fresh code for a speaker who has not given a gender yet, e.g. SPK_7Q3M9A_X."""
    return f"SPK_{''.join(secrets.choice(_CODE_ALPHABET) for _ in range(_CODE_LENGTH))}_X"


def code_with_letter(code: str, letter: str) -> str:
    """The same code with another gender letter; the random part never changes."""
    return f"{code[:-1]}{letter}"


def hide_gender(code: str) -> str:
    """A speaker or recording code with its gender letter shown as X, for packages that may
    not carry the speaker's gender (ADR-029): SPK_7Q3M9A_F_S012_read → SPK_7Q3M9A_X_S012_read."""
    parts = code.split("_")
    if len(parts) >= 3 and parts[0] == "SPK":
        parts[2] = "X"
    return "_".join(parts)
