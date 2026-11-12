import json
import urllib.error
import urllib.request


class InferenceFailed(Exception):
    pass


class LlamaClient:
    def __init__(self, endpoint, model_id, timeout=120):
        self.endpoint = endpoint.rstrip("/")
        self.model_id = model_id
        self.timeout = timeout

    def complete(self, system, user):
        url = self.endpoint + "/v1/chat/completions"
        body = {
            "model": self.model_id,
            "temperature": 0.3,
            "top_p": 0.8,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise InferenceFailed(str(exc))
        try:
            return payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise InferenceFailed("missing completion") from exc
