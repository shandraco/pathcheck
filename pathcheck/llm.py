"""Meterless Runtime (Nightshift) as the primary AI provider.

Follows the Meterless "Add Meterless as a provider" contract: OpenAI-compatible,
Bearer token, `meterless-app` header on every call, `meterless-scope: user` on chat,
status decided by GET /v1/models. Every call is logged with the model that served it.

Replay: real replies are recorded to samples/replay.json keyed by a prompt hash, so
SAMPLE_MODE can show the same run without Nightshift.
"""
import hashlib
import json
import re
import threading
import urllib.error
import urllib.request
from urllib.parse import urlparse

from . import config

REPLAY_PATH = config.ROOT / "samples" / "replay.json"
_lock = threading.Lock()


class LLMError(Exception):
    pass


def normalize_base_url(raw: str) -> str:
    """Accept host, host:port, /v1, /v1/chat/completions, /v1/models or /healthz; return <origin>/v1."""
    raw = (raw or "").strip()
    if "://" not in raw:
        raw = "http://" + raw
    u = urlparse(raw)
    return f"{u.scheme}://{u.netloc}/v1"


def _key(messages, lane) -> str:
    return hashlib.sha256(json.dumps([lane, messages], sort_keys=True).encode()).hexdigest()[:24]


def _load_replay() -> dict:
    try:
        return json.loads(REPLAY_PATH.read_text())
    except (OSError, ValueError):
        return {}


class MeterlessClient:
    def __init__(self, base_url=None, token=None, sample_mode=None, record=True):
        self.base = normalize_base_url(base_url or config.METERLESS_BASE_URL)
        self.token = token if token is not None else config.METERLESS_RUNTIME_TOKEN
        self.sample_mode = (config.SAMPLE_MODE and not config.LLM_LIVE) if sample_mode is None else sample_mode
        self.record = record
        self.replay = _load_replay()

    def _req(self, path, body=None, chat=False, timeout=180):
        headers = {"Authorization": f"Bearer {self.token}", "meterless-app": config.METERLESS_APP_ID,
                   "Content-Type": "application/json"}
        if chat:
            headers["meterless-scope"] = "user"
        req = urllib.request.Request(self.base + path, headers=headers, method="POST" if body else "GET",
                                     data=json.dumps(body).encode() if body else None)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode())

    def status(self) -> dict:
        """online / unauthorized / offline, per the Meterless contract."""
        if self.sample_mode:
            return {"state": "sample", "models": []}
        try:
            data = self._req("/models", timeout=5)
            ids = [m.get("id") for m in data.get("data", [])]
            return {"state": "online", "models": ids}
        except urllib.error.HTTPError as e:
            return {"state": "unauthorized" if e.code in (401, 403) else "offline", "models": []}
        except (urllib.error.URLError, OSError, ValueError):
            return {"state": "offline", "models": []}

    def chat(self, messages, lane, temperature=0.2, max_tokens=1200) -> dict:
        """Returns {"text", "model", "lane", "source"}; source is nightshift or replay."""
        k = _key(messages, lane)
        if self.sample_mode:
            if k in self.replay:
                hit = self.replay[k]
                return {"text": hit["text"], "model": hit["model"], "lane": lane, "source": "replay"}
            raise LLMError("no recorded reply for this prompt in SAMPLE_MODE")
        body = {"model": lane, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        try:
            data = self._req("/chat/completions", body, chat=True)
        except urllib.error.HTTPError as e:
            raise LLMError(f"Nightshift HTTP {e.code}: {e.read().decode(errors='replace')[:200]}") from e
        except (urllib.error.URLError, OSError) as e:
            raise LLMError(f"Nightshift unreachable at {self.base}: {e}") from e
        text = data["choices"][0]["message"].get("content") or ""
        model = data.get("model") or lane
        if self.record:
            with _lock:
                self.replay[k] = {"text": text, "model": model}
                REPLAY_PATH.write_text(json.dumps(self.replay, indent=1))
        return {"text": text, "model": model, "lane": lane, "source": "nightshift"}


def parse_json(text: str):
    """Pull the first JSON object or array out of a model reply (tolerates fences and <think>)."""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    m = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if m:
        text = m.group(1)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = text.find(opener)
        end = text.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except ValueError:
                continue
    raise LLMError("model reply had no parseable JSON")
