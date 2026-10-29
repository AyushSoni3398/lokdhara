"""Tags inside a FLAC file (a VORBIS_COMMENT metadata block), written without FFmpeg.

The release packages put their item's details in each FLAC file, so a file copied out of the
package still says what it is (ADR-029). The audio frames are passed through unchanged and the
output depends only on the input and the tags, so a package can be rebuilt byte for byte.

Only the STREAMINFO and SEEKTABLE blocks are kept; any other metadata (old tags, pictures,
padding, application data) is dropped, so nothing but the given tags is ever added.
"""

import struct
from collections.abc import Iterable, Iterator, Sequence

MAGIC = b"fLaC"
STREAMINFO, SEEKTABLE, VORBIS_COMMENT = 0, 3, 4
_KEPT = frozenset({STREAMINFO, SEEKTABLE})
_MAX_BLOCK = (1 << 24) - 1
VENDOR = "Lokdhara"


class NotFlac(ValueError):
    pass


def _valid_name(name: str) -> bool:
    return bool(name) and all(0x20 <= ord(c) <= 0x7D and c != "=" for c in name)


def comment_block(comments: Sequence[tuple[str, str]], *, last: bool) -> bytes:
    """A VORBIS_COMMENT block: field names are upper-cased ASCII, values UTF-8."""
    vendor = VENDOR.encode()
    body = [struct.pack("<I", len(vendor)), vendor, struct.pack("<I", len(comments))]
    for name, value in comments:
        if not _valid_name(name):
            raise ValueError(f"not a valid tag name: {name!r}")
        entry = f"{name.upper()}={value}".encode()
        body += [struct.pack("<I", len(entry)), entry]
    content = b"".join(body)
    if len(content) > _MAX_BLOCK:
        raise ValueError("the tags do not fit in one FLAC metadata block")
    return bytes([(0x80 if last else 0) | VORBIS_COMMENT]) + len(content).to_bytes(3) + content


class _Reader:
    def __init__(self, chunks: Iterable[bytes]) -> None:
        self._chunks = iter(chunks)
        self._buffer = bytearray()

    def take(self, size: int) -> bytes:
        while len(self._buffer) < size:
            chunk = next(self._chunks, None)
            if chunk is None:
                raise NotFlac("the file ends inside its metadata")
            self._buffer += chunk
        taken = bytes(self._buffer[:size])
        del self._buffer[:size]
        return taken

    def rest(self) -> Iterator[bytes]:
        if self._buffer:
            yield bytes(self._buffer)
            self._buffer.clear()
        yield from self._chunks


def tagged(chunks: Iterable[bytes], comments: Sequence[tuple[str, str]]) -> Iterator[bytes]:
    """The FLAC file read from `chunks`, with its metadata replaced by `comments`."""
    reader = _Reader(chunks)
    if reader.take(4) != MAGIC:
        raise NotFlac("not a FLAC file")
    kept: list[tuple[int, bytes]] = []
    last = False
    while not last:
        header = reader.take(4)
        last, kind = bool(header[0] & 0x80), header[0] & 0x7F
        body = reader.take(int.from_bytes(header[1:]))
        if kind in _KEPT:
            kept.append((kind, body))
    if not kept or kept[0][0] != STREAMINFO:
        raise NotFlac("the file has no STREAMINFO block first")
    head = [MAGIC]
    for kind, body in kept:
        head += [bytes([kind]), len(body).to_bytes(3), body]
    head.append(comment_block(comments, last=True))
    yield b"".join(head)
    yield from reader.rest()
