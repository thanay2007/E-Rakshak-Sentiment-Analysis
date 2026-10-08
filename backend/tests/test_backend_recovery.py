"""Scheduling and model-fallback regressions observed in the backend logs."""
import asyncio
import importlib.util
import os
import sys
from types import SimpleNamespace

import httpx
import pytest


def module(name, filename):
    staged = os.environ.get("BACKEND_RECOVERY_STAGE")
    if staged:
        spec = importlib.util.spec_from_file_location(name, os.path.join(staged, filename))
        loaded = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(loaded)
        return loaded
    return __import__(name, fromlist=["*"])


scheduler = module("app.services.scheduler", "scheduler.py")
groq = module("app.services.groq_client", "groq_client.py")


def test_next_cycle_is_scheduled_only_after_collection_finishes(monkeypatch):
    events = []
    async def crawl():
        events.extend(["start", "finish"])
    fake = SimpleNamespace(running=True, add_job=lambda *args, **kwargs: events.append("scheduled"))
    monkeypatch.setattr(scheduler, "scheduler", fake)
    monkeypatch.setattr(scheduler, "crawl_tick", crawl)
    asyncio.run(scheduler._scheduled_crawl())
    assert events == ["start", "finish", "scheduled"]


def test_failed_cycle_retries_but_shutdown_does_not_restart_it(monkeypatch):
    jobs = []
    async def fail():
        raise RuntimeError("Collector failed")
    fake = SimpleNamespace(running=True, add_job=lambda *args, **kwargs: jobs.append(kwargs))
    monkeypatch.setattr(scheduler, "scheduler", fake)
    monkeypatch.setattr(scheduler, "crawl_tick", fail)
    asyncio.run(scheduler._scheduled_crawl())
    assert len(jobs) == 1
    fake.running = False
    asyncio.run(scheduler._scheduled_crawl())
    assert len(jobs) == 1


def test_independent_collectors_start_together_and_keep_result_order(monkeypatch):
    received = []
    class Collector:
        min_interval_seconds = 0
        timeout_seconds = 2
        def __init__(self, name): self.name = name
        async def collect(self, terms):
            started.append(self.name)
            if len(started) == 2: ready.set()
            await asyncio.wait_for(ready.wait(), timeout=0.5)
            return [self.name]
    async def ingest(raws):
        received.extend(raws)
        return len(raws)
    async def run():
        nonlocal ready
        ready = asyncio.Event()
        await scheduler._crawl_tick_inner()
    ready = None
    started = []
    monkeypatch.setattr(scheduler, "_last_run", {})
    monkeypatch.setattr(scheduler, "_watch_terms", lambda: [])
    monkeypatch.setattr(scheduler, "get_active_collectors", lambda: [Collector("first"), Collector("second")])
    monkeypatch.setattr(scheduler, "ingest", ingest)
    monkeypatch.setitem(sys.modules, "app.osint.pr_analysis", SimpleNamespace(prime_count_cache=lambda: None))
    monkeypatch.setitem(sys.modules, "app.services.emerging", SimpleNamespace(prime_cache=lambda: None))
    asyncio.run(run())
    assert started == ["first", "second"]
    assert received == ["first", "second"]


def test_unavailable_groq_model_is_not_retried_next_request(monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "GROQ_API_KEY", "test-key")
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    monkeypatch.setattr(settings, "GROQ_MODEL", "retired-test-model")
    monkeypatch.setattr(settings, "GROQ_FALLBACK_MODELS", ["live-test-model"])
    monkeypatch.setattr(groq, "_unavailable_models", set())
    monkeypatch.setattr(groq, "_cooldown", {})
    calls = []
    def reply(request):
        import json
        name = json.loads(request.content)["model"]
        calls.append(name)
        if name == "retired-test-model": return httpx.Response(404, json={"error": {"code": "model_not_found"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(reply)) as client:
            assert (await groq.chat([{"role": "user", "content": "hello"}], client=client))[0] == "ok"
            assert (await groq.chat([{"role": "user", "content": "hello"}], client=client))[0] == "ok"
    asyncio.run(run())
    assert calls == ["retired-test-model", "live-test-model", "live-test-model"]
    assert groq.status()["models"][0]["state"] == "unavailable"


def test_json_instructions_do_not_mutate_the_callers_messages():
    messages = [{"role": "system", "content": "Translate."}, {"role": "user", "content": "hello"}]
    body = groq._body("openai/gpt-oss-20b", messages, 0, True)
    assert messages[0]["content"] == "Translate."
    assert "valid JSON object" in body["messages"][0]["content"]
    assert body["response_format"] == {"type": "json_object"}
