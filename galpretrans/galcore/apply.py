import shutil
from pathlib import Path

from galcore.errors import ApplyFailed
from galcore.textutil import safe_file_key


def apply_job(root, backup_root, sentences, plugin):
    root = Path(root)
    backup_root = Path(backup_root)
    groups = {}
    for row in sentences:
        groups.setdefault(row["fileKey"], []).append(row)
    backed = []
    changed = []
    buckets = {}
    order = []
    try:
        for file_key, rows in groups.items():
            if not any(row["status"] == "translated" for row in rows):
                continue
            storage = _storage_key(plugin, file_key)
            if storage not in buckets:
                order.append(storage)
                buckets[storage] = []
            buckets[storage].append((file_key, sorted(rows, key=lambda row: row["orderKey"])))
        for storage in order:
            source = root.joinpath(*storage.split("/"))
            backup = backup_root.joinpath(*storage.split("/"))
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, backup)
            backed.append(storage)
            files = buckets[storage]
            if hasattr(plugin, "apply_storage"):
                plugin.apply_storage(root, storage, files)
            else:
                for file_key, rows in files:
                    plugin.apply_file(root, file_key, rows)
            changed.extend(file_key for file_key, _rows in files)
        plugin.verify(root)
        return changed
    except Exception:
        restored = _restore(root, backup_root, backed)
        raise ApplyFailed(restored)


def _storage_key(plugin, file_key):
    method = getattr(plugin, "storage_key", None)
    if method is None:
        return safe_file_key(file_key)
    return safe_file_key(method(file_key))


def _restore(root, backup_root, file_keys):
    try:
        for file_key in file_keys:
            shutil.copy2(
                backup_root.joinpath(*file_key.split("/")),
                root.joinpath(*file_key.split("/")),
            )
        return True
    except Exception:
        return False
