from galcore.textutil import decode_newlines, encode_newlines, source_hash
from galcore.validate import control_counts


def import_pack(sentences, pack, engine_id, extractor_version, pattern=None, overwrite=False):
    original = sentences
    if not isinstance(pack, dict) or pack.get("format") != 1:
        return _rejected("IMPORT_FORMAT", original, extractor_version, "")
    if "engineId" not in pack or "extractorVersion" not in pack or not isinstance(pack.get("entries"), list):
        return _rejected("IMPORT_FORMAT", original, extractor_version, "")
    if pack["engineId"] != engine_id:
        return _rejected("IMPORT_ENGINE_MISMATCH", original, extractor_version, pack["extractorVersion"])

    accepted = {}
    ambiguous = set()
    rejected = 0
    for entry in pack["entries"]:
        parsed = _parse_entry(entry, pattern)
        if parsed is None:
            rejected += 1
            continue
        digest, translated = parsed
        if digest in ambiguous:
            continue
        if digest in accepted and accepted[digest] != translated:
            ambiguous.add(digest)
            del accepted[digest]
            continue
        accepted[digest] = translated

    hits = 0
    already = 0
    missed = 0
    updated = []
    changed = False
    for row in original:
        digest = row["sourceHash"]
        if digest in ambiguous or digest not in accepted:
            if digest not in accepted and digest not in ambiguous:
                missed += 1
            updated.append(dict(row))
            continue
        if row["status"] == "pending":
            copied = dict(row)
            copied["status"] = "translated"
            copied["origin"] = "import"
            copied["translatedText"] = decode_newlines(accepted[digest])
            copied["failureCode"] = None
            updated.append(copied)
            hits += 1
            changed = True
            continue
        if row["status"] == "translated" and overwrite:
            copied = dict(row)
            copied["origin"] = "import"
            copied["translatedText"] = decode_newlines(accepted[digest])
            copied["failureCode"] = None
            updated.append(copied)
            hits += 1
            changed = True
            continue
        if row["status"] == "translated":
            already += 1
        updated.append(dict(row))

    if hits == 0:
        return _rejected("IMPORT_NO_MATCH", original, extractor_version, pack["extractorVersion"], rejected, already, missed, len(ambiguous))
    return {
        "error": None,
        "hits": hits,
        "already": already,
        "ambiguous": len(ambiguous),
        "rejected": rejected,
        "missed": missed,
        "versionMismatch": str(pack["extractorVersion"]) != str(extractor_version),
        "sentences": updated if changed else original,
    }


def _parse_entry(entry, pattern):
    if not isinstance(entry, dict):
        return None
    source = entry.get("sourceText")
    translated = entry.get("translatedText")
    if not isinstance(source, str) or not isinstance(translated, str) or translated == "":
        return None
    digest = source_hash(source)
    stated = entry.get("sourceHash")
    if stated is not None and stated != digest:
        return None
    encoded = encode_newlines(translated)
    if pattern is not None and control_counts(source, pattern) != control_counts(encoded, pattern):
        return None
    return digest, encoded


def _rejected(code, sentences, local_version, pack_version, rejected=0, already=0, missed=0, ambiguous=0):
    return {
        "error": code,
        "hits": 0,
        "already": already,
        "ambiguous": ambiguous,
        "rejected": rejected,
        "missed": missed,
        "versionMismatch": str(pack_version) != str(local_version),
        "sentences": sentences,
    }
