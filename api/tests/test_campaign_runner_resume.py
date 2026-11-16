"""Failed campaigns are recoverable without deleting and recreating them.

A failure is usually transient (storage blip, no call capacity). Restarting one
must either re-run the source sync (nothing was queued yet) or continue from
the rows that are still in the queue.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from api.services.campaign import runner as runner_module
from api.services.campaign.runner import CampaignRunnerService
from api.tasks.function_names import FunctionNames


def _db(campaign, queued_runs: int = 0):
    return SimpleNamespace(
        get_campaign_by_id=AsyncMock(return_value=campaign),
        count_queued_runs=AsyncMock(return_value=queued_runs),
        update_campaign=AsyncMock(),
    )


def _breaker():
    return SimpleNamespace(reset=AsyncMock())


async def test_failed_campaign_without_rows_reruns_source_sync():
    campaign = SimpleNamespace(id=9, state="failed")
    db = _db(campaign, queued_runs=0)
    breaker = _breaker()
    enqueue = AsyncMock()

    with (
        patch.object(runner_module, "db_client", db),
        patch.object(runner_module, "circuit_breaker", breaker),
        patch.object(runner_module, "enqueue_job", enqueue),
    ):
        await CampaignRunnerService().resume_campaign(9)

    assert db.update_campaign.await_args.kwargs["state"] == "syncing"
    assert db.update_campaign.await_args.kwargs["source_sync_status"] == "in_progress"
    enqueue.assert_awaited_once_with(FunctionNames.SYNC_CAMPAIGN_SOURCE, 9)
    breaker.reset.assert_awaited_once_with(9)


async def test_failed_campaign_with_queued_rows_resumes_processing():
    campaign = SimpleNamespace(id=9, state="failed")
    db = _db(campaign, queued_runs=4)
    breaker = _breaker()
    enqueue = AsyncMock()

    with (
        patch.object(runner_module, "db_client", db),
        patch.object(runner_module, "circuit_breaker", breaker),
        patch.object(runner_module, "enqueue_job", enqueue),
    ):
        await CampaignRunnerService().resume_campaign(9)

    assert db.update_campaign.await_args.kwargs["state"] == "running"
    enqueue.assert_not_awaited()
    breaker.reset.assert_awaited_once_with(9)


async def test_completed_campaign_cannot_be_resumed():
    campaign = SimpleNamespace(id=9, state="completed")
    db = _db(campaign)

    with patch.object(runner_module, "db_client", db):
        with pytest.raises(ValueError, match="paused.*failed"):
            await CampaignRunnerService().resume_campaign(9)

    db.update_campaign.assert_not_awaited()
