import io
import contextlib
import tempfile
import unittest
from pathlib import Path

from galcore.apply import apply_job
from galcore.errors import ApplyFailed, GalError
from galcore.kirikiri import KirikiriPlugin, open_archive, read_bytes, write_archive
from galcore.registry import extract, register, reset

GAME = Path(__file__).resolve().parents[2] / "test" / "SETUP"

SCRIPT = (
    "*start|menu\r\n"
    "@name chara=\"\u592a\u90ce\"\r\n"
    "\u3053\u3093\u306b\u3061\u306f[heart]\r\n"
    "@iscript\r\n"
    "function skip(){ var x = \"\u65e5\u672c\u8a9e\"; }\r\n"
    "@endscript\r\n"
    "@jump storage=a\r\n"
).encode("cp932")
OTHER = "@name chara=\"\u82b1\u5b50\"\r\n\u3042\r\n".encode("cp932")


def archive(path):
    write_archive(
        path,
        [
            ("scenario/a.ks", SCRIPT, True),
            ("scenario/b.ks", OTHER, False),
            ("pict.bin", [b"PNG", b"DATA"], False),
        ],
    )


class KirikiriTest(unittest.TestCase):
    def tearDown(self):
        reset()

    def test_detects_xp3_and_one_child_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            disc = Path(tmp) / "disc"
            archive(disc / "SETUP" / "data.xp3")
            plugin = KirikiriPlugin()
            self.assertTrue(plugin.detect(disc / "SETUP"))
            self.assertTrue(plugin.detect(disc))
            self.assertFalse(plugin.detect(disc / "SETUP" / "data.xp3"))
            (disc / "other").mkdir()
            archive(disc / "other" / "patch.xp3")
            self.assertFalse(plugin.detect(disc))

    def test_startup_tjs_is_a_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "startup.tjs").write_text("function x(){}", encoding="utf-8")
            plugin = KirikiriPlugin()
            self.assertTrue(plugin.detect(root))
            self.assertEqual(plugin.extract(root), [])

    def test_extracts_dialogue_and_keeps_heart_tag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            archive(root / "data.xp3")
            rows = KirikiriPlugin().extract(root)
            self.assertEqual(len(rows), 4)
            texts = [row["sourceText"] for row in rows]
            self.assertEqual(texts[0], "\u592a\u90ce")
            self.assertEqual(texts[1], "\u3053\u3093\u306b\u3061\u306f[heart]")
            self.assertNotIn("\n", texts[1])
            self.assertTrue(all("function" not in row["sourceText"] for row in rows))
            self.assertTrue(all(row["fileKey"].startswith("data.xp3/scenario/") for row in rows))
            self.assertEqual(KirikiriPlugin().control_pattern(), r"\[[^\]\r\n]+\]")

    def test_later_archive_overrides_same_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_archive(root / "data.xp3", [("scenario/a.ks", SCRIPT, True)])
            write_archive(root / "patch.xp3", [("scenario/a.ks", OTHER, True)])
            rows = KirikiriPlugin().extract(root)
            self.assertEqual([row["sourceText"] for row in rows], ["\u82b1\u5b50", "\u3042"])
            self.assertTrue(all(row["fileKey"].startswith("patch.xp3/") for row in rows))

    def test_apply_writes_utf16_and_copies_other_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            archive(root / "data.xp3")
            plugin = KirikiriPlugin()
            rows = plugin.extract(root)
            dialogue = next(row for row in rows if "[heart]" in row["sourceText"])
            dialogue["status"] = "translated"
            dialogue["translatedText"] = "\u4f60\u597d\u6c49[heart]"
            dialogue["origin"] = "import"
            apply_job(root, Path(tmp) / "backup", rows, plugin)
            again = plugin.extract(root)
            updated = next(row for row in again if row["orderKey"] == dialogue["orderKey"])
            self.assertEqual(updated["sourceText"], "\u4f60\u597d\u6c49[heart]")
            handle, entries = open_archive(root / "data.xp3")
            try:
                script = next(entry for entry in entries if entry["name"] == "scenario/a.ks")
                other = next(entry for entry in entries if entry["name"] == "scenario/b.ks")
                image = next(entry for entry in entries if entry["name"] == "pict.bin")
                self.assertTrue(read_bytes(handle, script).startswith(b"\xff\xfe"))
                self.assertFalse(read_bytes(handle, other).startswith(b"\xff\xfe"))
                self.assertEqual(read_bytes(handle, image), b"PNGDATA")
                self.assertEqual(len(image["segments"]), 2)
            finally:
                handle.close()
            plugin.verify(root)

    def test_apply_restores_archive_when_verify_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            archive(root / "data.xp3")
            original = (root / "data.xp3").read_bytes()
            rows = KirikiriPlugin().extract(root)
            rows[1]["status"] = "translated"
            rows[1]["translatedText"] = "\u4f60\u597d"
            rows[1]["origin"] = "import"

            class Boom(KirikiriPlugin):
                def verify(self, root):
                    raise RuntimeError("bad")

            with self.assertRaises(ApplyFailed) as caught:
                apply_job(root, Path(tmp) / "backup", rows, Boom())
            self.assertTrue(caught.exception.restored)
            self.assertEqual((root / "data.xp3").read_bytes(), original)

    def test_bad_archive_is_extract_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data.xp3").write_bytes(b"not-an-xp3-file")
            with self.assertRaises(GalError) as caught:
                KirikiriPlugin().extract(root)
            self.assertEqual(caught.exception.code, "EXTRACT_FAILED")

    def test_unmarked_directory_is_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            register(KirikiriPlugin())
            code, rows = extract(Path(tmp))
            self.assertEqual(code, "ENGINE_UNKNOWN")
            self.assertEqual(rows, [])

    def test_real_game_spot_check(self):
        if not (GAME / "data.xp3").is_file():
            self.skipTest("test game not present")
        plugin = KirikiriPlugin()
        self.assertTrue(plugin.detect(GAME))
        self.assertTrue(plugin.detect(GAME.parent))
        rows = plugin.extract(GAME.parent)
        self.assertGreater(len(rows), 5000)
        heart = [row for row in rows if "[heart]" in row["sourceText"]]
        self.assertGreater(len(heart), 20)
        for row in heart[:20]:
            self.assertGreater(row["sourceText"].count("[heart]"), 0)
            self.assertNotIn("\n", row["sourceText"])
        self.assertEqual(sum("{" in row["sourceText"] for row in rows), 0)
        self.assertEqual(sum("function" in row["sourceText"] for row in rows), 0)
        self.assertEqual(sum(row["fileKey"].endswith(".tjs") for row in rows), 0)
        self.assertTrue(any(row["fileKey"].endswith("scenario/scenario.ks") for row in rows))
        first = [row["sourceHash"] for row in rows]
        second = [row["sourceHash"] for row in plugin.extract(GAME)]
        self.assertEqual(first, second)
        register(plugin)
        code, got = extract(GAME)
        self.assertEqual(code, "OK")
        self.assertEqual([row["sourceHash"] for row in got], second)

    def test_cli_extract_prints_count(self):
        from galpc.__main__ import main

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            archive(root / "data.xp3")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                status = main(["extract", "--root", str(root)])
            self.assertEqual(status, 0)
            self.assertEqual(buf.getvalue().splitlines(), ["OK", "4"])


if __name__ == "__main__":
    unittest.main()
