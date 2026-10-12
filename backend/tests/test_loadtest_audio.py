"""The load test's synthetic recordings must pass the upload's format check, or the load
test would measure refusals instead of uploads (docs/LOAD_TESTING.md)."""

import io
import wave

from app.audio_formats import SNIFF_BYTES, sniff_audio_container
from loadtest.audio import RATE, tone_wav


def test_synthetic_recordings_are_accepted_wav_files() -> None:
    data = tone_wav(2)
    assert sniff_audio_container(data[:SNIFF_BYTES]) == "wav"
    with wave.open(io.BytesIO(data)) as recording:
        assert recording.getnframes() == 2 * RATE
        assert (recording.getnchannels(), recording.getsampwidth()) == (1, 2)
