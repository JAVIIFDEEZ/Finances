"""Traces with OpenTelemetry (ADR-0048): off by default, and what they record when on.

The spans go to memory (``InMemorySpanExporter``) instead of a collector; the job's trace is
followed on PostgreSQL from the request that submits it to the worker that runs it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING
from uuid import uuid4

import httpx
import psycopg
import pytest
import respx
from fastapi.testclient import TestClient
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
)
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import INVALID_SPAN_CONTEXT, NonRecordingSpan, SpanKind, StatusCode

from investinglab.ports import JobStatus
from investinglab_api import telemetry, worker
from investinglab_api.app import create_app
from investinglab_api.jobs.sources import check_and_record
from investinglab_api.persistence import Database, SqlJobRepository, queue_app
from investinglab_api.persistence.queue import QUEUE, RUN_JOB, conninfo
from investinglab_api.settings import ApiSettings, TracingMode
from support.repositories import InMemoryHeartbeatStore, InMemoryJobRepository

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

    from opentelemetry.sdk.trace import ReadableSpan

    from investinglab.config import Settings
    from investinglab.toolkit import AsyncToolkit

    type Body = dict[str, object]

TRACED = ApiSettings(tracing=TracingMode.CONSOLE)
FAKE_KEY = "not-a-real-key"  # pragma: allowlist secret
HEX = re.compile(r"[0-9a-f]+")


@pytest.fixture
def spans() -> Iterator[InMemorySpanExporter]:
    """Trace this test, with every span kept in memory."""
    exporter = InMemorySpanExporter()
    assert telemetry.configure_tracing(
        TracingMode.CONSOLE, service="investinglab-test", exporter=exporter
    )
    yield exporter
    telemetry.shutdown_tracing()


def _named(spans: InMemorySpanExporter, name: str) -> ReadableSpan:
    (found,) = [span for span in spans.get_finished_spans() if span.name == name]
    return found


def _servers(spans: InMemorySpanExporter) -> list[ReadableSpan]:
    return [span for span in spans.get_finished_spans() if span.kind is SpanKind.SERVER]


def _of_job(spans: InMemorySpanExporter, name: str, job_id: str) -> ReadableSpan:
    """The span ``name`` of one job (the queue may hold other tests' jobs)."""
    (found,) = [
        span
        for span in spans.get_finished_spans()
        if span.name == name and (span.attributes or {}).get("investinglab.job.id") == job_id
    ]
    return found


def _ids(span: ReadableSpan) -> tuple[int, int]:
    """The trace and span ids of a finished span."""
    context = span.context
    assert context is not None
    return context.trace_id, context.span_id


def _parent(span: ReadableSpan) -> int | None:
    """The id of the span's parent; ``None`` for a root."""
    return None if span.parent is None else span.parent.span_id


# ── Off by default ─────────────────────────────────────────────────────────


def test_nothing_is_traced_by_default() -> None:
    assert ApiSettings().tracing is TracingMode.OFF
    assert telemetry.configure_tracing(TracingMode.OFF, service="investinglab-api") is False
    assert not telemetry.tracing_enabled()
    with telemetry.span("anything", attributes={"a": 1}) as span:
        span.set(b=2)
        span.event("happened")
        span.fail("nothing to fail")
        telemetry.annotate(c=3)
        assert telemetry.current_carrier() == {}  # nothing to carry to the worker
        assert telemetry.add_trace_context(None, "info", {"event": "x"}) == {"event": "x"}
    telemetry.flush_tracing()
    telemetry.shutdown_tracing()  # nothing to stop


def test_the_api_works_the_same_without_traces(client: TestClient) -> None:
    assert client.get("/api/v1/providers").status_code == 200


# ── Where the spans go ─────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("mode", "processor", "exporter"),
    [
        (TracingMode.OTLP, BatchSpanProcessor, OTLPSpanExporter),
        (TracingMode.CONSOLE, SimpleSpanProcessor, ConsoleSpanExporter),
    ],
)
def test_each_mode_sends_the_spans_where_it_says(
    mode: TracingMode, processor: type, exporter: type
) -> None:
    try:
        assert telemetry.configure_tracing(mode, service="investinglab-api")
        provider = telemetry._provider
        assert provider is not None
        (active,) = provider._active_span_processor._span_processors
        assert isinstance(active, processor)
        assert isinstance(active.span_exporter, exporter)  # type: ignore[attr-defined]
        assert provider.resource.attributes["service.name"] == "investinglab-api"
        assert provider.resource.attributes["service.namespace"] == "investinglab"
    finally:
        telemetry.shutdown_tracing()
    assert not telemetry.tracing_enabled()


def test_the_standard_variables_name_the_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SERVICE_NAME", "lab-on-my-laptop")

    assert telemetry._resource("investinglab-api").attributes["service.name"] == "lab-on-my-laptop"


def test_the_first_configuration_of_the_process_wins(spans: InMemorySpanExporter) -> None:
    assert telemetry.configure_tracing(TracingMode.OTLP, service="another")

    with telemetry.span("kept"):
        pass

    assert [span.name for span in spans.get_finished_spans()] == ["kept"]
    assert _named(spans, "kept").resource.attributes["service.name"] == "investinglab-test"


# ── What a span records ────────────────────────────────────────────────────


def test_a_span_continues_the_trace_it_is_given(spans: InMemorySpanExporter) -> None:
    with telemetry.span("send jobs", kind="producer", attributes={"messaging.system": "x"}):
        carrier = telemetry.current_carrier()
    with telemetry.span("process jobs", kind="consumer", parent=carrier) as span:
        span.set(attempt=1)
        span.event("source.checked", provider="yahoo", ok=True)
        span.fail(f"GET https://api.example.test/?api_key={FAKE_KEY} failed")

    producer, consumer = _named(spans, "send jobs"), _named(spans, "process jobs")
    assert set(carrier) == {"traceparent"}
    assert (producer.kind, consumer.kind) == (SpanKind.PRODUCER, SpanKind.CONSUMER)
    assert _ids(consumer)[0] == _ids(producer)[0]
    assert _parent(consumer) == _ids(producer)[1]
    assert consumer.attributes == {"attempt": 1}
    assert [event.name for event in consumer.events] == ["source.checked"]
    assert consumer.status.status_code is StatusCode.ERROR
    assert FAKE_KEY not in (consumer.status.description or "")


def test_log_lines_carry_the_ids_of_their_span(spans: InMemorySpanExporter) -> None:
    with telemetry.span("traced"):
        inside = telemetry.add_trace_context(None, "info", {"event": "inside"})
    outside = telemetry.add_trace_context(None, "info", {"event": "outside"})

    traced = _named(spans, "traced")
    assert traced.context is not None
    assert inside["trace_id"] == f"{traced.context.trace_id:032x}"
    assert inside["span_id"] == f"{traced.context.span_id:016x}"
    assert HEX.fullmatch(str(inside["trace_id"]))
    assert outside == {"event": "outside"}


async def test_the_urls_of_calls_out_never_keep_a_credential(
    spans: InMemorySpanExporter,
) -> None:
    url = "https://api.example.test/series"
    with respx.mock:
        respx.get(url).mock(return_value=httpx.Response(200, json={}))
        async with httpx.AsyncClient() as client:
            await client.get(url, params={"series_id": "A", "api_key": FAKE_KEY})

    assert _urls(spans) == [f"{url}?series_id=A&api_key=***"]


def test_so_do_those_of_a_client_that_blocks(spans: InMemorySpanExporter) -> None:
    url = "https://api.example.test/series"
    with respx.mock, httpx.Client() as client:
        respx.get(url).mock(return_value=httpx.Response(200, json={}))
        client.get(url, params={"token": FAKE_KEY})

    assert _urls(spans) == [f"{url}?token=***"]


def test_a_span_left_out_by_the_sampler_is_left_alone() -> None:
    dropped = NonRecordingSpan(INVALID_SPAN_CONTEXT)

    telemetry._masked_url(dropped)  # nothing recorded, nothing to mask

    assert not dropped.is_recording()


def _urls(spans: InMemorySpanExporter) -> list[str]:
    calls = [span for span in spans.get_finished_spans() if span.kind is SpanKind.CLIENT]
    return [
        str((span.attributes or {}).get("url.full", (span.attributes or {}).get("http.url")))
        for span in calls
    ]


# ── The API ────────────────────────────────────────────────────────────────


def test_each_request_is_a_span_with_its_route_and_its_id(
    spans: InMemorySpanExporter, toolkit: AsyncToolkit, core_settings: Settings
) -> None:
    with TestClient(create_app(TRACED, core_settings=core_settings, toolkit=toolkit)) as client:
        response = client.get("/api/v1/providers", headers={"X-Request-ID": "trace-me-0001"})

    (server,) = _servers(spans)
    assert spans.get_finished_spans() == (server,)  # nor a span per ASGI message
    assert response.status_code == 200
    assert server.name == "GET /api/v1/providers"
    assert server.attributes is not None
    assert server.attributes["http.route"] == "/api/v1/providers"
    assert server.attributes["investinglab.request_id"] == "trace-me-0001"


def test_the_probes_are_never_traced(
    spans: InMemorySpanExporter, toolkit: AsyncToolkit, core_settings: Settings
) -> None:
    with TestClient(create_app(TRACED, core_settings=core_settings, toolkit=toolkit)) as client:
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200

    assert spans.get_finished_spans() == ()


# ── The worker ─────────────────────────────────────────────────────────────


async def test_an_attempt_that_fails_is_a_failed_span(
    spans: InMemorySpanExporter, toolkit: AsyncToolkit
) -> None:
    jobs = InMemoryJobRepository()
    app = queue_app("postgresql+psycopg://nobody@localhost:1/none")  # never opened
    worker.register(app, jobs, toolkit=toolkit, settings=ApiSettings())
    job = await jobs.submit("owner", "simulation", {"n_paths": 500, "horizon": 20, "seed": 3})

    await app.tasks[RUN_JOB].func(job_id=str(job.id), owner_id="owner")  # no trace to continue
    await app.tasks[RUN_JOB].func(job_id=str(uuid4()), owner_id="owner")  # nothing to run

    failed, skipped = (
        span for span in spans.get_finished_spans() if span.name == f"process {QUEUE}"
    )
    assert failed.parent is None  # a root: the job came without a trace
    assert failed.attributes is not None
    assert failed.attributes["investinglab.job.status"] == JobStatus.FAILED.value
    assert failed.attributes["investinglab.job.kind"] == "simulation"
    assert failed.status.status_code is StatusCode.ERROR
    assert (failed.status.description or "").startswith("invalid-request")
    assert skipped.attributes is not None
    assert skipped.attributes["investinglab.job.status"] == "skipped"


async def test_a_check_of_the_sources_is_one_span_with_an_event_each(
    spans: InMemorySpanExporter, toolkit: AsyncToolkit
) -> None:
    statuses = await check_and_record(toolkit, InMemoryHeartbeatStore())

    check = _named(spans, "check sources")
    assert check.attributes is not None
    assert check.attributes["investinglab.sources.checked"] == len(statuses)
    assert len(check.events) == len(statuses)


# ── Across processes, on PostgreSQL ────────────────────────────────────────


@pytest.mark.integration
async def test_a_job_is_one_trace_from_the_request_to_the_worker(
    spans: InMemorySpanExporter,
    postgres: dict[str, str],
    toolkit: AsyncToolkit,
    core_settings: Settings,
    portfolio: Callable[..., Body],
) -> None:
    owner = f"owner-{uuid4().hex[:8]}"
    settings = ApiSettings(
        database_url=postgres["app"],  # type: ignore[arg-type]
        local_owner=owner,
        tracing=TracingMode.CONSOLE,
    )
    body = {"portfolio": portfolio(), "n_paths": 500, "horizon": 20, "seed": 3}

    with TestClient(create_app(settings, core_settings=core_settings, toolkit=toolkit)) as client:
        submitted = client.post("/api/v1/jobs/simulations", json=body)
        job_id = submitted.json()["id"]
        with psycopg.connect(conninfo(postgres["owner"])) as connection:
            (carried,) = connection.execute(
                "SELECT args->'trace' FROM procrastinate_jobs WHERE args->>'job_id' = %s",
                (job_id,),
            ).fetchone() or (None,)
        assert client.portal is not None
        client.portal.call(_work, postgres, toolkit)
        finished = client.get(submitted.headers["Location"]).json()

    request = next(s for s in _servers(spans) if s.name == "POST /api/v1/jobs/simulations")
    producer = _of_job(spans, f"send {QUEUE}", job_id)
    consumer = _of_job(spans, f"process {QUEUE}", job_id)
    assert finished["status"] == "succeeded"
    assert set(carried) == {"traceparent"}
    assert _parent(producer) == _ids(request)[1]  # sent inside the request
    assert _parent(consumer) == _ids(producer)[1]  # run where it was sent
    assert len({_ids(request)[0], _ids(producer)[0], _ids(consumer)[0]}) == 1
    assert consumer.attributes is not None
    assert consumer.attributes["investinglab.job.status"] == "succeeded"
    assert consumer.attributes["investinglab.job.attempt"] == 1
    statements = [
        s for s in spans.get_finished_spans() if s.attributes and "db.statement" in s.attributes
    ]
    assert _ids(consumer)[1] in {_parent(statement) for statement in statements}
    # A statement is recorded with its placeholders, never with the values it was sent.
    assert not any(owner in str(s.attributes["db.statement"]) for s in statements)  # type: ignore[index]


async def _work(postgres: dict[str, str], toolkit: AsyncToolkit) -> None:
    """Run a real worker until the queue is empty, with an engine made while tracing."""
    database = Database(postgres["app"])
    app = queue_app(postgres["app"])
    try:
        worker.register(
            app, SqlJobRepository(database, app), toolkit=toolkit, settings=ApiSettings()
        )
        async with app.open_async():
            await app.run_worker_async(
                queues=[QUEUE], wait=False, install_signal_handlers=False, delete_jobs="successful"
            )
    finally:
        await database.dispose()


@pytest.mark.integration
async def test_the_worker_traces_when_asked_and_stops_what_it_started(
    postgres: dict[str, str], core_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, bool] = {}

    async def run_worker_async(self: object, **_: object) -> None:
        seen["tracing"] = telemetry.tracing_enabled()

    monkeypatch.setattr("procrastinate.App.run_worker_async", run_worker_async)
    settings = ApiSettings(database_url=postgres["app"], tracing=TracingMode.CONSOLE)  # type: ignore[arg-type]

    await worker.serve(settings, core_settings)

    assert seen == {"tracing": True}
    assert not telemetry.tracing_enabled()
