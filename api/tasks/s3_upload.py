import os
import tempfile
from datetime import datetime, timezone
from typing import Optional

from loguru import logger

from api.db import db_client
from api.services.call_insights import generate_call_insights
from api.services.call_summarization import MIN_TRANSCRIPT_CHARS, generate_call_summary
from api.services.call_transcription import transcribe_call_audio
from api.services.callbacks import (
    get_user_timezone,
    parse_iso_to_utc,
    schedule_callback_for_run,
)
from api.services.pricing.workflow_run_cost import calculate_workflow_run_cost
from api.services.storage import get_current_storage_backend, storage_fs
from api.tasks.run_integrations import run_integrations_post_workflow_run
from pipecat.utils.run_context import set_current_run_id


def _transcript_needs_regeneration(transcript_text: Optional[str]) -> bool:
    """True when the transcript should be (re)generated from the recording.

    Covers missing/too-short transcripts and one-sided ones (user lines only,
    no assistant/agent lines) as produced by S2S pipelines. Two-sided live
    transcripts from traditional pipelines are kept as-is.
    """
    if not transcript_text or len(transcript_text.strip()) < MIN_TRANSCRIPT_CHARS:
        return True
    lowered = transcript_text.lower()
    return "assistant:" not in lowered and "agent:" not in lowered


async def upload_voicemail_audio_to_s3(
    _ctx,
    workflow_run_id: int,
    temp_file_path: str,
    s3_key: str,
):
    """Upload voicemail detection audio from temp file to S3.

    Handles voicemail-specific paths and doesn't update the workflow run's
    recording_url field.

    Args:
        _ctx: ARQ context (unused)
        workflow_run_id: The workflow run ID
        temp_file_path: Path to the temporary WAV file
        s3_key: The S3 key where the file should be uploaded
    """
    run_id = str(workflow_run_id)
    set_current_run_id(run_id)

    logger.info(f"Starting voicemail audio upload to S3 from {temp_file_path}")

    try:
        # Verify temp file exists
        if not os.path.exists(temp_file_path):
            logger.error(f"Temp voicemail audio file not found: {temp_file_path}")
            raise FileNotFoundError(
                f"Temp voicemail audio file not found: {temp_file_path}"
            )

        file_size = os.path.getsize(temp_file_path)
        logger.debug(f"Voicemail audio file size: {file_size} bytes")

        # Upload to S3
        upload_ok = await storage_fs.aupload_file(temp_file_path, s3_key)

        if upload_ok:
            logger.info(f"Successfully uploaded voicemail audio to S3: {s3_key}")
        else:
            logger.error(
                f"Failed to upload voicemail audio to S3 for workflow {workflow_run_id}"
            )
            raise Exception(f"S3 upload failed for {s3_key}")

    except Exception as e:
        logger.error(
            f"Error uploading voicemail audio to S3 for workflow {workflow_run_id}: {e}"
        )
        raise
    finally:
        # Clean up temp file
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.debug(f"Cleaned up temp voicemail audio file: {temp_file_path}")
            except Exception as e:
                logger.warning(
                    f"Failed to clean up temp voicemail audio file {temp_file_path}: {e}"
                )


async def process_workflow_completion(
    _ctx,
    workflow_run_id: int,
    audio_temp_path: Optional[str] = None,
    transcript_temp_path: Optional[str] = None,
):
    """Process workflow completion: upload artifacts and run integrations.

    This task combines audio upload, transcript upload, and webhook integrations
    into a single sequential task to ensure integrations run after uploads complete.

    Args:
        _ctx: ARQ context (unused)
        workflow_run_id: The workflow run ID
        audio_temp_path: Optional path to temp audio file
        transcript_temp_path: Optional path to temp transcript file
    """
    run_id = str(workflow_run_id)
    set_current_run_id(run_id)

    logger.info(f"Processing workflow completion for run {workflow_run_id}")

    storage_backend = get_current_storage_backend()

    # Keep transcript text in memory so we can summarize after upload,
    # even though the temp file is deleted in the finally block below.
    transcript_text: Optional[str] = None

    # Step 1: Upload audio if provided
    if audio_temp_path:
        try:
            if os.path.exists(audio_temp_path):
                file_size = os.path.getsize(audio_temp_path)
                logger.debug(f"Audio file size: {file_size} bytes")

                recording_url = f"recordings/{workflow_run_id}.wav"
                logger.info(
                    f"Uploading audio to {storage_backend.name} - workflow_run_id: {workflow_run_id}"
                )

                await storage_fs.aupload_file(audio_temp_path, recording_url)
                await db_client.update_workflow_run(
                    run_id=workflow_run_id,
                    recording_url=recording_url,
                    storage_backend=storage_backend.value,
                )
                logger.info(f"Successfully uploaded audio: {recording_url}")
            else:
                logger.warning(f"Audio temp file not found: {audio_temp_path}")
        except Exception as e:
            logger.error(f"Error uploading audio for workflow {workflow_run_id}: {e}")
        finally:
            if audio_temp_path and os.path.exists(audio_temp_path):
                try:
                    os.remove(audio_temp_path)
                    logger.debug(f"Cleaned up temp audio file: {audio_temp_path}")
                except Exception as e:
                    logger.warning(f"Failed to clean up temp audio file: {e}")

    # Step 2: Upload transcript if provided
    if transcript_temp_path:
        try:
            if os.path.exists(transcript_temp_path):
                file_size = os.path.getsize(transcript_temp_path)
                logger.debug(f"Transcript file size: {file_size} bytes")

                try:
                    with open(transcript_temp_path, encoding="utf-8") as f:
                        transcript_text = f.read()
                except Exception as e:
                    logger.warning(
                        f"Could not read transcript for summarization: {e}"
                    )

                transcript_url = f"transcripts/{workflow_run_id}.txt"
                logger.info(
                    f"Uploading transcript to {storage_backend.name} - workflow_run_id: {workflow_run_id}"
                )

                await storage_fs.aupload_file(transcript_temp_path, transcript_url)
                await db_client.update_workflow_run(
                    run_id=workflow_run_id,
                    transcript_url=transcript_url,
                    storage_backend=storage_backend.value,
                )
                logger.info(f"Successfully uploaded transcript: {transcript_url}")
            else:
                logger.warning(
                    f"Transcript temp file not found: {transcript_temp_path}"
                )
        except Exception as e:
            logger.error(
                f"Error uploading transcript for workflow {workflow_run_id}: {e}"
            )
        finally:
            if transcript_temp_path and os.path.exists(transcript_temp_path):
                try:
                    os.remove(transcript_temp_path)
                    logger.debug(
                        f"Cleaned up temp transcript file: {transcript_temp_path}"
                    )
                except Exception as e:
                    logger.warning(f"Failed to clean up temp transcript file: {e}")

    # Step 2b: Ensure a two-sided transcript exists. If the live transcript is
    # missing, too short, or one-sided (S2S pipelines only capture user lines
    # live; assistant audio never becomes text events), regenerate the full
    # diarized transcript from the recording via the configured LLM (same
    # approach as summaries). Decided on transcript *content*, not on whether
    # a transcript URL already exists, so reprocessing also heals old runs.
    transcript_regenerated = False
    if transcript_text is None:
        # No live text (e.g. reprocessing): reuse the stored transcript if any.
        try:
            existing_run = await db_client.get_workflow_run_by_id(workflow_run_id)
            if existing_run is not None and existing_run.transcript_url:
                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                    existing_path = tmp.name
                try:
                    if await storage_fs.adownload_file(
                        existing_run.transcript_url, existing_path
                    ):
                        with open(existing_path, encoding="utf-8") as f:
                            transcript_text = f.read() or None
                finally:
                    if os.path.exists(existing_path):
                        os.remove(existing_path)
        except Exception as e:
            logger.warning(
                f"Could not fetch existing transcript for workflow {workflow_run_id}: {e}"
            )

    if _transcript_needs_regeneration(transcript_text):
        try:
            workflow_run = await db_client.get_workflow_run_by_id(workflow_run_id)
            recording_key = (
                workflow_run.recording_url if workflow_run else None
            ) or f"recordings/{workflow_run_id}.wav"
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                download_path = tmp.name
            try:
                downloaded = await storage_fs.adownload_file(
                    recording_key, download_path
                )
                if downloaded and workflow_run is not None:
                    fallback_text = await transcribe_call_audio(
                        download_path, workflow_run
                    )
                    if fallback_text:
                        transcript_url = f"transcripts/{workflow_run_id}.txt"
                        with tempfile.NamedTemporaryFile(
                            mode="w", suffix=".txt", delete=False, encoding="utf-8"
                        ) as tf:
                            tf.write(fallback_text)
                            fallback_path = tf.name
                        try:
                            await storage_fs.aupload_file(
                                fallback_path, transcript_url
                            )
                            await db_client.update_workflow_run(
                                run_id=workflow_run_id,
                                transcript_url=transcript_url,
                                storage_backend=storage_backend.value,
                            )
                            logger.info(
                                f"Uploaded fallback transcript: {transcript_url}"
                            )
                            transcript_text = fallback_text
                            transcript_regenerated = True
                        finally:
                            if os.path.exists(fallback_path):
                                os.remove(fallback_path)
            finally:
                if os.path.exists(download_path):
                    os.remove(download_path)
        except Exception as e:
            logger.warning(
                f"Error in fallback audio transcription for workflow {workflow_run_id}: {e}"
            )

    # Step 2c: Generate call summary from transcript (S2S + traditional).
    # Runs after uploads so a slow/failed LLM call never blocks recordings.
    # Regenerates the summary when the transcript itself was regenerated.
    if transcript_text:
        try:
            workflow_run = await db_client.get_workflow_run_by_id(workflow_run_id)
            if workflow_run is not None and (
                not workflow_run.call_summary or transcript_regenerated
            ):
                summary = await generate_call_summary(workflow_run, transcript_text)
                if summary:
                    await db_client.update_workflow_run(
                        run_id=workflow_run_id,
                        call_summary=summary,
                        call_summary_generated_at=datetime.now(timezone.utc),
                    )
        except Exception as e:
            logger.warning(
                f"Error generating call summary for workflow {workflow_run_id}: {e}"
            )

    # Step 2d: Post-call insights — callback request + action items (agent LLM)
    # and caller sentiment (dedicated local NLP model). Runs after uploads so
    # slow/failed analysis never blocks recordings.
    if transcript_text:
        try:
            insight_run = await db_client.get_workflow_run_by_id(workflow_run_id)
            if insight_run is not None:
                insight_user_id = (
                    insight_run.workflow.user_id
                    if insight_run.workflow and insight_run.workflow.user
                    else None
                )
                user_tz = await get_user_timezone(insight_user_id)
                call_time_iso = (
                    insight_run.created_at.isoformat()
                    if insight_run.created_at
                    else datetime.now(timezone.utc).isoformat()
                )
                insights = await generate_call_insights(
                    insight_run, transcript_text, call_time_iso, user_tz
                )

                actions = insights.get("action_items") or []
                sentiment = insights.get("sentiment")
                insight_updates = {}
                if actions and not insight_run.action_items:
                    insight_updates["action_items"] = actions
                if sentiment and not insight_run.sentiment:
                    insight_updates["sentiment"] = sentiment
                if insight_updates:
                    await db_client.update_workflow_run(
                        run_id=workflow_run_id, **insight_updates
                    )

                # Safety net: schedule a callback the live tool may have missed.
                callback_at = insights.get("callback_at_iso")
                if callback_at:
                    requested = parse_iso_to_utc(callback_at, user_tz)
                    if requested is not None:
                        await schedule_callback_for_run(
                            insight_run, requested, note=None
                        )
        except Exception as e:
            logger.warning(
                f"Error generating call insights for workflow {workflow_run_id}: {e}"
            )

    # Step 3: Run integrations including QA analysis (after uploads are complete)
    try:
        await run_integrations_post_workflow_run(_ctx, workflow_run_id)
    except Exception as e:
        logger.error(f"Error running integrations for workflow {workflow_run_id}: {e}")

    # Step 4: Calculate cost after integrations (so QA token usage is included)
    try:
        await calculate_workflow_run_cost(workflow_run_id)
    except Exception as e:
        logger.error(f"Error calculating cost for workflow {workflow_run_id}: {e}")

    logger.info(f"Completed workflow completion processing for run {workflow_run_id}")
