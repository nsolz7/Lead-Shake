import pytest

from app.config import get_settings
from app.connectors.base import ConnectorScope
from app.connectors.email_verifier import EmailVerificationConnector
from app.tasks import execute_source_run
from app.models import ProviderRateCard
from app.services.research import calculate_openai_cost_microusd


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"data": {"status": "valid", "score": 95}}


class _Client:
    def __init__(self, *args, **kwargs):
        self.calls = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def get(self, *args, **kwargs):
        self.calls += 1
        return _Response()


@pytest.mark.asyncio
async def test_commercial_connector_stops_before_budget_ceiling(monkeypatch):
    monkeypatch.setattr(get_settings(), "email_verification_api_key", "fixture-key")
    monkeypatch.setattr("app.connectors.email_verifier.httpx.AsyncClient", _Client)
    async def no_sleep(_):
        return None
    monkeypatch.setattr("app.connectors.email_verifier.asyncio.sleep", no_sleep)
    connector = EmailVerificationConnector()
    scope = ConnectorScope(
        commercial_enabled=True,
        budget_cents=100,
        parameters={
            "emails": ["one@example.com", "two@example.com"],
            "cost_per_email_cents": 60,
        },
    )
    records = [record async for record in connector.discover(scope)]
    assert len(records) == 1
    assert connector.spent_cents == 60
    assert connector.spent_cents <= scope.budget_cents


def test_network_jobs_have_bounded_retries():
    assert execute_source_run.max_retries == 3


def test_openai_usage_cost_uses_actual_tokens_and_search_calls():
    card = ProviderRateCard(
        id="fixture", provider="openai", model="fixture", effective_on=__import__("datetime").date(2026, 1, 1),
        input_usd_per_million=1.0, cached_input_usd_per_million=0.1,
        output_usd_per_million=6.0, web_search_usd_per_thousand=10.0,
        source_url="https://example.test/pricing",
    )
    usage = {"input_tokens": 1000, "input_tokens_details": {"cached_tokens": 200}, "output_tokens": 500}
    assert calculate_openai_cost_microusd(usage, 2, card) == 23820
