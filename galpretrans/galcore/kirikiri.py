"""Kirikiri2 / KAG reader.

Detection matches Tyranor-Next: a game directory contains a .xp3 archive or
startup.tjs. The archive index is the usual XP3 layout (optional 0x80
indirection, then a zlib-compressed File/info/segm/adlr table). Script text is
read from .ks files only. Dialogue is one source line; [tags] stay in the
sentence so the control-token check can reject a translation that drops them.
"""

import os
import re
import struct
import unicodedata
import zlib
from pathlib import Path

from galcore.errors import GalError
from galcore.sentences import make_sentence
from galcore.textutil import decode_newlines, normalize_source, safe_file_key

ENGINE_ID = "kirikiri"
EXTRACTOR_VERSION = "1"
MAGIC = b"XP3\r\n \n\x1a\x8b\x67\x01"
ENCRYPTED = 0x80000000
_JAPANESE = re.compile(u"[\\u3040-\\u30ff\\u3400-\\u9fff\\uff66-\\uff9d]")
_CODE = re.compile(r"[{};]|function\b|\bvar\b|\bkag\.|\btf\.|\bsf\.")
_NAME = re.compile(r'\bchara="([^"]*)"')
_CONTROL = r"\[[^\]\r\n]+\]"


def install():
    from galcore.registry import current, register

    plugin = current()
    if plugin is None:
        register(KirikiriPlugin())
    elif not isinstance(plugin, KirikiriPlugin):
        raise RuntimeError("v1 registers one engine plugin")


class KirikiriPlugin:
    engine_id = ENGINE_ID
    extractor_version = EXTRACTOR_VERSION

    def detect(self, root):
        game, _prefix = locate(root)
        return game is not None

    def control_pattern(self):
        return _CONTROL

    def storage_key(self, file_key):
        lower = file_key.lower()
        marker = ".xp3/"
        index = lower.find(marker)
        if index != -1:
            return file_key[: index + 4]
        return file_key

    def extract(self, root):
        try:
            return _extract(root)
        except GalError:
            raise
        except Exception as exc:
            raise GalError("EXTRACT_FAILED", "kirikiri extract failed") from exc

    def apply_file(self, root, file_key, ordered):
        if ".xp3/" in file_key.lower():
            self.apply_storage(root, self.storage_key(file_key), [(file_key, ordered)])
            return
        path = Path(root).joinpath(*file_key.split("/"))
        original = path.read_bytes()
        text = decode_script(original)
        new_text, changed = replace_lines(text, ordered)
        if changed:
            path.write_bytes(encode_script(new_text, original))

    def apply_storage(self, root, storage, files):
        if storage.lower().endswith(".xp3"):
            replacements = {}
            for file_key, rows in files:
                inner = file_key.split(".xp3/", 1)[1]
                replacements[inner] = rows
            rewrite_archive(Path(root).joinpath(*storage.split("/")), replacements)
            return
        for file_key, rows in files:
            self.apply_file(root, file_key, rows)

    def verify(self, root):
        game, _prefix = locate(root)
        if game is None:
            raise RuntimeError("kirikiri marker missing")
        archives = xp3_files(game)
        if not archives and not (game / "startup.tjs").is_file():
            raise RuntimeError("kirikiri marker missing")
        for archive in archives:
            handle, entries = open_archive(archive)
            try:
                size = archive.stat().st_size
                for entry in entries:
                    if entry.get("raw") is not None:
                        raise RuntimeError("unknown xp3 tag")
                    for comp, offset, unpacked, packed in entry["segments"]:
                        if offset < 0 or packed < 0 or offset + packed > size:
                            raise RuntimeError("segment out of range")
                    if entry["adlr"] is None:
                        continue
                    data = read_bytes(handle, entry)
                    if (zlib.adler32(data) & 0xFFFFFFFF) != entry["adlr"]:
                        raise RuntimeError("adlr mismatch")
            finally:
                handle.close()


def locate(root):
    root = Path(root)
    if not root.is_dir():
        return None, None
    if marked(root):
        return root, ""
    children = sorted(
        (path for path in root.iterdir() if path.is_dir() and marked(path)),
        key=lambda path: path.name.lower(),
    )
    if len(children) == 1:
        return children[0], children[0].name
    return None, None


def marked(path):
    try:
        children = list(path.iterdir())
    except OSError:
        return False
    return any(child.is_file() and marker_name(child.name) for child in children)


def marker_name(name):
    lower = name.lower()
    return lower.endswith(".xp3") or lower == "startup.tjs"


def xp3_files(path):
    return [child for child in path.iterdir() if child.is_file() and child.name.lower().endswith(".xp3")]


def _extract(root):
    game, prefix = locate(root)
    if game is None:
        return []
    found = {}
    for archive in sorted(xp3_files(game), key=lambda path: path.name.lower()):
        handle, entries = open_archive(archive)
        try:
            for entry in entries:
                name = entry.get("name")
                if not _is_ks(name) or entry["flags"] & ENCRYPTED:
                    continue
                found[name] = (_file_key(prefix, archive.name, name), read_bytes(handle, entry))
        finally:
            handle.close()
    for loose in sorted(game.rglob("*.ks")):
        if not loose.is_file():
            continue
        inner = loose.relative_to(game).as_posix()
        key = inner if not prefix else prefix + "/" + inner
        safe_file_key(key)
        found[inner] = (key, loose.read_bytes())
    rows = []
    for name in sorted(found):
        file_key, data = found[name]
        rows.extend(sentences_from_script(ENGINE_ID, file_key, decode_script(data)))
    rows.sort(key=_order)
    return rows


def _is_ks(name):
    if not name:
        return False
    name = name.replace("\\", "/")
    if name.lower().endswith(".ks") and ".." not in name.split("/") and ":" not in name:
        return True
    return False


def _file_key(prefix, archive_name, inner):
    key = archive_name + "/" + inner.replace("\\", "/")
    if prefix:
        key = prefix + "/" + key
    return safe_file_key(key)


def _order(row):
    key = row["fileKey"]
    lower = key.lower()
    index = lower.find(".xp3/")
    inner = key[index + 5 :] if index != -1 else key
    return (inner, row["orderKey"])


def sentences_from_script(engine_id, file_key, text):
    rows = []
    inside_script = False
    for index, (content, _ending) in enumerate(script_lines(text)):
        stripped = content.strip()
        if not stripped:
            continue
        command = _command(stripped)
        if command == "iscript":
            inside_script = True
            continue
        if command == "endscript":
            inside_script = False
            continue
        if inside_script or stripped.startswith(";") or stripped.startswith("*") or stripped.startswith("//"):
            continue
        if command == "name" or stripped.startswith("@name"):
            match = _NAME.search(stripped)
            if match and _JAPANESE.search(match.group(1)):
                rows.append(make_sentence(engine_id, file_key, index, match.group(1)))
            continue
        if command is not None or stripped[0] in "@[":
            continue
        if _CODE.search(stripped) or not _JAPANESE.search(stripped):
            continue
        rows.append(make_sentence(engine_id, file_key, index, stripped))
    return rows


def _command(stripped):
    if stripped.startswith("@"):
        return stripped[1:].split(None, 1)[0].split("=", 1)[0].lower()
    if stripped.startswith("[") and "]" in stripped:
        return stripped[1:].split("]", 1)[0].split(None, 1)[0].lower()
    return None


def script_lines(text):
    lines = []
    index = 0
    length = len(text)
    while index < length:
        end = index
        while end < length and text[end] not in "\r\n":
            end += 1
        ending = ""
        if end < length:
            if text[end] == "\r" and end + 1 < length and text[end + 1] == "\n":
                ending = "\r\n"
            else:
                ending = text[end]
        lines.append((text[index:end], ending))
        index = end + len(ending)
    return lines


def replace_lines(text, rows):
    by_order = {row["orderKey"]: row for row in rows}
    pieces = []
    changed = False
    for index, (content, ending) in enumerate(script_lines(text)):
        updated = _replace_line(content, by_order.get(index))
        if updated is not None:
            content = updated
            changed = True
        pieces.append(content + ending)
    return "".join(pieces), changed


def _replace_line(content, row):
    if not row or row.get("status") != "translated" or not row.get("translatedText"):
        return None
    translated = decode_newlines(row["translatedText"])
    if translated == "" or "\n" in translated or "\r" in translated:
        return None
    stripped = content.strip()
    if stripped.startswith("@name"):
        if '"' in translated or "\\" in translated:
            return None
        match = _NAME.search(content)
        if not match or unicodedata.normalize("NFC", match.group(1)) != row["sourceText"]:
            return None
        start, end = match.span(1)
        return content[:start] + translated + content[end:]
    try:
        if normalize_source(stripped) != row["sourceText"]:
            return None
    except ValueError:
        return None
    lead = content[: len(content) - len(content.lstrip())]
    return lead + translated


def decode_script(data):
    if data.startswith(b"\xff\xfe"):
        return data[2:].decode("utf-16le")
    if data.startswith(b"\xfe\xff"):
        return data[2:].decode("utf-16be")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    for encoding in ("cp932", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise GalError("EXTRACT_FAILED", "script encoding")


def encode_script(text, original):
    if original.startswith(b"\xff\xfe"):
        return b"\xff\xfe" + text.encode("utf-16le")
    if original.startswith(b"\xfe\xff"):
        return b"\xfe\xff" + text.encode("utf-16be")
    if original.startswith(b"\xef\xbb\xbf"):
        return b"\xef\xbb\xbf" + text.encode("utf-8")
    try:
        return text.encode("cp932")
    except UnicodeEncodeError:
        return b"\xff\xfe" + text.encode("utf-16le")


def open_archive(path):
    handle = open(path, "rb")
    try:
        entries = parse_entries(handle)
    except Exception:
        handle.close()
        raise
    return handle, entries


def parse_entries(handle):
    handle.seek(0)
    if handle.read(11) != MAGIC:
        raise GalError("EXTRACT_FAILED", "xp3 magic")
    (index_at,) = struct.unpack("<Q", handle.read(8))
    handle.seek(index_at)
    marker = handle.read(1)
    if len(marker) != 1:
        raise GalError("EXTRACT_FAILED", "xp3 index")
    if marker[0] & 0x80:
        handle.read(8)
        (index_at,) = struct.unpack("<Q", handle.read(8))
        handle.seek(index_at)
        marker = handle.read(1)
        if len(marker) != 1:
            raise GalError("EXTRACT_FAILED", "xp3 index")
    packed, raw_size = struct.unpack("<QQ", handle.read(16))
    if packed > 64 * 1024 * 1024:
        raise GalError("EXTRACT_FAILED", "xp3 index size")
    blob = handle.read(packed)
    if len(blob) != packed:
        raise GalError("EXTRACT_FAILED", "xp3 index truncated")
    if marker[0] == 1:
        try:
            blob = zlib.decompress(blob)
        except zlib.error as exc:
            raise GalError("EXTRACT_FAILED", "xp3 index") from exc
    elif marker[0] != 0:
        raise GalError("EXTRACT_FAILED", "xp3 index flag")
    if len(blob) != raw_size:
        raise GalError("EXTRACT_FAILED", "xp3 index length")
    return _read_table(blob)


def _read_table(blob):
    entries = []
    pos = 0
    while pos + 12 <= len(blob):
        tag = blob[pos : pos + 4]
        size = struct.unpack_from("<Q", blob, pos + 4)[0]
        pos += 12
        if size > len(blob) - pos:
            raise GalError("EXTRACT_FAILED", "xp3 entry")
        body = blob[pos : pos + size]
        pos += size
        if tag != b"File":
            entries.append({"raw": tag, "body": body, "name": None, "flags": 0, "segments": [], "adlr": None, "extras": []})
            continue
        entries.append(_read_file(body))
    if pos != len(blob):
        raise GalError("EXTRACT_FAILED", "xp3 table")
    return entries


def _read_file(body):
    pos = 0
    name = None
    flags = 0
    segments = []
    adlr = None
    extras = []
    while pos + 12 <= len(body):
        tag = body[pos : pos + 4]
        size = struct.unpack_from("<Q", body, pos + 4)[0]
        pos += 12
        if size > len(body) - pos:
            raise GalError("EXTRACT_FAILED", "xp3 section")
        payload = body[pos : pos + size]
        pos += size
        if tag == b"info" and len(payload) >= 22:
            flags = struct.unpack_from("<I", payload, 0)[0]
            chars = struct.unpack_from("<H", payload, 20)[0]
            name = payload[22 : 22 + chars * 2].decode("utf-16le").replace("\\", "/")
        elif tag == b"segm":
            cursor = 0
            while cursor + 28 <= len(payload):
                segments.append(struct.unpack_from("<iQQQ", payload, cursor))
                cursor += 28
        elif tag == b"adlr" and len(payload) >= 4:
            adlr = struct.unpack_from("<I", payload, 0)[0]
        else:
            extras.append((tag, payload))
    return {"raw": None, "name": name, "flags": flags, "segments": segments, "adlr": adlr, "extras": extras}


def read_bytes(handle, entry):
    if entry["flags"] & ENCRYPTED:
        raise GalError("EXTRACT_FAILED", "encrypted xp3 entry")
    parts = []
    for comp, offset, unpacked, packed in entry["segments"]:
        if offset < 0 or packed < 0 or packed > 256 * 1024 * 1024:
            raise GalError("EXTRACT_FAILED", "xp3 segment")
        handle.seek(offset)
        blob = handle.read(packed)
        if len(blob) != packed:
            raise GalError("EXTRACT_FAILED", "xp3 segment truncated")
        if comp:
            try:
                blob = zlib.decompress(blob)
            except zlib.error as exc:
                raise GalError("EXTRACT_FAILED", "xp3 segment") from exc
        if unpacked and len(blob) != unpacked:
            raise GalError("EXTRACT_FAILED", "xp3 segment length")
        parts.append(blob)
    return b"".join(parts)


def rewrite_archive(path, replacements):
    path = Path(path)
    handle, entries = open_archive(path)
    tmp = path.with_name(path.name + ".writing")
    try:
        if any(entry.get("raw") is not None or not entry.get("name") for entry in entries):
            raise GalError("EXTRACT_FAILED", "xp3 entry")
        present = {entry["name"] for entry in entries}
        if not set(replacements).issubset(present):
            raise GalError("EXTRACT_FAILED", "script missing")
        with open(tmp, "wb") as out:
            out.write(MAGIC)
            out.write(struct.pack("<Q", 0))
            rebuilt = []
            for entry in entries:
                if entry["name"] in replacements:
                    original = read_bytes(handle, entry)
                    new_text, changed = replace_lines(decode_script(original), replacements[entry["name"]])
                    if changed:
                        data = encode_script(new_text, original)
                        payload = zlib.compress(data)
                        offset = out.tell()
                        out.write(payload)
                        segments = [(1, offset, len(data), len(payload))]
                        adlr = zlib.adler32(data) & 0xFFFFFFFF
                        rebuilt.append((entry, segments, adlr))
                        continue
                segments = []
                for comp, offset, unpacked, packed in entry["segments"]:
                    new_offset = out.tell()
                    _copy_span(handle, out, offset, packed)
                    segments.append((comp, new_offset, unpacked, packed))
                rebuilt.append((entry, segments, entry["adlr"]))
            index_at = out.tell()
            raw = b"".join(_pack_entry(entry, segments, adlr) for entry, segments, adlr in rebuilt)
            compressed = zlib.compress(raw)
            out.write(struct.pack("<BQQ", 1, len(compressed), len(raw)))
            out.write(compressed)
        handle.close()
        handle = None
        with open(tmp, "r+b") as out:
            out.seek(11)
            out.write(struct.pack("<Q", index_at))
        os.replace(tmp, path)
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
    finally:
        if handle is not None:
            handle.close()


def _copy_span(src, dst, offset, size):
    src.seek(offset)
    remaining = size
    while remaining:
        chunk = src.read(min(1024 * 1024, remaining))
        if not chunk:
            raise GalError("EXTRACT_FAILED", "xp3 segment truncated")
        dst.write(chunk)
        remaining -= len(chunk)


def _pack_entry(entry, segments, adlr):
    encoded = entry["name"].encode("utf-16le")
    unpacked = sum(segment[2] for segment in segments)
    packed = sum(segment[3] for segment in segments)
    info = struct.pack("<IQQH", entry["flags"], unpacked, packed, len(encoded) // 2) + encoded
    segm = b"".join(struct.pack("<iQQQ", *segment) for segment in segments)
    parts = [(b"info", info), (b"segm", segm)]
    if adlr is not None:
        parts.append((b"adlr", struct.pack("<I", adlr)))
    parts.extend(entry["extras"])
    body = b"".join(tag + struct.pack("<Q", len(payload)) + payload for tag, payload in parts)
    return b"File" + struct.pack("<Q", len(body)) + body


def write_archive(path, files):
    """Write a small XP3. Each item is (name, data, compressed). data may be a list of segments."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as out:
        out.write(MAGIC)
        out.write(struct.pack("<Q", 0))
        built = []
        for name, data, compressed in files:
            parts = data if isinstance(data, list) else [data]
            whole = b"".join(parts)
            segments = []
            for part in parts:
                payload = zlib.compress(part) if compressed else part
                offset = out.tell()
                out.write(payload)
                segments.append((1 if compressed else 0, offset, len(part), len(payload)))
            built.append((name, segments, zlib.adler32(whole) & 0xFFFFFFFF))
        index_at = out.tell()
        raw = b"".join(
            _pack_entry(
                {"name": name, "flags": 0, "extras": []},
                segments,
                adlr,
            )
            for name, segments, adlr in built
        )
        compressed = zlib.compress(raw)
        out.write(struct.pack("<BQQ", 1, len(compressed), len(raw)))
        out.write(compressed)
    with open(path, "r+b") as out:
        out.seek(11)
        out.write(struct.pack("<Q", index_at))
