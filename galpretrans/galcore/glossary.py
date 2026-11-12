import hashlib

from galcore.errors import GlossaryError


def load_glossary(text):
    items = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "->" not in line:
            raise GlossaryError("glossary line needs src->dst")
        src, right = line.split("->", 1)
        comment = ""
        if " #" in right:
            dst, comment = right.split(" #", 1)
        else:
            dst = right
        src = src.strip()
        dst = dst.strip()
        if not src or not dst:
            raise GlossaryError("empty glossary term")
        if "/" in dst:
            raise GlossaryError("one term cannot map to a/b")
        item = "%s->%s" % (src, dst)
        if comment.strip():
            item += " #%s" % comment.strip()
        items.append(item)
    body = "\n".join(items)
    if not body:
        return body, 0
    version = int(hashlib.sha256(body.encode("utf-8")).hexdigest()[:8], 16)
    return body, version
