"""Public download endpoints for workflow recordings and transcripts.

These endpoints provide secure, token-based public access to workflow artifacts
without requiring authentication. Tokens are generated on-demand when webhooks
are executed and included in the webhook payload.

Bytes are streamed through the API origin (instead of redirecting to raw
storage URLs) so links work in browsers even when the storage backend is not
directly reachable — e.g. MinIO behind HTTP/internal DNS on Azure fronted by
HTTPS. This mirrors the server-side upload proxy pattern in s3_signed_url.py.
"""

import os
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from loguru import logger
from starlette.background import BackgroundTask

from api.db import db_client
from api.utils.call_report import download_artifact_to_temp

router = APIRouter(prefix="/public/download")


@router.get("/workflow/{token}/{artifact_type}")
async def download_workflow_artifact(
    token: str,
    artifact_type: Literal["recording", "transcript"],
    inline: bool = Query(
        default=False, description="Display inline in browser instead of download"
    ),
):
    """Download a workflow recording or transcript via public access token.

    This endpoint:
    1. Validates the public access token
    2. Looks up the corresponding workflow run
    3. Streams the artifact bytes with an inline/attachment disposition

    Args:
        token: The public access token (UUID format)
        artifact_type: Type of artifact - "recording" or "transcript"
        inline: If true, sets Content-Disposition to inline for browser preview

    Returns:
        FileResponse streaming the artifact bytes

    Raises:
        HTTPException 404: If token is invalid or artifact not found
    """
    # 1. Lookup workflow run by token
    workflow_run = await db_client.get_workflow_run_by_public_token(token)
    if not workflow_run:
        logger.warning(f"Invalid public access token: {token[:8]}...")
        raise HTTPException(status_code=404, detail="Invalid or expired token")

    # 2. Get file path based on artifact type
    if artifact_type == "recording":
        file_path = workflow_run.recording_url
        media_type, suffix = "audio/wav", ".wav"
    else:  # transcript
        file_path = workflow_run.transcript_url
        media_type, suffix = "text/plain; charset=utf-8", ".txt"

    if not file_path:
        logger.warning(
            f"Artifact not found: type={artifact_type}, workflow_run_id={workflow_run.id}"
        )
        raise HTTPException(
            status_code=404,
            detail=f"No {artifact_type} available for this workflow run",
        )

    # 3. Download from the run's storage backend to a temp file and stream it.
    tmp_path = await download_artifact_to_temp(
        file_path, getattr(workflow_run, "storage_backend", None), suffix
    )
    if not tmp_path:
        logger.error(
            f"Failed to fetch artifact from storage: {file_path} "
            f"(run {workflow_run.id})"
        )
        raise HTTPException(status_code=404, detail="Artifact file not found")

    logger.info(
        f"Streaming {artifact_type}: workflow_run_id={workflow_run.id}, token={token[:8]}..."
    )

    filename = f"run-{workflow_run.id}-{artifact_type}{suffix}"
    disposition = "inline" if inline else "attachment"

    return FileResponse(
        path=tmp_path,
        media_type=media_type,
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
        background=BackgroundTask(os.remove, tmp_path),
    )
