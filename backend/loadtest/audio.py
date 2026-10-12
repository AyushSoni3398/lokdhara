"""Synthetic recordings for the load test: a plain tone in a WAV file, generated in memory.

Never real speech, and never written to disk. Sizes match 1 to 3 minute phone recordings
(about 1 MB a minute), not uncompressed studio audio.
"""

import io
import math
import wave
from array import array

RATE = 8000  # 8 kHz, 16-bit mono: 16 KB a second, close to a phone's AAC recording


def tone_wav(seconds: float, frequency: float = 440.0) -> bytes:
    """A WAV file holding `seconds` of a sine tone."""
    count = int(seconds * RATE)
    step = 2 * math.pi * frequency / RATE
    samples = array("h", (int(8000 * math.sin(step * i)) for i in range(count)))
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(RATE)
        out.writeframes(samples.tobytes())
    return buffer.getvalue()


# (seconds, weight): mostly short answers, some stories, a few long recordings.
LENGTHS = ((20, 6), (90, 3), (240, 1))


def samples() -> list[tuple[bytes, int]]:
    """One file per length with its weight, made once when the load test starts."""
    return [(tone_wav(seconds), weight) for seconds, weight in LENGTHS]
