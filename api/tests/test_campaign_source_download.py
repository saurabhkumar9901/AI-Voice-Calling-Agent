"""Source file downloads must tolerate transient storage failures.

A single MinIO/network blip used to fail an entire campaign ("runner failed")
because the downloaded URL timed out once. Downloads now retry transport errors
and 5xx responses, and report a readable error when they finally give up.
"""

import sys
from types import ModuleType

import httpx
import pytest

from api.services.campaign.sources import download

SIGNED_URL = "http://minio:9000/voice-audio/campaigns/1/source.xlsx"


@pytest.fixture
def storage(monkeypatch):
    module = ModuleType("api.services.storage")

    class _Storage:
        async def aget_signed_url(self, *_args, **_kwargs):
            return SIGNED_URL

    module.storage_fs = _Storage()
    monkeypatch.setitem(sys.modules, "api.services.storage", module)
    return module.storage_fs


@pytest.fixture(autouse=True)
def _no_backoff(monkeypatch):
    monkeypatch.setattr(download, "DOWNLOAD_BACKOFF_SECONDS", 0)


def _use_handler(monkeypatch, handler):
    real_client = httpx.AsyncClient

    def _factory(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(download.httpx, "AsyncClient", _factory)


async def test_retries_transient_connect_failures(monkeypatch, storage):
    calls = []

    def handler(request):
        calls.append(request.url)
        if len(calls) < download.DOWNLOAD_ATTEMPTS:
            raise httpx.ConnectTimeout("connect timed out", request=request)
        return httpx.Response(200, content=b"excel-bytes", request=request)

    _use_handler(monkeypatch, handler)

    content = await download.fetch_source_bytes("source.xlsx", "Excel")

    assert content == b"excel-bytes"
    assert len(calls) == download.DOWNLOAD_ATTEMPTS


async def test_retries_server_errors(monkeypatch, storage):
    calls = []

    def handler(request):
        calls.append(request.url)
        if len(calls) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, content=b"csv,bytes", request=request)

    _use_handler(monkeypatch, handler)

    assert await download.fetch_source_bytes("source.csv", "CSV") == b"csv,bytes"
    assert len(calls) == 2


async def test_gives_up_with_a_readable_error(monkeypatch, storage):
    calls = []

    def handler(request):
        calls.append(request.url)
        raise httpx.ConnectTimeout("", request=request)

    _use_handler(monkeypatch, handler)

    with pytest.raises(download.SourceFetchError) as excinfo:
        await download.fetch_source_bytes("source.xlsx", "Excel")

    # Connect timeouts have an empty str(); the type keeps the error useful.
    assert "ConnectTimeout" in str(excinfo.value)
    assert len(calls) == download.DOWNLOAD_ATTEMPTS


async def test_does_not_retry_missing_files(monkeypatch, storage):
    calls = []

    def handler(request):
        calls.append(request.url)
        return httpx.Response(404, request=request)

    _use_handler(monkeypatch, handler)

    with pytest.raises(download.SourceFetchError):
        await download.fetch_source_bytes("source.xlsx", "Excel")

    assert len(calls) == 1


async def test_reports_missing_signed_url(monkeypatch):
    module = ModuleType("api.services.storage")

    class _Storage:
        async def aget_signed_url(self, *_args, **_kwargs):
            return None

    module.storage_fs = _Storage()
    monkeypatch.setitem(sys.modules, "api.services.storage", module)

    with pytest.raises(download.SourceFetchError) as excinfo:
        await download.fetch_source_bytes("missing.xlsx", "Excel")

    assert "missing.xlsx" in str(excinfo.value)
