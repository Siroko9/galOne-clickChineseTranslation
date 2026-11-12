import argparse
import json
from pathlib import Path

from galcore.errors import GalError
from galcore.glossary import load_glossary
from galcore.job import load_job, move, new_job, save_job
from galcore.llama import LlamaClient
from galcore.pack import dumps_pack, export_pack
from galcore.kirikiri import install
from galcore.registry import current, extract
from galcore.sentences import make_sentence
from galcore.translate import has_pending, translate_job


def init_job(path, engine_id, extractor_version, sentences_path):
    raw = json.loads(Path(sentences_path).read_text(encoding="utf-8"))
    sentences = [
        make_sentence(engine_id, item["fileKey"], item["orderKey"], item["sourceText"])
        for item in raw
    ]
    save_job(path, new_job(engine_id, extractor_version, sentences))


def run_translate(job_path, endpoint, model_id, glossary_path, batch_size):
    job = load_job(job_path)
    if job["state"] == "ready_to_translate":
        move(job, "start_translate")
    elif job["state"] == "paused":
        move(job, "resume")
    elif job["state"] != "translating":
        raise GalError("ILLEGAL_TRANSITION", job["state"])
    glossary_body, glossary_version = ("", 0)
    if glossary_path:
        glossary_body, glossary_version = load_glossary(Path(glossary_path).read_text(encoding="utf-8"))
    plugin = current()
    pattern = None if plugin is None else plugin.control_pattern()
    client = LlamaClient(endpoint, model_id)
    translate_job(job, client, glossary_body, glossary_version, model_id, pattern, batch_size)
    if not has_pending(job):
        move(job, "no_pending")
    elif job.get("lastError") == "INFERENCE_FAILED":
        move(job, "pause")
    save_job(job_path, job)
    return job


def export_job(job_path, out_path):
    job = load_job(job_path)
    pack = export_pack(job["engineId"], job["extractorVersion"], job["sentences"])
    Path(out_path).write_text(dumps_pack(pack), encoding="utf-8")
    return pack


def extract_root(root):
    return extract(root)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="galpc")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init")
    init.add_argument("--job", required=True)
    init.add_argument("--engine", required=True)
    init.add_argument("--extractor-version", required=True)
    init.add_argument("--sentences", required=True)

    trans = sub.add_parser("translate")
    trans.add_argument("--job", required=True)
    trans.add_argument("--endpoint", default="http://127.0.0.1:8080")
    trans.add_argument("--model-id", required=True)
    trans.add_argument("--glossary")
    trans.add_argument("--batch-size", type=int, default=8)

    exp = sub.add_parser("export")
    exp.add_argument("--job", required=True)
    exp.add_argument("--out", required=True)

    ext = sub.add_parser("extract")
    ext.add_argument("--root", required=True)
    ext.add_argument("--job")

    args = parser.parse_args(argv)
    install()
    try:
        if args.cmd == "init":
            init_job(args.job, args.engine, args.extractor_version, args.sentences)
            print(args.job)
        elif args.cmd == "translate":
            job = run_translate(args.job, args.endpoint, args.model_id, args.glossary, args.batch_size)
            print(job["state"])
            if job.get("lastError"):
                print(job["lastError"])
        elif args.cmd == "export":
            pack = export_job(args.job, args.out)
            print(len(pack["entries"]))
        else:
            code, sentences = extract_root(Path(args.root))
            print(code)
            print(len(sentences))
            if args.job and code == "OK":
                plugin = current()
                save_job(
                    args.job,
                    new_job(plugin.engine_id, plugin.extractor_version, sentences),
                )
                print(args.job)
    except GalError as exc:
        print(exc.code)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
