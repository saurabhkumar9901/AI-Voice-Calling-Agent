"""Download campaign source files from storage with bounded retries.

Source syncs run on the shared ARQ worker, so a transient storage/network blip
must not fail an entire campaign. Transport errors and 5xx responses are
retried a few times before the sync gives up.
"""

import asyncio

import httpx
from loguru import logger

# A hung storage endpoint should surface as an error quickly. The defaults
# (5s connect, no read timeout) are too eager on a busy worker and too patient
# on a stalled one.
DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
DOWNLOAD_ATTEMPTS = 3
DOWNLOAD_BACKOFF_SECONDS = 1.0


class SourceFetchError(ValueError):
    """Transient failure while fetching a campaign source file from storage.

    Subclasses ``ValueError`` so existing validation callers keep treating it
    as a bad source, while the sync task can recognise it as retryable.
    """


def _is_transient(error: httpx.HTTPError) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        return error.response.status_code >= 500
    return isinstance(error, httpx.TransportError)


def _describe(error: Exception) -> str:
    """Include the exception type: str(connect timeouts) is often empty."""
    message = str(error).strip()
    return f"{type(error).__name__}: {message}" if message else type(error).__name__


async def fetch_source_bytes(file_key: str, kind: str) -> bytes:
    """Download a source file from storage. Raises ``SourceFetchError``."""
    # Imported lazily: keeps this helper (and the pure validation helpers that
    # share its package) importable without storage configuration.
    from api.services.storage import storage_fs

    signed_url = await storage_fs.aget_signed_url(
        file_key, expiration=3600, use_internal_endpoint=True
    )
    if not signed_url:
        raise SourceFetchError(f"Failed to access {kind} file: {file_key}")

    last_error: Exception | None = None
    async with httpx.AsyncClient(
        timeout=DOWNLOAD_TIMEOUT, follow_redirects=True
    ) as client:
        for attempt in range(1, DOWNLOAD_ATTEMPTS + 1):
            try:
                response = await client.get(signed_url)
                response.raise_for_status()
                return response.content
            except httpx.HTTPError as e:
                last_error = e
                if attempt == DOWNLOAD_ATTEMPTS or not _is_transient(e):
                    break
                delay = DOWNLOAD_BACKOFF_SECONDS * (2 ** (attempt - 1))
                logger.warning(
                    f"Failed to download {kind} file from storage "
                    f"(attempt {attempt}/{DOWNLOAD_ATTEMPTS}): {_describe(e)}; "
                    f"retrying in {delay:.0f}s"
                )
                await asyncio.sleep(delay)

    if last_error is None:  # defensive: the loop always exits via break
        raise SourceFetchError(f"Failed to download {kind} file from storage")

    logger.error(
        f"Failed to download {kind} file: {_describe(last_error)} "
        f"for url: {signed_url}"
    )
    raise SourceFetchError(
        f"Failed to download {kind} file from storage: {_describe(last_error)}"
    )
