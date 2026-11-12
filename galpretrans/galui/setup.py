import json
import os
import shutil
import subprocess
import urllib.request
import zipfile
from pathlib import Path

MODEL_ID = "Galtransl-v4-4B-2601-Q5_K_S"
MODEL_URL = (
    "https://huggingface.co/SakuraLLM/GalTransl-v4-4B-2601/resolve/main/"
    "Galtransl-v4-4B-2601-Q5_K_S.gguf"
)
MODEL_BYTES = 2823707232
RELEASES_URL = "https://api.github.com/repos/ggml-org/llama.cpp/releases?per_page=20"
_KIND_SUFFIXES = {
    "cuda": (
        "bin-win-cuda-12.4-x64.zip",
        "bin-win-cuda-13.5-x64.zip",
        "bin-win-cuda-13.3-x64.zip",
    ),
    "vulkan": ("bin-win-vulkan-x64.zip",),
    "cpu": ("bin-win-cpu-x64.zip",),
}


class SetupError(Exception):
    pass


def runtime_home():
    # Store Python maps LOCALAPPDATA onto C:. Keep the model and engine on the
    # project drive instead, beside this repository.
    return Path(__file__).resolve().parents[2] / "runtime"


def detect_kind():
    try:
        subprocess.run(
            ["nvidia-smi"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=8,
            check=True,
        )
        return "cuda"
    except (OSError, subprocess.SubprocessError):
        return "vulkan"


def pick_cudart(releases, suffix):
    for release in releases:
        for asset in release.get("assets") or []:
            filename = asset.get("name") or ""
            if "cudart" in filename and filename.endswith(suffix):
                return asset
    return None


def pick_asset(releases, kind):
    order = [kind]
    if kind != "cpu":
        order.append("cpu")
    for name in order:
        for suffix in _KIND_SUFFIXES[name]:
            for release in releases:
                for asset in release.get("assets") or []:
                    filename = asset.get("name") or ""
                    if filename.startswith("llama-") and filename.endswith(suffix):
                        return asset
    return None


def _percent_log(log, label):
    seen = {"value": -1}

    def progress(done, total):
        if not total:
            return
        percent = int(done * 100 / total)
        if percent // 5 != seen["value"]:
            seen["value"] = percent // 5
            log("%s %d%%" % (label, percent))

    return progress


def download_file(url, dest, progress=None, exact=None):
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if exact is not None and dest.is_file() and dest.stat().st_size == exact:
        return dest
    part = dest.with_name(dest.name + ".part")
    done = part.stat().st_size if part.is_file() else 0
    request = urllib.request.Request(url, headers={"User-Agent": "galpretrans"})
    if done:
        request.add_header("Range", "bytes=%d-" % done)
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except Exception as exc:
        raise SetupError("download failed") from exc
    status = getattr(response, "status", 200)
    if status == 200 and done:
        done = 0
    elif status not in (200, 206):
        response.close()
        raise SetupError("download failed")
    length = response.headers.get("Content-Length")
    total = done + int(length) if length and length.isdigit() else None
    mode = "ab" if status == 206 else "wb"
    try:
        with response, open(part, mode) as handle:
            while True:
                chunk = response.read(256 * 1024)
                if not chunk:
                    break
                handle.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except Exception as exc:
        raise SetupError("download failed") from exc
    if exact is not None and part.stat().st_size != exact:
        part.unlink(missing_ok=True)
        raise SetupError("download incomplete")
    os.replace(part, dest)
    return dest


def llama_server_path(home=None):
    home = Path(home or runtime_home())
    direct = home / "llama" / "llama-server.exe"
    if direct.is_file():
        return direct
    found = sorted(home.glob("llama/**/llama-server.exe"))
    return found[0] if found else None


def model_path(home=None):
    return Path(home or runtime_home()) / "models" / (MODEL_ID + ".gguf")


def ensure_runtime(log, home=None, kind=None, opener=None):
    home = Path(home or runtime_home())
    kind = kind or detect_kind()
    server = llama_server_path(home)
    if server is None or not (server.parent / "llama-server-impl.dll").is_file():
        log("\u6b63\u5728\u4e0b\u8f7d\u7ffb\u8bd1\u5f15\u64ce")
        server = _install_llama(home, kind, log, opener)
    else:
        log("\u7ffb\u8bd1\u5f15\u64ce\u5df2\u5c31\u7eea")
    _ensure_cuda_runtime(server.parent, log, opener)
    path = model_path(home)
    if path.is_file() and path.stat().st_size == MODEL_BYTES:
        log("\u7ffb\u8bd1\u6a21\u578b\u5df2\u5c31\u7eea")
    else:
        log("\u6b63\u5728\u4e0b\u8f7d\u7ffb\u8bd1\u6a21\u578b\uff08\u7ea6 2.8 GB\uff09")
        download_file(MODEL_URL, path, _percent_log(log, "\u6a21\u578b"), exact=MODEL_BYTES)
        log("\u7ffb\u8bd1\u6a21\u578b\u5df2\u5c31\u7eea")
    return server, path


def _install_llama(home, kind, log, opener):
    fetch = opener or _read_json
    releases = fetch(RELEASES_URL)
    asset = pick_asset(releases, kind)
    if asset is None:
        raise SetupError("\u627e\u4e0d\u5230 Windows \u7248\u7ffb\u8bd1\u5f15\u64ce")
    archive = home / "llama.zip"
    download_file(asset["browser_download_url"], archive, exact=asset.get("size"))
    target = home / "llama"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    with zipfile.ZipFile(archive) as packed:
        for info in packed.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise SetupError("unsafe llama package")
        packed.extractall(target)
    archive.unlink(missing_ok=True)
    _unblock(target)
    server = llama_server_path(home)
    if server is None:
        raise SetupError("\u7ffb\u8bd1\u5f15\u64ce\u538b\u7f29\u5305\u91cc\u6ca1\u6709 llama-server.exe")
    log("\u7ffb\u8bd1\u5f15\u64ce\u5df2\u5c31\u7eea")
    return server


def _read_json(url):
    request = urllib.request.Request(url, headers={"User-Agent": "galpretrans"})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def server_ready():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080/health", timeout=2) as response:
            return response.status == 200
    except Exception:
        return False


def native_path(path):
    # Store Python hides LocalAppData. The server process is outside that
    # sandbox, so it must be started with the real file path.
    return Path(os.path.realpath(path))


def start_server(server, model, kind, home=None):
    if server_ready():
        return None
    server = native_path(server)
    model = native_path(model)
    if not (server.parent / "llama-server-impl.dll").is_file():
        raise SetupError("\u627e\u4e0d\u5230 llama-server-impl.dll\u3002\u8bf7\u518d\u70b9\u4e00\u6b21\uff0c\u7a0b\u5e8f\u4f1a\u91cd\u65b0\u4e0b\u8f7d\u7ffb\u8bd1\u5f15\u64ce\u3002")
    home = Path(home or runtime_home())
    home.mkdir(parents=True, exist_ok=True)
    log_path = home / "llama-server.log"
    handle = open(log_path, "ab")
    command = [
        str(server),
        "-m",
        str(model),
        "-c",
        "2048",
        "--host",
        "127.0.0.1",
        "--port",
        "8080",
    ]
    if kind != "cpu":
        command.extend(["-ngl", "99"])
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    env = os.environ.copy()
    env["PATH"] = str(server.parent) + os.pathsep + env.get("PATH", "")
    process = subprocess.Popen(
        command,
        stdout=handle,
        stderr=subprocess.STDOUT,
        cwd=str(server.parent),
        env=env,
        creationflags=flags,
    )
    return process


def _ensure_cuda_runtime(folder, log, opener):
    folder = Path(folder)
    if not (folder / "ggml-cuda.dll").is_file() or any(folder.glob("cudart64_*.dll")):
        return
    suffix = _cuda_suffix(folder)
    if suffix is None:
        return
    fetch = opener or _read_json
    asset = pick_cudart(fetch(RELEASES_URL), suffix)
    if asset is None:
        raise SetupError("\u627e\u4e0d\u5230\u663e\u5361\u8fd0\u884c\u5e93")
    log("\u6b63\u5728\u4e0b\u8f7d\u663e\u5361\u8fd0\u884c\u5e93")
    archive = folder.parent / "cudart.zip"
    download_file(asset["browser_download_url"], archive, _percent_log(log, "\u663e\u5361\u5e93"), exact=asset.get("size"))
    _extract_zip(archive, folder)
    archive.unlink(missing_ok=True)
    _unblock(folder)


def _cuda_suffix(folder):
    path = Path(folder) / "ggml-cuda.dll"
    needles = (
        (b"cudart64_12.dll", "bin-win-cuda-12.4-x64.zip"),
        (b"cudart64_13.dll", "bin-win-cuda-13.5-x64.zip"),
    )
    with path.open("rb") as handle:
        previous = b""
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                return None
            data = previous + chunk
            for needle, suffix in needles:
                if needle in data:
                    return suffix
            previous = data[-32:]


def _extract_zip(archive, target):
    with zipfile.ZipFile(archive) as packed:
        for info in packed.infolist():
            name = info.filename.replace("\\", "/")
            if name.startswith("/") or ".." in name.split("/"):
                raise SetupError("unsafe llama package")
        packed.extractall(target)


def _unblock(folder):
    for path in Path(folder).rglob("*"):
        if not path.is_file():
            continue
        try:
            os.remove(str(path) + ":Zone.Identifier")
        except OSError:
            pass
