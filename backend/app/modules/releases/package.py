"""The export package of a frozen release (docs/DATASET_VERSIONING.md §4, §5). Pure functions:
no database, no storage. Given the same inputs they produce the same bytes, so an export can be
rebuilt and checked against the manifest frozen with the release.

Every exported field comes from an explicit allow-list here (check D6). Names, contacts, user
IDs, object keys, review notes, and collection notes are never in it.
"""

import hashlib
import json
import zipfile
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import IO, Any

EXPORT_FORMAT_VERSION = "1"
ITEM_FIELDS = frozenset(
    {
        "item_id",
        "language",
        "speaker_code",
        "speaker",
        "dialect_label",
        "content_type",
        "collection_method",
        "recording_mode",
        "prompt",
        "recorded_on",
        "audio",
        "transcription",
        "text",
        "translations",
        "quality_flags",
        "consent_permissions",
        "collection_context",
    }
)
AUDIO_FIELDS = frozenset(
    {
        "path",
        "duration_ms",
        "sample_rate_hz",
        "is_lossy_source",
        "sha256",
        "bytes",
        "original",
        "quality",
    }
)
# What the uploaded file was, as measured when it was checked (docs/DATA_DICTIONARY.md §1).
ORIGINAL_FIELDS = (
    "container",
    "codec",
    "sample_rate_hz",
    "channels",
    "bit_depth",
    "bytes",
    "source",
)
# app.audio.quality.Metrics, measured on the original.
QUALITY_FIELDS = (
    "peak_dbfs",
    "rms_dbfs",
    "integrated_lufs",
    "true_peak_dbtp",
    "clipping_ratio",
    "silence_ratio",
)
TEXT_FIELDS = frozenset(
    {
        "revision_id",
        "language",
        "script",
        "text",
        "origin",
        "verification_status",
        "uncertainty_markup",
    }
)
TRANSLATION_FIELDS = TEXT_FIELDS | {"source_revision_id"}
PROMPT_FIELDS = frozenset({"id", "key", "version", "type"})
# docs/DATA_DICTIONARY.md §3. `notes` is never exported: it may contain personal details.
COLLECTION_CONTEXT_FIELDS = ("setting", "speaker_count", "equipment")
CONSENT_FIELDS = ("research", "public", "ai_training", "commercial")
DEFAULT_LICENCE = (
    "Internal research use only, within the Lokdhara project. Do not share, publish, or use "
    "this data for training AI models. Speakers can withdraw their contributions; see README.md."
)
# Zip entries carry this fixed time so rebuilding gives identical bytes (§5).
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class AudioFile:
    sha256: str
    size_bytes: int
    duration_ms: int | None
    is_lossy_source: bool | None
    # ORIGINAL_FIELDS and QUALITY_FIELDS; missing ones are exported as null.
    original: Mapping[str, Any] = field(default_factory=dict)
    quality: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TextVersion:
    revision_id: str
    layer_type: str
    language: str
    script: str
    text: str
    origin: str
    verification_status: str
    uncertainty_markup: bool
    source_revision_id: str | None = None


@dataclass(frozen=True)
class ItemSource:
    item_id: str
    language: str
    speaker_code: str
    age_band: str | None
    dialect_label: str | None
    content_type: str
    collection_method: str
    recording_mode: str | None
    prompt: Mapping[str, Any] | None
    recorded_on: date | None
    audio: AudioFile | None
    texts: tuple[TextVersion, ...]
    quality_flags: tuple[str, ...]
    consent: Mapping[str, bool]
    collection_context: Mapping[str, Any] = field(default_factory=dict)


def audio_path(item_id: str) -> str:
    return f"audio/{item_id}.flac"


def _text(version: TextVersion, fields: frozenset[str]) -> dict[str, Any]:
    values = {
        "revision_id": version.revision_id,
        "language": version.language,
        "script": version.script,
        "text": version.text,
        "origin": version.origin,
        "verification_status": version.verification_status,
        "uncertainty_markup": version.uncertainty_markup,
        "source_revision_id": version.source_revision_id,
    }
    return {key: values[key] for key in sorted(fields)}


def item_record(item: ItemSource) -> dict[str, Any]:
    """One line of items.jsonl, built only from allow-listed fields."""
    main = {v.layer_type: v for v in item.texts if v.layer_type != "translation"}
    translations = sorted(
        (v for v in item.texts if v.layer_type == "translation"),
        key=lambda v: (v.language, v.revision_id),
    )
    audio = None
    if item.audio is not None:
        audio = {
            "path": audio_path(item.item_id),
            "duration_ms": item.audio.duration_ms,
            "sample_rate_hz": 16000,
            "is_lossy_source": item.audio.is_lossy_source,
            "sha256": item.audio.sha256,
            "bytes": item.audio.size_bytes,
            "original": {key: item.audio.original.get(key) for key in ORIGINAL_FIELDS},
            "quality": {key: item.audio.quality.get(key) for key in QUALITY_FIELDS},
        }
    record = {
        "item_id": item.item_id,
        "language": item.language,
        "speaker_code": item.speaker_code,
        # Only with the speaker's consent to share demographics; never more than the age band.
        "speaker": {"age_band": item.age_band} if item.age_band else {},
        "dialect_label": item.dialect_label,
        "content_type": item.content_type,
        "collection_method": item.collection_method,
        "recording_mode": item.recording_mode,
        "prompt": (
            {key: item.prompt[key] for key in sorted(PROMPT_FIELDS)} if item.prompt else None
        ),
        "recorded_on": item.recorded_on.isoformat() if item.recorded_on else None,
        "audio": audio,
        "transcription": (
            _text(main["transcription"], TEXT_FIELDS) if "transcription" in main else None
        ),
        "text": _text(main["standalone"], TEXT_FIELDS) if "standalone" in main else None,
        "translations": [_text(v, TRANSLATION_FIELDS) for v in translations],
        "quality_flags": sorted(item.quality_flags),
        "consent_permissions": {key: bool(item.consent.get(key)) for key in CONSENT_FIELDS},
        "collection_context": {
            key: item.collection_context[key]
            for key in COLLECTION_CONTEXT_FIELDS
            if item.collection_context.get(key) is not None
        },
    }
    if record.keys() != ITEM_FIELDS:  # pragma: no cover - a programming error
        raise ValueError("an item record does not match the export allow-list")
    return record


def _json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def items_jsonl(records: Iterable[Mapping[str, Any]]) -> bytes:
    lines = sorted(
        json.dumps(r, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for r in records
    )
    return "".join(f"{line}\n" for line in lines).encode()


# ------------------------------------------------------------------ data card


@dataclass(frozen=True)
class ReleaseInfo:
    slug: str
    version: str
    purpose: str
    licence: str | None
    frozen_at: str
    code_version: str
    data_card_markdown: str


def statistics(records: list[dict[str, Any]], speaker_share_warning: float) -> dict[str, Any]:
    """Counts for the data card (check D8) and speakers above the share limit (check D9)."""
    durations = Counter[str]()
    for record in records:
        durations[record["speaker_code"]] += (record["audio"] or {}).get("duration_ms") or 0
    total = sum(durations.values())
    texts = [
        text
        for record in records
        for text in [record["transcription"], record["text"], *record["translations"]]
        if text
    ]
    main_scripts = Counter(
        (record["transcription"] or record["text"] or {}).get("script") or "(no text)"
        for record in records
    )
    return {
        "item_count": len(records),
        "total_duration_ms": total,
        "speaker_count": len({r["speaker_code"] for r in records}),
        "by_content_type": dict(sorted(Counter(r["content_type"] for r in records).items())),
        "by_dialect_label": dict(
            sorted(Counter(r["dialect_label"] or "(none)" for r in records).items())
        ),
        "by_recording_mode": dict(
            sorted(Counter(r["recording_mode"] or "(text only)" for r in records).items())
        ),
        "by_script": dict(sorted(main_scripts.items())),
        "with_audio": sum(1 for r in records if r["audio"]),
        "lossy_sources": sum(1 for r in records if (r["audio"] or {}).get("is_lossy_source")),
        "texts": len(texts),
        "unverified_texts": sum(1 for t in texts if t["verification_status"] != "verified"),
        "translations": sum(len(r["translations"]) for r in records),
        "speakers_above_share": sorted(
            code
            for code, duration in durations.items()
            if total and duration / total > speaker_share_warning
        ),
        "speaker_share_warning": speaker_share_warning,
    }


def _table(title: str, counts: Mapping[str, int]) -> str:
    rows = "\n".join(f"| {key} | {count} |" for key, count in counts.items())
    return f"| {title} | Items |\n|---|---|\n{rows}\n"


def data_card_markdown(info: ReleaseInfo, stats: Mapping[str, Any]) -> str:
    minutes = stats["total_duration_ms"] / 60000
    share = stats["speakers_above_share"]
    bias = (
        f"{len(share)} speaker(s) each contribute more than "
        f"{stats['speaker_share_warning']:.0%} of the audio: {', '.join(share)}. Results may "
        "reflect their speech more than the community's."
        if share
        else f"No speaker contributes more than {stats['speaker_share_warning']:.0%} of the audio."
    )
    sections = [
        f"# {info.slug} {info.version}\n",
        info.data_card_markdown.strip() + "\n" if info.data_card_markdown.strip() else "",
        "## Composition\n",
        f"{stats['item_count']} items from {stats['speaker_count']} speakers, "
        f"{stats['with_audio']} with audio ({minutes:.1f} minutes in total).\n",
        _table("Content", stats["by_content_type"]),
        _table("Dialect label (as reported)", stats["by_dialect_label"]),
        _table("Recording mode", stats["by_recording_mode"]),
        _table("Script of the main text", stats["by_script"]),
        "## Consent and permitted uses\n",
        f"Purpose: `{info.purpose}`. Every item's speaker agreed to this use, checked when the "
        "release was frozen. See LICENSE.txt for the terms.\n",
        "## Known limitations\n",
        f"- {stats['unverified_texts']} of {stats['texts']} texts were written by contributors "
        "and **not checked by anyone** (`verification_status: unverified`).\n"
        f"- {stats['lossy_sources']} recordings come from compressed (lossy) sources.\n"
        "- Dialect labels are as reported by contributors, not a controlled list.\n"
        f"- {bias}\n",
        "## Preprocessing\n",
        "Audio is a 16 kHz mono FLAC copy of each original, without metadata. Text is exactly "
        "as written; nothing was corrected or normalised.\n",
        "## Withdrawal\n",
        "Speakers can withdraw their contributions. Items withdrawn after this release was "
        "frozen must be deleted from every copy; holders are told.\n",
        f"\nFrozen {info.frozen_at} by Lokdhara {info.code_version}, export format "
        f"{EXPORT_FORMAT_VERSION}.\n",
    ]
    return "\n".join(part for part in sections if part)


def data_card_json(info: ReleaseInfo, stats: Mapping[str, Any]) -> bytes:
    return _json(
        {
            "name": info.slug,
            "version": info.version,
            "purpose": info.purpose,
            "licence": info.licence,
            "language": {"bcp47": "unr", "glottolog": "mund1320", "name": "Mundari"},
            "frozen_at": info.frozen_at,
            "statistics": dict(stats),
            "texts_verified_by_reviewer": False,
        }
    )


# ------------------------------------------------------------------ the package


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str
    size_bytes: int


def entry(path: str, content: bytes) -> FileEntry:
    return FileEntry(path, hashlib.sha256(content).hexdigest(), len(content))


def manifest(info: ReleaseInfo, stats: Mapping[str, Any], files: Iterable[FileEntry]) -> bytes:
    return _json(
        {
            "release_slug": info.slug,
            "version": info.version,
            "purpose": info.purpose,
            "licence": info.licence,
            "frozen_at": info.frozen_at,
            "frozen_by_role": "admin",
            "item_count": stats["item_count"],
            "total_duration_ms": stats["total_duration_ms"],
            "export_format_version": EXPORT_FORMAT_VERSION,
            "lokdhara_git_commit": info.code_version,
            "files": [
                {"path": f.path, "sha256": f.sha256, "bytes": f.size_bytes}
                for f in sorted(files, key=lambda f: f.path)
            ],
        }
    )


def checksums(files: Iterable[FileEntry]) -> bytes:
    """sha256sum-compatible: `sha256sum -c checksums.sha256` checks the unpacked package."""
    return "".join(f"{f.sha256}  {f.path}\n" for f in sorted(files, key=lambda f: f.path)).encode()


Chunks = Callable[[], Iterator[bytes]]


def write_zip(target: IO[bytes], root: str, files: Iterable[tuple[str, Chunks]]) -> None:
    """Writes files under `root/` in path order with fixed times and permissions, so the same
    files always give the same ZIP. Audio is stored as is (FLAC is already compressed)."""
    with zipfile.ZipFile(target, "w") as archive:
        for path, chunks in sorted(files, key=lambda pair: pair[0]):
            info = zipfile.ZipInfo(f"{root}/{path}", date_time=_ZIP_TIME)
            info.create_system = 3
            info.external_attr = 0o644 << 16
            info.compress_type = (
                zipfile.ZIP_STORED if path.endswith(".flac") else zipfile.ZIP_DEFLATED
            )
            with archive.open(info, "w") as out:
                for chunk in chunks():
                    out.write(chunk)


@dataclass(frozen=True)
class Package:
    manifest: bytes
    files: list[tuple[str, Chunks]]


def _once(content: bytes) -> Chunks:
    return lambda: iter((content,))


def assemble(
    info: ReleaseInfo,
    records: list[dict[str, Any]],
    stats: Mapping[str, Any],
    audio: Mapping[str, tuple[FileEntry, Chunks]],
) -> Package:
    """Every file of the package. `audio` maps each audio path to its entry (checksum and size
    as stored) and a way to read it."""
    texts = {
        "items.jsonl": items_jsonl(records),
        "README.md": data_card_markdown(info, stats).encode(),
        "datacard.json": data_card_json(info, stats),
        "LICENSE.txt": ((info.licence or DEFAULT_LICENCE) + "\n").encode(),
    }
    entries = [entry(path, content) for path, content in texts.items()]
    entries += [file_entry for file_entry, _ in audio.values()]
    manifest_bytes = manifest(info, stats, entries)
    listed = [*entries, entry("manifest.json", manifest_bytes)]
    files = [(path, _once(content)) for path, content in texts.items()]
    files += [(path, chunks) for path, (_, chunks) in audio.items()]
    files += [
        ("manifest.json", _once(manifest_bytes)),
        ("checksums.sha256", _once(checksums(listed))),
    ]
    return Package(manifest_bytes, files)
