_plugin = None


def register(plugin):
    global _plugin
    if _plugin is not None:
        raise RuntimeError("v1 registers one engine plugin")
    _plugin = plugin


def reset():
    global _plugin
    _plugin = None


def current():
    return _plugin


def detect(root):
    plugin = current()
    if plugin is None:
        return "ENGINE_UNSELECTED", None
    if plugin.detect(root):
        return "HIT", plugin
    return "ENGINE_UNKNOWN", None


def extract(root):
    code, plugin = detect(root)
    if code != "HIT":
        return code, []
    sentences = plugin.extract(root)
    if not sentences:
        return "EXTRACT_FAILED", []
    return "OK", sentences
