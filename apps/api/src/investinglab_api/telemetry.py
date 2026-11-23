"""Traces with OpenTelemetry (ADR-0048): optional, and off by default.

This is the only module that imports OpenTelemetry. The rest of the API asks it for spans
and trace contexts in its own terms, and the core library never sees it.

With ``INVESTINGLAB_API_TRACING=otlp`` (or ``console``) each process traces:

* **every request** to the API (its route, status and request id), except the health probes;
* **every call out**: the HTTP requests to the data sources and the statements sent to the
  database, inside the request or job that made them;
* **every job**, from the request that submitted it (a ``send`` span) to each attempt of the
  worker that ran it (a ``process`` span continued from the trace the job carries);
* **every check of the data sources**, one event per source.

Log lines written inside a span carry its ``trace_id`` and ``span_id``, so a log line leads to
its trace and back. URLs are masked before they are recorded, with the rule the logs follow
(``api_key=***``): a credential never reaches a trace either.

The exporter is configured with the standard ``OTEL_*`` variables (endpoint, headers, sampler,
resource attributes); without ``OTEL_SERVICE_NAME`` the services are ``investinglab-api`` and
``investinglab-worker``.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING, Any, Final, Literal

from opentelemetry import propagate, trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from opentelemetry.instrumentation.utils import suppress_instrumentation
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
)
from opentelemetry.trace import SpanKind, Status, StatusCode

from investinglab.config import get_logger, redact_text
from investinglab_api import __version__
from investinglab_api.settings import TracingMode

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

    from fastapi import FastAPI
    from structlog.typing import EventDict, WrappedLogger

__all__ = [
    "PROBE_PATHS",
    "SCOPE",
    "SpanHandle",
    "TraceCarrier",
    "add_trace_context",
    "annotate",
    "configure_tracing",
    "current_carrier",
    "flush_tracing",
    "instrument_app",
    "messaging",
    "shutdown_tracing",
    "span",
    "tracing_enabled",
    "untraced",
]

log = get_logger(__name__)

SCOPE: Final = "investinglab_api"
"""Name of the instrumentation scope of the spans this package creates."""

PROBE_PATHS: Final = ("/health/live", "/health/ready")
"""Requests never traced, nor what they do: probes asked every few seconds would bury the rest."""

UNTRACED_URLS: Final = ",".join(path.lstrip("/") for path in PROBE_PATHS)

URL_ATTRIBUTES: Final = ("url.full", "http.url")
"""Where an outbound span keeps its URL (the stable and the older semantic conventions)."""

type TraceCarrier = dict[str, str]
"""A trace context written as text (W3C ``traceparent``), to carry it to another process."""

type Kind = Literal["internal", "producer", "consumer"]

_KINDS: Final[dict[str, SpanKind]] = {
    "internal": SpanKind.INTERNAL,
    "producer": SpanKind.PRODUCER,
    "consumer": SpanKind.CONSUMER,
}

_provider: TracerProvider | None = None


def _resource(service: str) -> Resource:
    """The process's resource; ``OTEL_SERVICE_NAME`` (or its resource attribute) wins."""
    attributes = {"service.namespace": "investinglab", "service.version": __version__}
    detected = Resource.create(attributes)
    named = str(detected.attributes.get(SERVICE_NAME, ""))
    if named and not named.startswith("unknown_service"):
        return detected
    return detected.merge(Resource({SERVICE_NAME: service}))


def _masked_url(span: trace.Span) -> None:
    """Mask the credentials of the URL an outbound span recorded."""
    if not span.is_recording():
        return
    attributes: Mapping[str, Any] = getattr(span, "attributes", None) or {}
    for key in URL_ATTRIBUTES:
        value = attributes.get(key)
        if isinstance(value, str):
            span.set_attribute(key, redact_text(value))


def _sync_request(span: trace.Span, _: object) -> None:
    _masked_url(span)


async def _async_request(span: trace.Span, _: object) -> None:
    _masked_url(span)


def configure_tracing(
    mode: TracingMode, *, service: str, exporter: SpanExporter | None = None
) -> bool:
    """Start tracing this process, once; whether it traces.

    The first call that turns it on wins: later calls (another app in the same process) keep
    that configuration. The HTTP clients and database engines created afterwards are traced.

    Args:
        mode: Where the spans go; with ``off`` nothing changes.
        service: Name of the service when ``OTEL_SERVICE_NAME`` does not give one.
        exporter: Where the spans go instead, each as soon as it ends (the tests' memory).
    """
    global _provider  # noqa: PLW0603 - tracing is the process's, set up once
    if _provider is not None:
        return True
    if mode is TracingMode.OFF:
        return False
    provider = TracerProvider(resource=_resource(service))
    if exporter is not None:
        provider.add_span_processor(SimpleSpanProcessor(exporter))
    elif mode is TracingMode.CONSOLE:
        provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    else:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    HTTPXClientInstrumentor().instrument(
        tracer_provider=provider, request_hook=_sync_request, async_request_hook=_async_request
    )
    # Its release still declares SQLAlchemy < 2.1; it only uses the engine's stable events,
    # and the tests check that the statements of 2.1 are traced (ADR-0048).
    SQLAlchemyInstrumentor().instrument(tracer_provider=provider, skip_dep_check=True)
    _provider = provider
    log.info("tracing_started", mode=mode.value, service=service)
    return True


def tracing_enabled() -> bool:
    """Whether this process traces."""
    return _provider is not None


def instrument_app(app: FastAPI) -> None:
    """Trace every request to ``app`` (but the health probes), if this process traces."""
    if _provider is not None:
        FastAPIInstrumentor.instrument_app(
            app,
            tracer_provider=_provider,
            excluded_urls=UNTRACED_URLS,
            exclude_spans=["receive", "send"],  # one span per request, not one per ASGI message
        )


def flush_tracing(timeout_seconds: float = 5.0) -> None:
    """Send the spans waiting in the exporter's buffer."""
    if _provider is not None:
        _provider.force_flush(int(timeout_seconds * 1_000))


def shutdown_tracing() -> None:
    """Send what is pending and stop tracing this process (a worker that stops, the tests)."""
    global _provider  # noqa: PLW0603 - see configure_tracing
    if _provider is None:
        return
    HTTPXClientInstrumentor().uninstrument()
    SQLAlchemyInstrumentor().uninstrument()
    _provider.shutdown()
    _provider = None


class SpanHandle:
    """What a span of this package can be told while it runs, in plain values."""

    def __init__(self, inner: trace.Span) -> None:
        self._inner = inner

    def set(self, **attributes: str | int | float | bool) -> None:
        """Add or replace attributes."""
        self._inner.set_attributes(attributes)

    def event(self, name: str, **attributes: str | int | float | bool) -> None:
        """Record something that happened at this instant."""
        self._inner.add_event(name, attributes)

    def fail(self, description: str) -> None:
        """Mark the span as failed, with what went wrong (no credentials, no personal data)."""
        self._inner.set_status(Status(StatusCode.ERROR, redact_text(description)))


@contextlib.contextmanager
def span(
    name: str,
    *,
    kind: Kind = "internal",
    attributes: Mapping[str, str | int | float | bool] | None = None,
    parent: Mapping[str, str] | None = None,
) -> Iterator[SpanHandle]:
    """Run the block inside a span, current while it runs; a no-op when nothing traces.

    Args:
        name: What the span does (``send jobs``, ``check sources``...).
        kind: ``producer`` and ``consumer`` for the two ends of a job.
        attributes: What describes it.
        parent: The trace context it continues, as :func:`current_carrier` wrote it in
            another process; by default the current one.
    """
    tracer = _provider.get_tracer(SCOPE, __version__) if _provider else trace.NoOpTracer()
    context = propagate.extract(dict(parent)) if parent else None
    with tracer.start_as_current_span(
        name, context=context, kind=_KINDS[kind], attributes=dict(attributes or {})
    ) as inner:
        yield SpanHandle(inner)


def messaging(queue: str, operation: Literal["send", "process"]) -> dict[str, str]:
    """The attributes of either end of a queue, in OpenTelemetry's messaging conventions."""
    return {
        "messaging.system": "procrastinate",
        "messaging.destination.name": queue,
        "messaging.operation.type": operation,
        "messaging.operation.name": operation,
    }


def annotate(**attributes: str | int | float | bool) -> None:
    """Add attributes to the current span (the request's, in the API), if one is recorded."""
    current = trace.get_current_span()
    if current.is_recording():
        current.set_attributes(attributes)


@contextlib.contextmanager
def untraced() -> Iterator[None]:
    """Run the block without tracing anything it does (its database statements included)."""
    with suppress_instrumentation():
        yield


def current_carrier() -> TraceCarrier:
    """The current trace context as text, to continue it elsewhere; empty when untraced."""
    carrier: TraceCarrier = {}
    propagate.inject(carrier)
    return carrier


def add_trace_context(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    """Structlog processor: the trace and span ids of the span the line is written in."""
    context = trace.get_current_span().get_span_context()
    if context.is_valid:
        event_dict["trace_id"] = trace.format_trace_id(context.trace_id)
        event_dict["span_id"] = trace.format_span_id(context.span_id)
    return event_dict
