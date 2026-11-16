"""Capacity handling for campaign batches.

When every from-number or concurrent slot is busy, a batch must stop
gracefully and hand the unsent runs back to the queue. It must never raise and
fail the campaign, and a cancelled job must not leave runs stuck in
'processing'.

These tests mock the database and rate limiter so they do not need PostgreSQL.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.services.campaign import campaign_call_dispatcher as dispatcher_module
from api.services.campaign.campaign_call_dispatcher import CampaignCallDispatcher
from api.services.campaign.errors import PhoneNumberPoolExhaustedError


def _campaign():
    return SimpleNamespace(
        id=1,
        state="running",
        organization_id=7,
        rate_limit_per_second=1,
        processed_rows=0,
    )


def _queued_runs(count: int):
    return [
        SimpleNamespace(id=100 + i, context_variables={"phone_number": "+15550000000"})
        for i in range(count)
    ]


def _db_client(campaign, queued_runs):
    return SimpleNamespace(
        get_campaign_by_id=AsyncMock(return_value=campaign),
        claim_queued_runs_for_processing=AsyncMock(return_value=queued_runs),
        update_queued_run=AsyncMock(),
        update_campaign=AsyncMock(),
    )


def _rate_limiter():
    return SimpleNamespace(initialize_from_number_pool=AsyncMock(return_value=True))


def _dispatcher():
    dispatcher = CampaignCallDispatcher()
    dispatcher.apply_rate_limit = AsyncMock()
    dispatcher.acquire_concurrent_slot = AsyncMock(return_value="slot-1")
    dispatcher.get_telephony_provider = AsyncMock(
        return_value=SimpleNamespace(from_numbers=["+15551111111"])
    )
    return dispatcher


def _reverted_ids(db_client):
    return [
        call.kwargs["queued_run_id"]
        for call in db_client.update_queued_run.await_args_list
        if call.kwargs.get("state") == "queued"
    ]


class TestBatchCapacity:
    @pytest.mark.asyncio
    async def test_busy_pool_reverts_unsent_runs_without_raising(self):
        campaign = _campaign()
        queued_runs = _queued_runs(3)
        db_client = _db_client(campaign, queued_runs)
        dispatcher = _dispatcher()
        workflow_run = SimpleNamespace(id=500)

        dispatcher.dispatch_call = AsyncMock(
            side_effect=[
                workflow_run,
                PhoneNumberPoolExhaustedError(organization_id=campaign.organization_id),
            ]
        )

        with (
            patch.object(dispatcher_module, "db_client", db_client),
            patch.object(dispatcher_module, "rate_limiter", _rate_limiter()),
        ):
            processed = await dispatcher.process_batch(campaign_id=1, batch_size=3)

        assert processed == 1
        # The current run and everything after it go back to the queue.
        assert _reverted_ids(db_client) == [101, 102]

    @pytest.mark.asyncio
    async def test_cancelled_job_reverts_claimed_runs(self):
        campaign = _campaign()
        queued_runs = _queued_runs(2)
        db_client = _db_client(campaign, queued_runs)
        dispatcher = _dispatcher()
        dispatcher.dispatch_call = AsyncMock(side_effect=asyncio.CancelledError())

        with (
            patch.object(dispatcher_module, "db_client", db_client),
            patch.object(dispatcher_module, "rate_limiter", _rate_limiter()),
        ):
            with pytest.raises(asyncio.CancelledError):
                await dispatcher.process_batch(campaign_id=1, batch_size=2)

        assert _reverted_ids(db_client) == [100, 101]

    @pytest.mark.asyncio
    async def test_exhausted_dispatch_budget_reverts_claimed_runs(self):
        campaign = _campaign()
        queued_runs = _queued_runs(2)
        db_client = _db_client(campaign, queued_runs)
        dispatcher = _dispatcher()
        dispatcher.batch_dispatch_timeout = 0
        dispatcher.dispatch_call = AsyncMock()

        with (
            patch.object(dispatcher_module, "db_client", db_client),
            patch.object(dispatcher_module, "rate_limiter", _rate_limiter()),
        ):
            processed = await dispatcher.process_batch(campaign_id=1, batch_size=2)

        assert processed == 0
        assert _reverted_ids(db_client) == [100, 101]
        dispatcher.dispatch_call.assert_not_awaited()
