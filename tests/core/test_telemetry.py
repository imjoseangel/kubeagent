from unittest.mock import patch

import pytest
from fastapi import FastAPI

import app.core.telemetry as telemetry


@pytest.fixture(autouse=True)
def _reset_configured():
    """Keep the module's process-global guard from leaking across tests."""
    telemetry._configured = False
    yield
    telemetry._configured = False


def test_setup_telemetry_disabled_without_endpoint(monkeypatch) -> None:
    monkeypatch.setattr(telemetry.settings, "otel_exporter_otlp_endpoint", "")

    assert telemetry.setup_telemetry(FastAPI()) is False


def test_setup_telemetry_skips_when_already_configured(monkeypatch) -> None:
    monkeypatch.setattr(
        telemetry.settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318",
    )
    telemetry._configured = True

    assert telemetry.setup_telemetry(FastAPI()) is False


def test_setup_telemetry_configures_and_instruments(monkeypatch) -> None:
    monkeypatch.setattr(
        telemetry.settings,
        "otel_exporter_otlp_endpoint",
        "http://collector:4318",
    )
    monkeypatch.setattr(telemetry.settings, "otel_service_name", "kubeagent")
    app = FastAPI()

    with (
        patch.object(telemetry, "OTLPSpanExporter"),
        patch.object(telemetry, "BatchSpanProcessor"),
        patch.object(telemetry, "TracerProvider"),
        patch.object(telemetry.trace, "set_tracer_provider"),
        patch.object(telemetry, "set_global_textmap") as set_propagator,
        patch.object(telemetry, "HTTPXClientInstrumentor") as httpx_inst,
        patch.object(telemetry, "FastAPIInstrumentor") as fastapi_inst,
    ):
        assert telemetry.setup_telemetry(app) is True
        set_propagator.assert_called_once()
        httpx_inst.return_value.instrument.assert_called_once()
        fastapi_inst.instrument_app.assert_called_once_with(app)

    assert telemetry._configured is True
