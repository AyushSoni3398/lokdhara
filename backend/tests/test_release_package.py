"""The export package (docs/DATASET_VERSIONING.md §4 and §5): allow-listed fields, a data card with
the counts and limitations, and identical bytes when built again. Synthetic data only."""

import hashlib
import io
import json
import zipfile
from datetime import date
from typing import Any

from app.modules.releases import package
from app.modules.releases.package import AudioFile, ItemSource, ReleaseInfo, TextVersion

INFO = ReleaseInfo(
    slug="mundari-speech-pilot",
    version="0.1.0",
    purpose="internal_research",
    licence=None,
    frozen_at="2026-10-15T12:00:00+00:00",
    code_version="abc1234",
    data_card_markdown="A test release made of synthetic data.",
)
FLAC = b"fLaC" + b"\x00" * 60  # not real audio
TEXT = TextVersion(
    revision_id="r1",
    layer_type="transcription",
    language="unr",
    script="Deva",
    text="यह एक परीक्षण वाक्य है।",
    origin="human_contributor",
    verification_status="unverified",
    uncertainty_markup=False,
)


def _item(item_id: str, speaker: str = "SPK-AAAAA", **fields: Any) -> ItemSource:
    values: dict[str, Any] = {
        "item_id": item_id,
        "language": "unr",
        "speaker_code": speaker,
        "age_band": None,
        "dialect_label": "Hasada",
        "content_type": "story",
        "collection_method": "self_recorded",
        "recording_mode": "free",
        "prompt": None,
        "recorded_on": date(2026, 10, 1),
        "audio": AudioFile(hashlib.sha256(FLAC).hexdigest(), len(FLAC), 4000, True),
        "texts": (
            TEXT,
            TextVersion(
                revision_id="r2",
                layer_type="translation",
                language="en",
                script="Latn",
                text="This is a test sentence.",
                origin="human_contributor",
                verification_status="unverified",
                uncertainty_markup=False,
                source_revision_id="r1",
            ),
        ),
        "quality_flags": ("very_quiet",),
        "consent": {"research": True, "public": False, "secret": True},
    }
    values.update(fields)
    return ItemSource(**values)


def test_item_records_hold_only_allow_listed_fields() -> None:
    record = package.item_record(_item("b2", age_band="45-59"))
    assert record.keys() == package.ITEM_FIELDS
    assert record["audio"].keys() == package.AUDIO_FIELDS
    assert record["transcription"].keys() == package.TEXT_FIELDS
    assert record["translations"][0].keys() == package.TRANSLATION_FIELDS
    assert record["text"] is None
    assert record["speaker"] == {"age_band": "45-59"}
    # Unknown consent keys are dropped; missing ones are false.
    assert record["consent_permissions"] == {
        "research": True,
        "public": False,
        "ai_training": False,
        "commercial": False,
    }
    assert package.item_record(_item("b3"))["speaker"] == {}


def _build(items: list[ItemSource]) -> bytes:
    records = [package.item_record(item) for item in items]
    stats = package.statistics(records, speaker_share_warning=0.6)
    audio = {
        package.audio_path(item.item_id): (
            package.FileEntry(package.audio_path(item.item_id), item.audio.sha256, len(FLAC)),
            lambda: iter((FLAC,)),
        )
        for item in items
        if item.audio
    }
    built = package.assemble(INFO, records, stats, audio)
    out = io.BytesIO()
    package.write_zip(out, "mundari-speech-pilot-0.1.0", built.files)
    return out.getvalue()


def test_the_same_release_always_gives_the_same_bytes() -> None:
    items = [_item("b2"), _item("a1", speaker="SPK-BBBBB", audio=None)]
    first = _build(items)
    assert first == _build(list(reversed(items)))

    archive = zipfile.ZipFile(io.BytesIO(first))
    names = archive.namelist()
    assert names == sorted(names)
    assert {n.split("/", 1)[1] for n in names} == {
        "LICENSE.txt",
        "README.md",
        "audio/b2.flac",
        "checksums.sha256",
        "datacard.json",
        "items.jsonl",
        "manifest.json",
    }
    assert all(info.date_time == (1980, 1, 1, 0, 0, 0) for info in archive.infolist())

    # checksums.sha256 matches every other file.
    root = "mundari-speech-pilot-0.1.0/"
    lines = archive.read(root + "checksums.sha256").decode().splitlines()
    for line in lines:
        digest, path = line.split("  ")
        assert hashlib.sha256(archive.read(root + path)).hexdigest() == digest, path
    assert len(lines) == len(names) - 1

    manifest = json.loads(archive.read(root + "manifest.json"))
    assert manifest["item_count"] == 2
    assert manifest["export_format_version"] == "1"
    assert "manifest.json" not in [f["path"] for f in manifest["files"]]
    items_lines = archive.read(root + "items.jsonl").decode().splitlines()
    assert [json.loads(line)["item_id"] for line in items_lines] == ["a1", "b2"]
    assert "Internal research use only" in archive.read(root + "LICENSE.txt").decode()


def test_the_data_card_counts_items_and_states_its_limitations() -> None:
    items = [_item("a1"), _item("b2"), _item("c3", speaker="SPK-BBBBB", content_type="song")]
    records = [package.item_record(item) for item in items]
    stats = package.statistics(records, speaker_share_warning=0.6)
    assert stats["by_content_type"] == {"song": 1, "story": 2}
    assert stats["unverified_texts"] == 6
    assert stats["speakers_above_share"] == ["SPK-AAAAA"]  # two thirds of the audio

    card = package.data_card_markdown(INFO, stats)
    assert "A test release made of synthetic data." in card
    assert "6 of 6 texts were written by contributors and **not checked by anyone**" in card
    assert "SPK-AAAAA" in card
    assert "| song | 1 |" in card
    assert json.loads(package.data_card_json(INFO, stats))["texts_verified_by_reviewer"] is False
