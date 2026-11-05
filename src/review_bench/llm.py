"""Thin wrapper around the Anthropic SDK: disk cache, cost ledger, hard budget cap.

Every request is cached on disk under cache/api/<sha256 of the request>.json, so a rerun of the same request
costs nothing. Every *paid* call is appended to cache/ledger.jsonl with its token usage and dollar cost; the
running total across all runs is checked against the budget cap before each new call.

The cache and ledger live under cache/, which is git-ignored. They hold model outputs and token counts, never the
API key.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import anthropic

from .common import ROOT

CACHE_DIR = ROOT / "cache" / "api"
LEDGER = ROOT / "cache" / "ledger.jsonl"

# USD per million tokens (input, output), Claude API first-party rates.
PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-fable-5-1": (10.00, 50.00),
}

# The environment this project was built in sets ANTHROPIC_BASE_URL to an internal endpoint. Benchmark calls must
# go to the public API with the user's own key, so the base URL is explicit (override with BENCH_API_BASE_URL).
PUBLIC_API = "https://api.anthropic.com"


class BudgetExceeded(RuntimeError):
    pass


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES[model]
    return input_tokens / 1e6 * price_in + output_tokens / 1e6 * price_out


def request_key(params: dict, sample: int = 0) -> str:
    """Cache key. Sample 0 is the plain request (keeps existing cache entries valid); sample k > 0 is an independent
    repeat of the same request, cached separately. The sample index is never sent to the API."""
    keyed = params if sample == 0 else {"request": params, "sample": sample}
    return hashlib.sha256(json.dumps(keyed, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def spent_so_far() -> float:
    if not LEDGER.exists():
        return 0.0
    return sum(json.loads(line)["cost_usd"] for line in LEDGER.read_text().splitlines() if line.strip())


@dataclass
class Result:
    response: dict  # the full response, as a dict (message.to_dict())
    cost_usd: float  # 0.0 when served from cache
    cached: bool


class Client:
    def __init__(self, budget_usd: float):
        # Claude Code cloud sessions reserve ANTHROPIC_API_KEY for their own auth, so the benchmark key gets its own name.
        key = os.environ.get("BENCH_ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit("BENCH_ANTHROPIC_API_KEY is not set. Add it in the environment settings and start a new "
                             "session.")
        # Organisation-level keys that are not scoped to a workspace must name one on every request.
        workspace = os.environ.get("BENCH_ANTHROPIC_WORKSPACE_ID")
        self.sdk = anthropic.Anthropic(api_key=key, base_url=os.environ.get("BENCH_API_BASE_URL", PUBLIC_API),
                                       max_retries=4, timeout=600.0,
                                       default_headers={"anthropic-workspace-id": workspace} if workspace else None)
        self.budget_usd = budget_usd
        self.lock = threading.Lock()
        self.key_locks: dict[str, threading.Lock] = {}

    def count_tokens(self, model: str, system: str, messages: list[dict]) -> int:
        return self.sdk.messages.count_tokens(model=model, system=system, messages=messages).input_tokens

    def create(self, params: dict, tag: str, sample: int = 0) -> Result:
        """messages.create with caching and budget enforcement. `tag` identifies the call in the ledger.

        Identical concurrent requests are serialized by a per-request lock, so each is paid for once.
        """
        key = request_key(params, sample)
        with self.lock:
            key_lock = self.key_locks.setdefault(key, threading.Lock())
        with key_lock:
            return self._create(params, tag, key)

    def _create(self, params: dict, tag: str, key: str) -> Result:
        path = CACHE_DIR / f"{key}.json"
        if path.exists():
            return Result(json.loads(path.read_text())["response"], 0.0, True)
        with self.lock:
            spent = spent_so_far()
            if spent >= self.budget_usd:
                raise BudgetExceeded(f"budget cap ${self.budget_usd:.2f} reached (spent ${spent:.2f})")
        started = time.time()
        message = self.sdk.messages.create(**params)
        response = message.to_dict()
        usage = response["usage"]
        cost = cost_usd(params["model"], usage["input_tokens"], usage["output_tokens"])
        with self.lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"request": params, "response": response}, ensure_ascii=False))
            os.replace(tmp, path)  # atomic: readers never see a half-written file
            with open(LEDGER, "a") as fh:
                fh.write(json.dumps({
                    "time": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": tag, "key": key, "model": params["model"],
                    "input_tokens": usage["input_tokens"], "output_tokens": usage["output_tokens"],
                    "cost_usd": round(cost, 6), "seconds": round(time.time() - started, 1),
                    "request_id": response.get("_request_id") or getattr(message, "_request_id", None),
                }) + "\n")
        return Result(response, cost, False)


def is_cached(params: dict, sample: int = 0) -> bool:
    return (CACHE_DIR / f"{request_key(params, sample)}.json").exists()


def response_text(response: dict) -> str:
    return "".join(block.get("text", "") for block in response["content"] if block["type"] == "text")


def rough_tokens(text: str) -> int:
    """Offline estimate used only when no API key is available (dry run). count_tokens is used otherwise."""
    return int(len(text) / 3.2) + 1


def ensure_dirs(*paths: Path) -> None:
    for p in paths:
        p.mkdir(parents=True, exist_ok=True)
