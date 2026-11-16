import csv
import hashlib
from io import StringIO
from typing import List, Optional

from loguru import logger

from api.db import db_client
from api.services.campaign.source_sync import (
    CampaignSourceSyncService,
    ValidationError,
    ValidationResult,
)
from api.services.campaign.sources.download import fetch_source_bytes


class CSVSyncService(CampaignSourceSyncService):
    """Implementation for CSV file synchronization"""

    async def _fetch_csv_data(self, file_key: str) -> List[List[str]]:
        """Download and parse CSV file from storage. Returns all rows including header."""
        content = await fetch_source_bytes(file_key, "CSV")
        return self._parse_csv(content.decode("utf-8-sig", errors="replace"))

    async def validate_source(
        self, source_id: str, organization_id: Optional[int] = None
    ) -> ValidationResult:
        """Validate a CSV source file for campaign creation."""
        try:
            csv_data = await self._fetch_csv_data(source_id)
        except ValueError as e:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(message=str(e)),
            )

        if not csv_data or len(csv_data) < 2:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(
                    message="CSV file must have a header row and at least one data row"
                ),
            )

        headers = csv_data[0]
        data_rows = csv_data[1:]

        return self.validate_source_data(headers, data_rows)

    async def sync_source_data(self, campaign_id: int) -> int:
        """
        Fetches data from CSV file in S3/MinIO and creates queued_runs
        """
        # Get campaign
        campaign = await db_client.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        file_key = campaign.source_id
        csv_data = await self._fetch_csv_data(file_key)

        if not csv_data or len(csv_data) < 2:
            logger.warning(f"No data found in CSV for campaign {campaign_id}")
            return 0

        headers, rows = self.sanitize_source_rows(csv_data[0], csv_data[1:])

        # Create hash of file_key for consistent source_uuid prefix
        file_hash = hashlib.md5(file_key.encode()).hexdigest()[:8]

        # Convert to queued_runs
        queued_runs = []
        for idx, row_values in enumerate(rows, 1):
            # Pad row to match headers length
            padded_row = row_values + [""] * (len(headers) - len(row_values))

            # Create context variables dict
            context_vars = dict(zip(headers, padded_row))

            # Generate unique source UUID: csv_{hash(source_id)}_row_{idx}
            source_uuid = f"csv_{file_hash}_row_{idx}"

            queued_runs.append(
                {
                    "campaign_id": campaign_id,
                    "source_uuid": source_uuid,
                    "context_variables": context_vars,
                    "state": "queued",
                }
            )

        # Bulk insert
        if queued_runs:
            await db_client.bulk_create_queued_runs(queued_runs)
            logger.info(
                f"Created {len(queued_runs)} queued runs for campaign {campaign_id}"
            )

        # Update campaign total_rows
        await db_client.update_campaign(
            campaign_id=campaign_id,
            total_rows=len(queued_runs),
            source_sync_status="completed",
        )

        return len(queued_runs)

    def _parse_csv(self, csv_content: str) -> List[List[str]]:
        """Parse CSV content into rows"""
        try:
            csv_file = StringIO(csv_content)
            reader = csv.reader(csv_file)
            return list(reader)
        except Exception as e:
            logger.error(f"Failed to parse CSV: {e}")
            raise ValueError(f"Invalid CSV format: {str(e)}")
