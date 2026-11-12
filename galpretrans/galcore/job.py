import json
from pathlib import Path

from galcore.machine import transition
from galcore.sentences import pending


def new_job(engine_id, extractor_version, sentences):
    return {
        "state": "ready_to_translate",
        "engineId": engine_id,
        "extractorVersion": extractor_version,
        "sentences": sentences,
        "importFrom": None,
        "failureCode": None,
        "lastError": None,
        "modelId": None,
        "glossaryVersion": 0,
        "cache": {},
    }


def load_job(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_job(path, job):
    Path(path).write_text(json.dumps(job, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def move(job, event):
    job["state"] = transition(job["state"], event, job.get("importFrom"))
    return job


def begin_import(job):
    origin = job["state"]
    job["state"] = transition(origin, "start_import")
    job["importFrom"] = origin
    return job


def finish_import(job, report):
    origin = job["importFrom"]
    if report["error"]:
        job["sentences"] = report["sentences"]
        job["lastError"] = report["error"]
        job["state"] = transition("importing", "rejected", origin)
        job["importFrom"] = None
        return job
    job["sentences"] = report["sentences"]
    job["lastError"] = None
    if pending(job["sentences"]):
        job["state"] = transition("importing", "still_pending", origin)
    else:
        job["state"] = transition("importing", "no_pending", origin)
    job["importFrom"] = None
    return job


def keep_source(job):
    for row in job["sentences"]:
        if row["status"] == "pending":
            row["status"] = "failed"
            row["failureCode"] = "KEEP_SOURCE"
            row["origin"] = None
            row["translatedText"] = None
    job["state"] = transition(job["state"], "keep_source")
    return job
