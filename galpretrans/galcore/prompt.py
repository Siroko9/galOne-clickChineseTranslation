from galcore.textutil import estimate_tokens

SYSTEM_PROMPT = (
    "\u4f60\u662f\u4e00\u4e2a\u89c6\u89c9\u5c0f\u8bf4\u7ffb\u8bd1\u6a21\u578b\uff0c"
    "\u53ef\u4ee5\u901a\u987a\u5730\u4f7f\u7528\u7ed9\u5b9a\u7684\u672f\u8bed\u8868"
    "\u4ee5\u6307\u5b9a\u7684\u98ce\u683c\u5c06\u65e5\u6587\u7ffb\u8bd1\u6210\u7b80\u4f53\u4e2d\u6587\uff0c"
    "\u5e76\u8054\u7cfb\u4e0a\u4e0b\u6587\u6b63\u786e\u4f7f\u7528\u4eba\u79f0\u4ee3\u8bcd\uff0c"
    "\u6ce8\u610f\u4e0d\u8981\u6df7\u6dc6\u4f7f\u5f79\u6001\u548c\u88ab\u52a8\u6001\u7684\u4e3b\u8bed\u548c\u5bbe\u8bed\uff0c"
    "\u4e0d\u8981\u64c5\u81ea\u6dfb\u52a0\u539f\u6587\u4e2d\u6ca1\u6709\u7684\u7279\u6b8a\u7b26\u53f7\uff0c"
    "\u4e5f\u4e0d\u8981\u64c5\u81ea\u589e\u52a0\u6216\u51cf\u5c11\u6362\u884c\u3002"
)

_HISTORY = "\u5386\u53f2\u7ffb\u8bd1\uff1a"
_GLOSSARY = (
    "\u53c2\u8003\u4ee5\u4e0b\u672f\u8bed\u8868\uff08\u53ef\u4e3a\u7a7a\uff0c"
    "\u683c\u5f0f\u4e3asrc->dst #\u5907\u6ce8\uff09\uff1a"
)
_ASK = (
    "\u6839\u636e\u4ee5\u4e0a\u672f\u8bed\u8868\u7684\u5bf9\u5e94\u5173\u7cfb\u548c\u5907\u6ce8\uff0c"
    "\u7ed3\u5408\u5386\u53f2\u5267\u60c5\u548c\u4e0a\u4e0b\u6587\uff0c"
    "\u5c06\u4e0b\u9762\u7684\u6587\u672c\u4ece\u65e5\u6587\u7ffb\u8bd1\u6210\u7b80\u4f53\u4e2d\u6587\uff1a"
)
CONTEXT_LIMIT = 2048


def build_user(history, glossary_body, sources):
    if history:
        history_block = _HISTORY + history[0]
        if len(history) > 1:
            history_block += "\n" + "\n".join(history[1:])
    else:
        history_block = _HISTORY
    glossary_block = _GLOSSARY
    if glossary_body:
        glossary_block += "\n" + glossary_body
    return "\n\n".join(
        (history_block, glossary_block, _ASK + "\n" + "\n".join(sources))
    )


def fit_history(history, glossary_body, sources):
    kept = list(history)
    while kept and estimate_tokens(build_user(kept, glossary_body, sources)) > CONTEXT_LIMIT:
        kept.pop(0)
    return kept
