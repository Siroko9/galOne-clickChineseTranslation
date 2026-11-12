import argparse
import json
from pathlib import Path

from galcore.apply import apply_job
from galcore.errors import ApplyFailed, GalError
from galcore.importer import import_pack
from galcore.job import begin_import, finish_import, keep_source, load_job, move, save_job
from galcore.pack import loads_pack
from galcore.kirikiri import install
from galcore.registry import current


def import_file(job_path, pack_path, overwrite=False):
    job = load_job(job_path)
    pack = loads_pack(Path(pack_path).read_text(encoding="utf-8"))
    plugin = current()
    pattern = None if plugin is None else plugin.control_pattern()
    begin_import(job)
    report = import_pack(
        job["sentences"],
        pack,
        job["engineId"],
        job["extractorVersion"],
        pattern=pattern,
        overwrite=overwrite,
    )
    finish_import(job, report)
    save_job(job_path, job)
    return report


def mark_keep(job_path):
    job = load_job(job_path)
    keep_source(job)
    save_job(job_path, job)
    return job


def confirm(job_path, root, backup):
    job = load_job(job_path)
    plugin = current()
    if plugin is None:
        job["lastError"] = "ENGINE_UNSELECTED"
        save_job(job_path, job)
        return job
    move(job, "confirm_apply")
    try:
        apply_job(root, backup, job["sentences"], plugin)
    except ApplyFailed as exc:
        move(job, "applied")
        job["failureCode"] = exc.code
        move(job, "verify_failed")
        save_job(job_path, job)
        return job
    move(job, "applied")
    move(job, "verified")
    save_job(job_path, job)
    return job


def main(argv=None):
    parser = argparse.ArgumentParser(prog="galphone")
    sub = parser.add_subparsers(dest="cmd", required=True)

    imp = sub.add_parser("import")
    imp.add_argument("--job", required=True)
    imp.add_argument("--pack", required=True)
    imp.add_argument("--overwrite", action="store_true")

    keep = sub.add_parser("keep-source")
    keep.add_argument("--job", required=True)

    apply = sub.add_parser("apply")
    apply.add_argument("--job", required=True)
    apply.add_argument("--root", required=True)
    apply.add_argument("--backup", required=True)

    args = parser.parse_args(argv)
    install()
    try:
        if args.cmd == "import":
            report = import_file(args.job, args.pack, args.overwrite)
            print(json.dumps({k: v for k, v in report.items() if k != "sentences"}, ensure_ascii=False))
        elif args.cmd == "keep-source":
            job = mark_keep(args.job)
            print(job["state"])
        else:
            job = confirm(args.job, args.root, args.backup)
            print(job["state"])
            if job.get("failureCode"):
                print(job["failureCode"])
    except GalError as exc:
        print(exc.code)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
