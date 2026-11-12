import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from galcore.kirikiri import KirikiriPlugin, write_archive
from galcore.pack import dumps_pack, export_pack
from galcore.registry import reset
from galui.setup import download_file, native_path, pick_asset, pick_cudart
from galui.workflow import WorkflowError, one_click_import, one_click_prepare

SCRIPT = (
    "*start|menu\r\n"
    "@name chara=\"\u592a\u90ce\"\r\n"
    "\u3053\u3093\u306b\u3061\u306f[heart]\r\n"
    "@iscript\r\n"
    "function skip(){ var x = \"\u65e5\u672c\u8a9e\"; }\r\n"
    "@endscript\r\n"
).encode("cp932")


class Scripted:
    def __init__(self, answers):
        self.answers = list(answers)
        self.calls = 0

    def complete(self, system, user):
        self.calls += 1
        return self.answers.pop(0)


class OneClickTest(unittest.TestCase):
    def tearDown(self):
        reset()

    def test_pick_cuda_12_before_newer_cuda_and_ignores_runtime_zip(self):
        releases = [
            {
                "assets": [
                    {"name": "llama-b1-bin-win-cuda-13.5-x64.zip", "browser_download_url": "http://cuda13"},
                    {"name": "cudart-llama-bin-win-cuda-12.4-x64.zip", "browser_download_url": "http://runtime"},
                    {"name": "llama-b1-bin-win-cuda-12.4-x64.zip", "browser_download_url": "http://cuda12"},
                    {"name": "llama-b1-bin-win-vulkan-x64.zip", "browser_download_url": "http://vk"},
                ]
            },
            {"assets": [{"name": "llama-b2-bin-win-cpu-x64.zip", "browser_download_url": "http://cpu"}]},
        ]
        self.assertEqual(pick_asset(releases, "cuda")["browser_download_url"], "http://cuda12")
        self.assertEqual(pick_asset(releases, "vulkan")["browser_download_url"], "http://vk")
        self.assertEqual(pick_asset([{"assets": []}, releases[1]], "cuda")["browser_download_url"], "http://cpu")
        cudart = pick_cudart(
            [{"assets": [{"name": "cudart-llama-bin-win-cuda-12.4-x64.zip", "browser_download_url": "http://rt"}]}],
            "bin-win-cuda-12.4-x64.zip",
        )
        self.assertEqual(cudart["browser_download_url"], "http://rt")

    def test_native_path_matches_realpath(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "file.txt"
            path.write_text("x", encoding="utf-8")
            self.assertEqual(native_path(path), path.resolve())

    def test_download_resumes(self):
        payload = b"abcdefghijklmnopqrstuvwxyz"

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                header = self.headers.get("Range")
                if header:
                    start = int(header.split("=")[1].split("-")[0])
                    body = payload[start:]
                    self.send_response(206)
                else:
                    body = payload
                    self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, fmt, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                dest = Path(tmp) / "file.bin"
                part = dest.with_name(dest.name + ".part")
                part.write_bytes(payload[:4])
                download_file("http://127.0.0.1:%d/file" % server.server_address[1], dest, exact=len(payload))
                self.assertEqual(dest.read_bytes(), payload)
                download_file("http://127.0.0.1:%d/file" % server.server_address[1], dest, exact=len(payload))
                self.assertEqual(dest.read_bytes(), payload)
        finally:
            server.shutdown()
            server.server_close()

    def test_prepare_writes_pack_and_second_click_does_not_translate_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            write_archive(root / "data.xp3", [("scenario/a.ks", SCRIPT, True)])
            client = Scripted(["\u7532\n\u4e59[heart]\n"])
            notes = []
            one_click_prepare(root, notes.append, client=client, skip_setup=True)
            self.assertEqual(client.calls, 1)
            pack = root / "\u6c49\u5316\u5bfc\u5165" / "\u7ffb\u8bd1\u7ed3\u679c.galpack.json"
            self.assertTrue(pack.is_file())
            one_click_prepare(root, notes.append, client=client, skip_setup=True)
            self.assertEqual(client.calls, 1)
            one_click_import(root, notes.append)
            texts = [row["sourceText"] for row in KirikiriPlugin().extract(root)]
            self.assertIn("\u4e59[heart]", texts)
            self.assertIn("\u7532", texts)

    def test_import_writes_chinese_and_keeps_unmatched_japanese(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            write_archive(root / "data.xp3", [("scenario/a.ks", SCRIPT, True)])
            plugin = KirikiriPlugin()
            rows = plugin.extract(root)
            dialogue = next(row for row in rows if "[heart]" in row["sourceText"])
            dialogue["status"] = "translated"
            dialogue["translatedText"] = "\u4f60\u597d\u6c49[heart]"
            folder = root / "\u6c49\u5316\u5bfc\u5165"
            folder.mkdir()
            (folder / "given.galpack.json").write_text(
                dumps_pack(export_pack("kirikiri", "1", rows)),
                encoding="utf-8",
            )
            notes = []
            one_click_import(root, notes.append)
            texts = [row["sourceText"] for row in plugin.extract(root)]
            self.assertIn("\u4f60\u597d\u6c49[heart]", texts)
            self.assertIn("\u592a\u90ce", texts)
            self.assertTrue((Path(tmp) / "game-backup" / "data.xp3").is_file())

    def test_import_without_pack_leaves_the_game_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "game"
            write_archive(root / "data.xp3", [("scenario/a.ks", SCRIPT, True)])
            before = (root / "data.xp3").read_bytes()
            with self.assertRaises(WorkflowError):
                one_click_import(root, lambda message: None)
            self.assertEqual((root / "data.xp3").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
