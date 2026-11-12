import time
from pathlib import Path

from galcore.errors import GalError
from galcore.job import keep_source, load_job, move, new_job, save_job
from galcore.kirikiri import install
from galcore.llama import LlamaClient
from galcore.pack import dumps_pack, export_pack
from galcore.registry import current, extract
from galcore.translate import has_pending, translate_job
from galphone.__main__ import confirm, import_file
from galui.setup import MODEL_ID, detect_kind, ensure_runtime, server_ready, start_server

IMPORT_DIR = "\u6c49\u5316\u5bfc\u5165"
PACK_NAME = "\u7ffb\u8bd1\u7ed3\u679c.galpack.json"


class WorkflowError(Exception):
    pass


def one_click_prepare(game_root, log, client=None, skip_setup=False):
    game_root = Path(game_root)
    install()
    if not skip_setup:
        kind = detect_kind()
        server, model = ensure_runtime(log, kind=kind)
        if not server_ready():
            log("\u6b63\u5728\u542f\u52a8\u7ffb\u8bd1\u670d\u52a1")
            start_server(server, model, kind)
            _wait_until_ready()
        log("\u7ffb\u8bd1\u670d\u52a1\u5df2\u5c31\u7eea")
    job_path = _job_path(game_root)
    job = _load_or_extract(game_root, job_path, log)
    if job["state"] == "ready_to_apply":
        path = _export(game_root, job)
        log("\u7ffb\u8bd1\u5df2\u7ecf\u5b8c\u6210\u3002\u6c49\u5316\u5305\u5728\uff1a%s" % path)
        log("\u63a5\u4e0b\u6765\u70b9\u300c\u4e00\u952e\u5bfc\u5165\u300d\u3002")
        return job
    if job["state"] == "done":
        log("\u8fd9\u4e2a\u6587\u4ef6\u5939\u5df2\u7ecf\u5199\u56de\u8fc7\u4e86\u3002")
        return job
    if job["state"] == "ready_to_translate":
        move(job, "start_translate")
    elif job["state"] == "paused":
        move(job, "resume")
    elif job["state"] != "translating":
        raise WorkflowError(job.get("failureCode") or job["state"])
    save_job(job_path, job)
    if client is None:
        client = LlamaClient("http://127.0.0.1:8080", MODEL_ID)
    plugin = current()
    pattern = None if plugin is None else plugin.control_pattern()

    def on_batch(current_job):
        save_job(job_path, current_job)
        done = sum(row["status"] != "pending" for row in current_job["sentences"])
        log("\u6b63\u5728\u7ffb\u8bd1 %d/%d" % (done, len(current_job["sentences"])))

    translate_job(job, client, "", 0, MODEL_ID, pattern, 8, on_batch)
    if not has_pending(job):
        move(job, "no_pending")
    elif job.get("lastError") == "INFERENCE_FAILED":
        move(job, "pause")
    save_job(job_path, job)
    if job["state"] == "paused":
        log("\u7ffb\u8bd1\u4e2d\u65ad\u4e86\u3002\u518d\u70b9\u4e00\u6b21\u300c\u4e00\u952e\u51c6\u5907\u5e76\u7ffb\u8bd1\u300d\u4f1a\u63a5\u7740\u7ffb\u3002")
        return job
    path = _export(game_root, job)
    log("\u7ffb\u8bd1\u5b8c\u6210\u3002\u6c49\u5316\u5305\u5728\uff1a%s" % path)
    log("\u63a5\u4e0b\u6765\u70b9\u300c\u4e00\u952e\u5bfc\u5165\u300d\u3002")
    return job


def one_click_import(game_root, log):
    game_root = Path(game_root)
    install()
    pack = _find_pack(game_root)
    if pack is None:
        folder = game_root / IMPORT_DIR
        folder.mkdir(parents=True, exist_ok=True)
        raise WorkflowError("\u8bf7\u628a .galpack.json \u653e\u8fdb\u8fd9\u4e2a\u6587\u4ef6\u5939\uff1a%s" % folder)
    log("\u4f7f\u7528\u6c49\u5316\u5305\uff1a%s" % pack.name)
    job_path = _job_path(game_root)
    job = _load_or_extract(game_root, job_path, log)
    if job["state"] in ("failed", "cancelled"):
        failed = job_path.with_name("job.failed.json")
        if failed.exists():
            failed.unlink()
        job_path.replace(failed)
        job = _load_or_extract(game_root, job_path, log)
    if job["state"] == "done":
        log("\u8fd9\u4e2a\u6587\u4ef6\u5939\u5df2\u7ecf\u5199\u56de\u8fc7\u4e86\u3002")
        return job
    if job["state"] == "translating":
        move(job, "pause")
        save_job(job_path, job)
        job = load_job(job_path)
    report = import_file(job_path, pack)
    job = load_job(job_path)
    if job.get("lastError") == "IMPORT_NO_MATCH" and report.get("already") and job["state"] == "ready_to_apply":
        job["lastError"] = None
        save_job(job_path, job)
        log("\u8fd9\u4e9b\u53e5\u5b50\u5df2\u7ecf\u7ffb\u8bd1\u8fc7\uff0c\u76f4\u63a5\u5199\u5165\u6e38\u620f")
    elif job.get("lastError"):
        raise WorkflowError(_import_message(job["lastError"]))
    else:
        log("\u5bf9\u4e0a\u4e86 %d \u53e5" % report["hits"])
    if job["state"] in ("ready_to_translate", "paused") and has_pending(job):
        keep_source(job)
        save_job(job_path, job)
        log("\u6ca1\u5bf9\u4e0a\u7684\u53e5\u5b50\u4fdd\u6301\u65e5\u6587")
    if job["state"] != "ready_to_apply":
        raise WorkflowError(job.get("lastError") or job["state"])
    backup = game_root.parent / (game_root.name + "-backup")
    log("\u6b63\u5728\u5199\u5165\u6e38\u620f\uff0c\u8bf7\u4e0d\u8981\u5173\u95ed\u7a97\u53e3")
    result = confirm(job_path, game_root, backup)
    if result["state"] != "done":
        raise WorkflowError(result.get("failureCode") or result["state"])
    log("\u6c49\u5316\u5df2\u7ecf\u5199\u8fdb\u6e38\u620f\u3002\u628a\u8fd9\u4e2a\u6587\u4ef6\u5939\u62f7\u5230\u624b\u673a\uff0c\u7528 Tyranor \u6253\u5f00\u3002")
    log("\u5907\u4efd\u5728\uff1a%s" % backup)
    return result


def _load_or_extract(game_root, job_path, log):
    if job_path.is_file():
        return load_job(job_path)
    log("\u6b63\u5728\u62bd\u51fa\u53e5\u5b50")
    try:
        code, sentences = extract(game_root)
    except GalError as exc:
        raise WorkflowError(exc.code) from exc
    if code != "OK":
        raise WorkflowError(
            "\u8ba4\u4e0d\u51fa\u8fd9\u4e2a\u6587\u4ef6\u5939\u91cc\u7684\u6e38\u620f\u3002\u8bf7\u9009\u5230\u542b\u6709 data.xp3 \u7684\u90a3\u4e00\u5c42\u3002"
        )
    plugin = current()
    job = new_job(plugin.engine_id, plugin.extractor_version, sentences)
    job_path.parent.mkdir(parents=True, exist_ok=True)
    save_job(job_path, job)
    log("\u62bd\u51fa\u4e86 %d \u53e5" % len(sentences))
    return job


def _job_path(game_root):
    return Path(game_root) / IMPORT_DIR / "job.json"


def _export(game_root, job):
    folder = Path(game_root) / IMPORT_DIR
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / PACK_NAME
    pack = export_pack(job["engineId"], job["extractorVersion"], job["sentences"])
    path.write_text(dumps_pack(pack), encoding="utf-8")
    return path


def _find_pack(game_root):
    folder = Path(game_root) / IMPORT_DIR
    if not folder.is_dir():
        return None
    packs = [path for path in folder.glob("*.galpack.json") if path.is_file()]
    if not packs:
        return None
    return max(packs, key=lambda path: path.stat().st_mtime)


def _import_message(code):
    if code == "IMPORT_NO_MATCH":
        return "\u8fd9\u4e2a\u6c49\u5316\u5305\u548c\u5f53\u524d\u6e38\u620f\u5bf9\u4e0d\u4e0a\uff0c\u6e38\u620f\u6587\u4ef6\u6ca1\u6709\u6539"
    if code == "IMPORT_ENGINE_MISMATCH":
        return "\u8fd9\u4e2a\u6c49\u5316\u5305\u4e0d\u662f Kirikiri \u7684\uff0c\u6e38\u620f\u6587\u4ef6\u6ca1\u6709\u6539"
    if code == "IMPORT_FORMAT":
        return "\u6c49\u5316\u5305\u683c\u5f0f\u4e0d\u5bf9\uff0c\u6e38\u620f\u6587\u4ef6\u6ca1\u6709\u6539"
    return code


def _wait_until_ready():
    for _ in range(180):
        if server_ready():
            return
        time.sleep(1)
    raise WorkflowError("\u7ffb\u8bd1\u670d\u52a1\u6ca1\u6709\u542f\u52a8\u6210\u529f\u3002\u8bf7\u518d\u70b9\u4e00\u6b21\u3002")
