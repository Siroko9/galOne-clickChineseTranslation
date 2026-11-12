from galcore.llama import InferenceFailed
from galcore.prompt import SYSTEM_PROMPT, build_user, fit_history
from galcore.sentences import pending
from galcore.textutil import cache_key, decode_newlines
from galcore.validate import batch_problem, split_output


def translate_job(job, client, glossary_body, glossary_version, model_id, pattern=None, batch_size=8, on_batch=None):
    if batch_size < 7 or batch_size > 10:
        raise ValueError("batch size must be 7 to 10")
    job["modelId"] = model_id
    job["glossaryVersion"] = glossary_version
    for row in job["sentences"]:
        if row["status"] != "pending":
            continue
        cached = _cached(job, row, model_id, glossary_version)
        if cached is not None:
            _accept(row, cached)
    history = []
    remaining = [row for row in job["sentences"] if row["status"] == "pending"]
    saw_invalid = False
    for start in range(0, len(remaining), batch_size):
        batch = remaining[start : start + batch_size]
        sources = [row["sourceText"] for row in batch]
        kept = fit_history(history, glossary_body, sources)
        user = build_user(kept, glossary_body, sources)
        result = _request(client, user, sources, pattern)
        if result == "inference_failed":
            job["lastError"] = "INFERENCE_FAILED"
            return job
        if result == "invalid":
            for row in batch:
                row["status"] = "failed"
                row["failureCode"] = "OUTPUT_INVALID"
                row["origin"] = None
                row["translatedText"] = None
            saw_invalid = True
            if on_batch:
                on_batch(job)
            continue
        for row, line in zip(batch, result):
            _accept(row, line)
            _store(job, row, model_id, glossary_version, line)
        history = list(result)
        if on_batch:
            on_batch(job)
    job["lastError"] = "OUTPUT_INVALID" if saw_invalid else None
    return job


def _request(client, user, sources, pattern):
    for _attempt in (1, 2):
        try:
            raw = client.complete(SYSTEM_PROMPT, user)
        except InferenceFailed:
            return "inference_failed"
        lines = split_output(raw or "")
        if batch_problem(sources, lines, pattern) is None:
            return lines
    return "invalid"


def _accept(row, line):
    row["status"] = "translated"
    row["origin"] = "model"
    row["translatedText"] = decode_newlines(line)
    row["failureCode"] = None


def _cached(job, row, model_id, glossary_version):
    return job.setdefault("cache", {}).get(cache_key(model_id, glossary_version, row["sourceText"]))


def _store(job, row, model_id, glossary_version, line):
    job.setdefault("cache", {})[cache_key(model_id, glossary_version, row["sourceText"])] = line


def has_pending(job):
    return bool(pending(job["sentences"]))
