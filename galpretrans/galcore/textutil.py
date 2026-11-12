import hashlib
import unicodedata


def encode_newlines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "\\n")


def decode_newlines(text):
    return text.replace("\\n", "\n")


def normalize_source(text):
    encoded = encode_newlines(text)
    if "\n" in encoded or "\r" in encoded:
        raise ValueError("source text still contains a line break")
    return unicodedata.normalize("NFC", encoded)


def source_hash(source_text):
    normalized = unicodedata.normalize("NFC", source_text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def cache_key(model_id, glossary_version, source_text):
    raw = "%s\n%s\n%s" % (model_id, glossary_version, source_text)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def estimate_tokens(text):
    total = 0
    for char in text:
        total += 1 if ord(char) > 127 else 0.25
    return int(total + 0.999)


def safe_file_key(file_key):
    if not isinstance(file_key, str) or not file_key:
        raise ValueError("empty file key")
    if "\\" in file_key or file_key.startswith("/") or ":" in file_key:
        raise ValueError("unsafe file key")
    parts = file_key.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError("unsafe file key")
    return file_key
