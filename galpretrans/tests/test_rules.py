import json
import tempfile
import unittest
from pathlib import Path

from galcore.apply import apply_job
from galcore.errors import ApplyFailed, IllegalTransition
from galcore.glossary import GlossaryError, load_glossary
from galcore.importer import import_pack
from galcore.job import begin_import, finish_import, keep_source, new_job
from galcore.llama import InferenceFailed
from galcore.machine import transition
from galcore.pack import export_pack, loads_pack, dumps_pack
from galcore.prompt import SYSTEM_PROMPT, build_user
from galcore.registry import extract, register, reset
from galcore.sentences import make_sentence
from galcore.textutil import source_hash
from galcore.translate import has_pending, translate_job
from galphone.__main__ import import_file


class Scripted:
    def __init__(self, answers):
        self.answers = list(answers)

    def complete(self, system, user):
        item = self.answers.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def sentence(text, order=0, file_key="lines.txt"):
    return make_sentence("yuris", file_key, order, text)


class RulesTest(unittest.TestCase):
    def tearDown(self):
        reset()

    def test_source_hash_ignores_model(self):
        row = sentence("\u3042")
        self.assertEqual(row["sourceHash"], source_hash(row["sourceText"]))
        self.assertNotIn("\n", row["sourceText"])

    def test_newline_roundtrip(self):
        row = sentence("a\nb")
        self.assertEqual(row["sourceText"], "a\\nb")

    def test_prompt_keeps_empty_history_label(self):
        user = build_user([], "", ["\u3042"])
        self.assertIn("\u5386\u53f2\u7ffb\u8bd1\uff1a", user)
        self.assertIn("\u672f\u8bed\u8868", user)
        self.assertTrue(SYSTEM_PROMPT.startswith("\u4f60\u662f\u4e00\u4e2a"))

    def test_glossary_rejects_split_meaning(self):
        with self.assertRaises(GlossaryError):
            load_glossary("name->a/b")

    def test_state_table(self):
        state = "created"
        state = transition(state, "path_resolved")
        state = transition(state, "unselected")
        self.assertEqual(state, "failed")
        with self.assertRaises(IllegalTransition):
            transition("done", "path_resolved")
        with self.assertRaises(IllegalTransition):
            transition("translating", "start_import")

    def test_import_hit_and_leave_pending(self):
        rows = [sentence("one", 0), sentence("two", 1)]
        pack = {
            "format": 1,
            "engineId": "yuris",
            "extractorVersion": "1",
            "entries": [
                {"sourceText": rows[0]["sourceText"], "translatedText": "\u4e00", "sourceHash": rows[0]["sourceHash"]}
            ],
        }
        job = new_job("yuris", "1", rows)
        begin_import(job)
        report = import_pack(job["sentences"], pack, "yuris", "1")
        finish_import(job, report)
        self.assertEqual(report["hits"], 1)
        self.assertEqual(job["state"], "ready_to_translate")
        self.assertEqual(job["sentences"][0]["origin"], "import")
        self.assertEqual(job["sentences"][1]["status"], "pending")

    def test_import_rejects_wrong_engine_without_writes(self):
        rows = [sentence("one")]
        pack = {"format": 1, "engineId": "cs2", "extractorVersion": "1", "entries": []}
        before = json.dumps(rows)
        report = import_pack(rows, pack, "yuris", "1")
        self.assertEqual(report["error"], "IMPORT_ENGINE_MISMATCH")
        self.assertEqual(json.dumps(rows), before)

    def test_import_ambiguous_is_not_a_hit(self):
        rows = [sentence("one")]
        pack = {
            "format": 1,
            "engineId": "yuris",
            "extractorVersion": "1",
            "entries": [
                {"sourceText": "one", "translatedText": "\u7532"},
                {"sourceText": "one", "translatedText": "\u4e59"},
            ],
        }
        report = import_pack(rows, pack, "yuris", "1")
        self.assertEqual(report["error"], "IMPORT_NO_MATCH")
        self.assertEqual(rows[0]["status"], "pending")

    def test_import_control_mismatch_rejected(self):
        rows = [sentence("name <r> line")]
        pack = {
            "format": 1,
            "engineId": "yuris",
            "extractorVersion": "1",
            "entries": [{"sourceText": "name <r> line", "translatedText": "\u540d\u5b57"}],
        }
        report = import_pack(rows, pack, "yuris", "1", pattern=r"<[^>]+>")
        self.assertEqual(report["error"], "IMPORT_NO_MATCH")
        self.assertEqual(report["rejected"], 1)

    def test_translate_then_export_then_import(self):
        rows = [sentence("alpha", 0), sentence("beta", 1)]
        job = new_job("yuris", "1", rows)
        client = Scripted(["\u7532\n\u4e59\n"])
        translate_job(job, client, "", 0, "test-model", batch_size=8)
        self.assertFalse(has_pending(job))
        self.assertEqual(job["sentences"][0]["origin"], "model")
        pack = loads_pack(dumps_pack(export_pack("yuris", "1", job["sentences"])))
        fresh = new_job("yuris", "1", [sentence("alpha", 0), sentence("beta", 1)])
        report = import_pack(fresh["sentences"], pack, "yuris", "1")
        self.assertEqual(report["hits"], 2)
        self.assertEqual(report["sentences"][1]["translatedText"], "\u4e59")

    def test_invalid_output_marks_batch_and_keeps_retry(self):
        rows = [sentence("alpha", 0), sentence("beta", 1)]
        job = new_job("yuris", "1", rows)
        client = Scripted(["only-one", "still-one"])
        translate_job(job, client, "", 0, "test-model", batch_size=8)
        self.assertEqual(job["lastError"], "OUTPUT_INVALID")
        self.assertTrue(all(row["status"] == "failed" for row in job["sentences"]))
        self.assertEqual(len(client.answers), 0)

    def test_inference_failure_leaves_pending(self):
        rows = [sentence("alpha")]
        job = new_job("yuris", "1", rows)
        translate_job(job, Scripted([InferenceFailed("down")]), "", 0, "m", batch_size=8)
        self.assertEqual(job["lastError"], "INFERENCE_FAILED")
        self.assertEqual(rows[0]["status"], "pending")

    def test_apply_restores_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            backup = Path(tmp) / "backup"
            root.mkdir()
            original = "one\ntwo\n"
            (root / "lines.txt").write_text(original, encoding="utf-8")
            rows = [sentence("one", 0), sentence("two", 1)]
            rows[0]["status"] = "translated"
            rows[0]["translatedText"] = "\u4e00"
            rows[0]["origin"] = "import"

            class Boom:
                def apply_file(self, root, file_key, ordered):
                    path = root.joinpath(*file_key.split("/"))
                    path.write_text("changed\n", encoding="utf-8")

                def verify(self, root):
                    raise RuntimeError("bad")

            with self.assertRaises(ApplyFailed) as caught:
                apply_job(root, backup, rows, Boom())
            self.assertTrue(caught.exception.restored)
            self.assertEqual((root / "lines.txt").read_text(encoding="utf-8"), original)

    def test_phone_import_command_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            job_path = Path(tmp) / "job.json"
            pack_path = Path(tmp) / "out.galpack.json"
            rows = [sentence("alpha")]
            from galcore.job import save_job

            save_job(job_path, new_job("yuris", "1", rows))
            translated = new_job("yuris", "1", [dict(rows[0], status="translated", origin="model", translatedText="\u7532")])
            pack_path.write_text(dumps_pack(export_pack("yuris", "1", translated["sentences"])), encoding="utf-8")
            report = import_file(job_path, pack_path)
            self.assertEqual(report["hits"], 1)
            saved = json.loads(job_path.read_text(encoding="utf-8"))
            self.assertEqual(saved["state"], "ready_to_apply")

    def test_keep_source_then_ready(self):
        job = new_job("yuris", "1", [sentence("alpha"), sentence("beta")])
        job["sentences"][0]["status"] = "translated"
        job["sentences"][0]["translatedText"] = "\u7532"
        job["sentences"][0]["origin"] = "import"
        keep_source(job)
        self.assertEqual(job["state"], "ready_to_apply")
        self.assertEqual(job["sentences"][1]["failureCode"], "KEEP_SOURCE")

    def test_extract_without_plugin(self):
        code, rows = extract(Path("."))
        self.assertEqual(code, "ENGINE_UNSELECTED")
        self.assertEqual(rows, [])

    def test_second_plugin_rejected(self):
        register(object())
        with self.assertRaises(RuntimeError):
            register(object())


if __name__ == "__main__":
    unittest.main()
