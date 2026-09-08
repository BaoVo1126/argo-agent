"""
The trace reaches the browser while the run is still going.

This is the one claim in the feature that a unit test of the pipeline cannot
make. `probe_pool` emitting events proves the events exist; it does not prove
a customer sees them before the result does, and a stream that quietly
buffered until the job finished would pass every other test in this suite
while delivering exactly the static report the trace was built to replace.

So the run here is a stub that pauses in the middle, and the assertion is
about *when* the bytes arrive: the first events must be readable off the
stream while the job's status is still "running".
"""

from __future__ import annotations

import json
import threading

import pytest
from fastapi.testclient import TestClient

from modes.research import pipeline
from web import main as web


@pytest.fixture
def client(monkeypatch):
    """A server whose scrape is a stub we can hold open."""
    released = threading.Event()
    reached_middle = threading.Event()

    def fake_run(request, output_dir=None, log=None, trace=None, **_kwargs):
        log = log or (lambda _line: None)
        log("Đang xác định loại dữ liệu cần tìm…")
        trace.event("probe", "Đang kiểm tra gso.gov.vn…", domain="gso.gov.vn")
        trace.event("keep", "Đạt ngưỡng 60/100", domain="gso.gov.vn",
                    score=60, threshold=60)
        reached_middle.set()
        released.wait(timeout=10)
        trace.event("summary", "Đã xác nhận 1/1 nguồn, đang tổng hợp")
        result = pipeline.ResearchResult(topic=request.topic, start=request.start,
                                         end=request.end)
        result.refusal = "Dừng ở đây, đây là bản chạy thử."
        return result

    monkeypatch.setattr(pipeline, "run", fake_run)
    with TestClient(web.app) as client:
        client.released = released
        client.reached_middle = reached_middle
        yield client
    released.set()


def _start(client) -> str:
    response = client.post("/api/run", json={
        "topic": "lạm phát Việt Nam",
        "start": "2020-01-01", "end": "2024-12-31",
    })
    assert response.status_code == 200
    return response.json()["id"]


def test_frames_are_produced_while_the_run_is_still_going(client):
    """The claim the whole feature rests on, tested at the only place it can
    be. `TestClient` collects a streaming response in full before returning
    it, so driving the endpoint through HTTP would prove nothing about when
    the bytes left -- the generator is pulled directly instead."""
    job_id = _start(client)
    assert client.reached_middle.wait(timeout=10)

    job = web._JOBS[job_id]
    frames = web.trace_frames(job)
    events = [json.loads(next(frames)[len("data: "):]) for _ in range(2)]

    assert job.status == "running", "the run is supposed to still be in flight"
    assert [event["kind"] for event in events] == ["probe", "keep"]
    assert events[1]["score"] == 60

    # And it keeps going: the event published after this point arrives on the
    # same open generator rather than waiting for the result.
    job.publish({"kind": "hit", "text": "imf.org trả về 20 mốc dữ liệu"})
    assert json.loads(next(frames)[len("data: "):])["kind"] == "hit"
    frames.close()
    client.released.set()


def test_the_stream_endpoint_answers_as_an_event_stream(client):
    job_id = _start(client)
    assert client.reached_middle.wait(timeout=10)
    client.released.set()

    with client.stream("GET", f"/api/run/{job_id}/events") as stream:
        assert stream.status_code == 200
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["x-accel-buffering"] == "no"
        payloads = [json.loads(line[len("data: "):])
                    for line in stream.iter_lines() if line.startswith("data: ")]

    # The last frame is the end marker, which carries no event of its own: it
    # is what tells the browser to stop reconnecting to a finished run.
    assert payloads[-1] == {}
    assert [p["kind"] for p in payloads[:2]] == ["probe", "keep"]


def test_every_event_carries_its_position_so_a_reconnect_cannot_double_up(client):
    job_id = _start(client)
    assert client.reached_middle.wait(timeout=10)
    client.released.set()

    body = client.get(f"/api/run/{job_id}").json()
    indexes = [event["i"] for event in body["events"]]
    assert indexes == sorted(indexes) == list(range(len(indexes)))


def test_the_poll_can_ask_for_only_what_it_is_missing(client):
    job_id = _start(client)
    assert client.reached_middle.wait(timeout=10)
    client.released.set()

    whole = client.get(f"/api/run/{job_id}").json()
    total = whole["event_total"]
    assert total >= 3

    tail = client.get(f"/api/run/{job_id}?since={total - 1}").json()
    assert len(tail["events"]) == 1
    assert tail["events"][0]["i"] == total - 1


def test_a_stream_for_a_job_that_never_existed_is_a_404(client):
    assert client.get("/api/run/khongcothat/events").status_code == 404
