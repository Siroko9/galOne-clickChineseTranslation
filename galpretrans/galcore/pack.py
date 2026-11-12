import json

from galcore.textutil import encode_newlines, source_hash


def export_pack(engine_id, extractor_version, sentences):
    entries = []
    for row in sentences:
        if row["status"] != "translated":
            continue
        source = row["sourceText"]
        translated = encode_newlines(row["translatedText"] or "")
        entries.append(
            {
                "sourceText": source,
                "translatedText": translated,
                "sourceHash": source_hash(source),
            }
        )
    return {
        "format": 1,
        "engineId": engine_id,
        "extractorVersion": extractor_version,
        "entries": entries,
    }


def dumps_pack(pack):
    return json.dumps(pack, ensure_ascii=False, indent=2) + "\n"


def loads_pack(text):
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data
