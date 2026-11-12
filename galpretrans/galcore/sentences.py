from galcore.textutil import normalize_source, source_hash


def make_sentence(engine_id, file_key, order_key, source_text):
    source = normalize_source(source_text)
    return {
        "locationId": "%s:%s:%s" % (engine_id, file_key, order_key),
        "fileKey": file_key,
        "orderKey": order_key,
        "sourceText": source,
        "sourceHash": source_hash(source),
        "status": "pending",
        "origin": None,
        "translatedText": None,
        "failureCode": None,
    }


def pending(sentences):
    return [row for row in sentences if row["status"] == "pending"]
