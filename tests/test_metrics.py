import asyncio

import pytest
from fastapi import Request
from prometheus_client import generate_latest

from src import api
from src.metrics import RuntimeCollector


def test_metric_route_never_uses_image_ids():
    assert api.metric_route("/text2img/data/a-unique-image-id.png") == (
        "/text2img/data/{id}"
    )
    assert api.metric_route("/not-found/some-random-value") == "unmatched"
    assert api.metric_route("/url2img/generate") == "/url2img/generate"
    assert api.metric_route("/url2img/data/image.png") == "/url2img/data/{id}"


def make_request(authorization: str = "") -> Request:
    headers = []
    if authorization:
        headers.append((b"authorization", authorization.encode()))
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/metrics",
            "headers": headers,
        }
    )


def test_metrics_endpoint_exposes_prometheus_payload(monkeypatch):
    monkeypatch.setattr(api, "METRICS_ENABLED", True)
    monkeypatch.delenv("METRICS_TOKEN", raising=False)
    response = asyncio.run(api.prometheus_metrics(make_request()))

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert b"t2i_cgroup_memory_current_bytes" in response.body
    assert b"t2i_render_requests_total" in response.body


def test_metrics_endpoint_supports_bearer_auth(monkeypatch):
    monkeypatch.setattr(api, "METRICS_ENABLED", True)
    monkeypatch.setenv("METRICS_TOKEN", "test-token")

    unauthorized = asyncio.run(api.prometheus_metrics(make_request()))
    authorized = asyncio.run(api.prometheus_metrics(make_request("Bearer test-token")))

    assert unauthorized.status_code == 401
    assert authorized.status_code == 200


def test_metrics_generation_runs_in_a_worker_thread(monkeypatch):
    monkeypatch.setattr(api, "METRICS_ENABLED", True)
    calls = []

    async def fake_to_thread(function):
        calls.append(function)
        return b"test_metric 1\n"

    monkeypatch.setattr(api.asyncio, "to_thread", fake_to_thread)

    response = asyncio.run(api.prometheus_metrics(make_request()))

    assert calls == [api.generate_latest]
    assert response.body == b"test_metric 1\n"


def test_periodic_cleanup_runs_in_a_worker_thread(monkeypatch):
    calls = []

    async def fake_to_thread(function):
        calls.append(function)
        return 2

    async def stop_after_first_interval(delay):
        assert delay == 3600
        raise asyncio.CancelledError

    monkeypatch.setattr(api.asyncio, "to_thread", fake_to_thread)
    monkeypatch.setattr(api.asyncio, "sleep", stop_after_first_interval)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(api.periodic_cleanup())

    assert calls == [api.cleanup_expired_files]


def test_metrics_endpoint_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(api, "METRICS_ENABLED", False)

    response = asyncio.run(api.prometheus_metrics(make_request()))

    assert response.status_code == 404
    assert response.body == b""


def test_runtime_collector_reads_cgroup_v2_metrics(tmp_path):
    (tmp_path / "memory.current").write_text("536870912\n", encoding="utf-8")
    (tmp_path / "memory.max").write_text("1610612736\n", encoding="utf-8")
    (tmp_path / "memory.stat").write_text(
        "anon 400000000\nfile 100000000\nkernel 20000000\n",
        encoding="utf-8",
    )
    (tmp_path / "memory.events").write_text(
        "low 0\nhigh 1\nmax 7\noom 2\noom_kill 2\n",
        encoding="utf-8",
    )
    collector = RuntimeCollector()
    collector.cgroup_root = tmp_path

    output = b"".join(
        metric_family.samples[0].name.encode()
        for metric_family in collector.collect()
        if metric_family.samples
    )
    assert b"t2i_cgroup_memory_current_bytes" in output
    assert b"t2i_cgroup_memory_limit_bytes" in output
    assert b"t2i_cgroup_memory_usage_ratio" in output

    events = next(
        metric_family
        for metric_family in collector.collect()
        if metric_family.name == "t2i_cgroup_memory_events"
    )
    oom_kill = next(
        sample for sample in events.samples if sample.labels.get("event") == "oom_kill"
    )
    assert oom_kill.value == 2


def test_global_registry_renders_runtime_metrics():
    payload = generate_latest()

    assert b"# HELP t2i_chromium_resident_memory_bytes" in payload
