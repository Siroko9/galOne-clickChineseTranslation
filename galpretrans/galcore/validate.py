import re
from collections import Counter

REFUSAL_PREFIXES = (
    "\u65e0\u6cd5\u7ffb\u8bd1",
    "\u65e0\u6cd5\u534f\u52a9",
    "\u6211\u4e0d\u80fd",
    "I cannot",
    "I am sorry",
)


def split_output(text):
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if text.endswith("\n"):
        text = text[:-1]
    return text.split("\n")


def is_batch_refusal(text):
    stripped = text.strip()
    if len(stripped) >= 15:
        return False
    return any(stripped.startswith(prefix) for prefix in REFUSAL_PREFIXES)


def control_counts(text, pattern):
    if pattern is None or text is None:
        return Counter()
    if isinstance(pattern, str):
        pattern = re.compile(pattern)
    return Counter(pattern.findall(text))


def batch_problem(sources, outputs, pattern):
    if is_batch_refusal("\n".join(outputs)):
        return "refusal"
    if len(sources) != len(outputs):
        return "count"
    for source, output in zip(sources, outputs):
        if output == "":
            return "empty"
        if pattern is not None and control_counts(source, pattern) != control_counts(output, pattern):
            return "control"
    return None
