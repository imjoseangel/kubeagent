"""OpenTelemetry distributed tracing setup.

Wires the kubeagent FastAPI service into an OpenTelemetry collector so a
single investigation can be followed end to end: the inbound HTTP request,
the background agent workflow it spawns (see ``app.agents.troubleshooter``),
and every outbound LLM call the agent makes to the LiteLLM proxy over httpx.

Tracing is opt-in. With no ``OTEL_EXPORTER_OTLP_ENDPOINT`` configured — the
default for tests and local development — ``setup_telemetry`` is a no-op, so
nothing ever tries to reach a collector that isn't there.

Reference:
https://developers.redhat.com/articles/2026/04/06/distributed-tracing-agentic-workflows-opentelemetry
"""

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
    OTLPSpanExporter,
)
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.propagate import set_global_textmap
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace.propagation.tracecontext import (
    TraceContextTextMapPropagator,
)

from app.core.config import settings

# Guards against re-instrumenting the app (e.g. if setup is called twice in
# one process), which OpenTelemetry rejects with a noisy warning.
_configured = False


def setup_telemetry(app: FastAPI) -> bool:
    """Configure OTLP tracing and instrument the FastAPI app.

    Returns True when tracing was configured, and False when it was
    skipped — either because no collector endpoint is set (tracing is
    disabled) or because it was already configured in this process.
    """
    global _configured
    if _configured or not settings.otel_exporter_otlp_endpoint:
        return False

    resource = Resource.create({"service.name": settings.otel_service_name})
    provider = TracerProvider(resource=resource)
    # The endpoint (and any OTEL_EXPORTER_OTLP_HEADERS) are read straight
    # from the standard OTEL_EXPORTER_OTLP_* environment variables by the
    # exporter, so the HTTP exporter appends the correct /v1/traces path.
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)

    # W3C trace context so spans stitch together across the HTTP hop into
    # the LiteLLM proxy and any other OTel-aware service downstream.
    set_global_textmap(TraceContextTextMapPropagator())

    # Outbound LLM calls (LlamaIndex talks to LiteLLM over httpx) and the
    # inbound REST surface.
    HTTPXClientInstrumentor().instrument()
    FastAPIInstrumentor.instrument_app(app)

    _configured = True
    return True
