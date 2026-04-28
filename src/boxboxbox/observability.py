from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from boxboxbox.config import settings

logger = logging.getLogger(__name__)

_provider: TracerProvider | None = None
tracer: trace.Tracer = trace.get_tracer("boxboxbox")


def init_observability() -> None:
    """Set up OpenTelemetry tracing with Phoenix as the backend.

    Must be called before any PydanticAI agents are created so that
    Agent.instrument_all() picks up the configured TracerProvider.
    """
    global _provider, tracer

    if not settings.PHOENIX_ENABLED:
        logger.info("Phoenix observability disabled")
        return

    try:
        from pydantic_ai.agent import Agent, InstrumentationSettings

        resource = Resource.create({"service.name": settings.PHOENIX_PROJECT_NAME})
        _provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=f"{settings.PHOENIX_ENDPOINT}/v1/traces")
        _provider.add_span_processor(SimpleSpanProcessor(exporter))
        trace.set_tracer_provider(_provider)

        tracer = trace.get_tracer("boxboxbox")

        Agent.instrument_all(InstrumentationSettings(tracer_provider=_provider))
        logger.info("Phoenix observability enabled → %s", settings.PHOENIX_ENDPOINT)
    except Exception:
        logger.exception("Failed to initialise Phoenix observability — continuing without tracing")


def shutdown_observability() -> None:
    """Flush pending spans and shut down the tracer provider."""
    if _provider is not None:
        try:
            _provider.force_flush()
            _provider.shutdown()
            logger.info("Observability shut down")
        except Exception:
            logger.exception("Error shutting down observability")
