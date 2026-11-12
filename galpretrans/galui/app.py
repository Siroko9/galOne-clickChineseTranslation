import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from galui.setup import runtime_home
from galui.workflow import WorkflowError, one_click_import, one_click_prepare


def main():
    root = tk.Tk()
    root.title("\u624b\u673a Gal \u4e00\u952e\u6c49\u5316")
    root.geometry("720x520")
    settings = _settings_path()
    saved = _load_settings(settings)
    folder = tk.StringVar(value=saved.get("game", ""))

    frame = tk.Frame(root, padx=16, pady=16)
    frame.pack(fill="both", expand=True)
    tk.Label(frame, text="\u6e38\u620f\u6587\u4ef6\u5939", font=("Microsoft YaHei UI", 12)).pack(anchor="w")
    row = tk.Frame(frame)
    row.pack(fill="x", pady=(4, 8))
    entry = tk.Entry(row, textvariable=folder, font=("Microsoft YaHei UI", 11))
    entry.pack(side="left", fill="x", expand=True)
    tk.Button(
        row,
        text="\u9009\u62e9",
        font=("Microsoft YaHei UI", 12),
        command=lambda: _choose(folder, settings),
    ).pack(side="left", padx=(8, 0))
    tk.Label(
        frame,
        text="\u5bfc\u5165\u4f1a\u4fee\u6539\u4e0a\u9762\u8fd9\u4e2a\u6587\u4ef6\u5939\u91cc\u7684\u6e38\u620f\uff0c\u5e76\u5728\u65c1\u8fb9\u7559\u4e0b\u5907\u4efd\u3002",
        font=("Microsoft YaHei UI", 10),
        fg="#555555",
    ).pack(anchor="w", pady=(0, 12))

    buttons = []

    def prepare():
        _start(root, buttons, log, lambda message: one_click_prepare(_require(folder), message))

    def import_pack():
        _start(root, buttons, log, lambda message: one_click_import(_require(folder), message))

    buttons.append(
        tk.Button(
            frame,
            text="\u4e00\u952e\u51c6\u5907\u5e76\u7ffb\u8bd1",
            font=("Microsoft YaHei UI", 16),
            height=2,
            command=prepare,
        )
    )
    buttons.append(
        tk.Button(
            frame,
            text="\u4e00\u952e\u5bfc\u5165",
            font=("Microsoft YaHei UI", 16),
            height=2,
            command=import_pack,
        )
    )
    for button in buttons:
        button.pack(fill="x", pady=4)
    tk.Label(
        frame,
        text="\u628a\u522b\u4eba\u7684 .galpack.json \u653e\u8fdb\u6e38\u620f\u6587\u4ef6\u5939\u91cc\u7684\u300c\u6c49\u5316\u5bfc\u5165\u300d\uff0c\u518d\u70b9\u4e00\u952e\u5bfc\u5165\u3002",
        font=("Microsoft YaHei UI", 10),
        fg="#555555",
    ).pack(anchor="w", pady=(8, 4))
    log = tk.Text(frame, height=14, font=("Microsoft YaHei UI", 10), wrap="word")
    log.pack(fill="both", expand=True, pady=(8, 0))
    log.insert("end", "\u5148\u9009\u6e38\u620f\u6587\u4ef6\u5939\u3002\u8fd9\u4e2a\u6587\u4ef6\u5939\u91cc\u8981\u80fd\u770b\u5230 data.xp3\u3002\n")
    log.configure(state="disabled")
    root.mainloop()


def _require(folder):
    path = folder.get().strip()
    if not path or not Path(path).is_dir():
        raise WorkflowError("\u8bf7\u5148\u9009\u62e9\u6e38\u620f\u6587\u4ef6\u5939\u3002")
    return Path(path)


def _choose(folder, settings):
    path = filedialog.askdirectory()
    if not path:
        return
    folder.set(path)
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps({"game": path}, ensure_ascii=False), encoding="utf-8")


def _start(root, buttons, log, action):
    for button in buttons:
        button.configure(state="disabled")
    events = queue.Queue()

    def work():
        try:
            action(lambda message: events.put(message))
        except WorkflowError as exc:
            events.put(str(exc))
        except Exception as exc:
            events.put(str(exc) or exc.__class__.__name__)
        events.put(None)

    threading.Thread(target=work, daemon=True).start()

    def poll():
        try:
            while True:
                message = events.get_nowait()
                if message is None:
                    for button in buttons:
                        button.configure(state="normal")
                    return
                _append(log, message)
        except queue.Empty:
            pass
        root.after(200, poll)

    root.after(200, poll)


def _append(log, message):
    log.configure(state="normal")
    log.insert("end", message + "\n")
    log.see("end")
    log.configure(state="disabled")


def _settings_path():
    return runtime_home() / "settings.json"


def _load_settings(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


if __name__ == "__main__":
    main()
