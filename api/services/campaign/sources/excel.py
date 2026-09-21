import hashlib
import re
from datetime import date, datetime
from io import BytesIO
from typing import List, Optional

import httpx
from loguru import logger

from api.db import db_client
from api.services.campaign.source_sync import (
    CampaignSourceSyncService,
    ValidationError,
    ValidationResult,
)
from api.services.storage import storage_fs

# Reserved context variable names produced from the column mapping.
MAPPED_NAME_KEY = "name"
MAPPED_PHONE_KEY = "phone_number"
MAPPED_CITY_KEY = "city"


def _cell_to_str(value) -> str:
    """Convert an openpyxl cell value to a clean string."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def _normalize_phone_number(value: str) -> str:
    """Normalize a phone number from an Excel cell to E.164 with + prefix.

    Excel treats a leading "+" as a formula, so users type numbers without it
    (and often with spaces/dashes). Strip common formatting and prepend "+"
    when the remaining digits look like an international number (7-15 digits).
    Anything else is returned stripped but untouched so downstream validation
    flags the exact row instead of silently corrupting it.
    """
    cleaned = re.sub(r"[\s\-().]", "", (value or "").strip())
    if re.fullmatch(r"\+?\d{7,15}", cleaned):
        return cleaned if cleaned.startswith("+") else f"+{cleaned}"
    return (value or "").strip()


class ExcelSyncService(CampaignSourceSyncService):
    """Implementation for Excel (.xlsx/.xls) file synchronization."""

    async def _fetch_excel_data(self, file_key: str) -> List[List[str]]:
        """Download and parse the first sheet of an Excel file from storage.

        Returns all rows including the header row.
        """
        signed_url = await storage_fs.aget_signed_url(
            file_key, expiration=3600, use_internal_endpoint=True
        )

        if not signed_url:
            raise ValueError(f"Failed to access Excel file: {file_key}")

        async with httpx.AsyncClient() as client:
            try:
                response = await client.get(signed_url)
                response.raise_for_status()
                content = response.content
            except httpx.HTTPError as e:
                logger.error(f"Failed to download Excel file: {e} for url: {signed_url}")
                raise ValueError(f"Failed to download Excel file from storage: {str(e)}")

        return self._parse_excel(content, file_key)

    def _parse_excel(self, content: bytes, file_key: str = "") -> List[List[str]]:
        """Parse Excel bytes (first sheet) into rows of strings."""
        try:
            from openpyxl import load_workbook
        except ImportError:
            raise ValueError("Excel support is not installed on the server")

        try:
            workbook = load_workbook(BytesIO(content), read_only=True, data_only=True)
        except Exception as e:
            logger.error(f"Failed to parse Excel file {file_key}: {e}")
            raise ValueError(
                "Invalid Excel file. Please upload a valid .xlsx or .xls workbook."
            )

        try:
            sheet = workbook.worksheets[0]
            rows = [
                [_cell_to_str(cell) for cell in row]
                for row in sheet.iter_rows(values_only=True)
            ]
        finally:
            workbook.close()

        # Drop fully-empty rows (trailing blanks are common in Excel).
        rows = [row for row in rows if any(cell.strip() for cell in row)]
        return rows

    async def get_preview(
        self, file_key: str, max_rows: int = 5
    ) -> dict:
        """Return headers, sample rows, and total row count for column mapping."""
        excel_data = await self._fetch_excel_data(file_key)
        if not excel_data:
            raise ValueError("Excel file is empty")
        headers = [h if h else f"Column {i + 1}" for i, h in enumerate(excel_data[0])]
        data_rows = excel_data[1:]
        return {
            "headers": headers,
            "sample_rows": data_rows[:max_rows],
            "total_rows": len(data_rows),
        }

    def _resolve_mapping(
        self, headers: List[str], mapping: dict
    ) -> dict[str, int]:
        """Resolve mapped header names to column indices (exact, then normalized)."""
        normalized = CampaignSourceSyncService.normalize_headers(headers)

        def find(wanted: str) -> Optional[int]:
            if wanted in headers:
                return headers.index(wanted)
            want_norm = wanted.strip().lower()
            if want_norm in normalized:
                return normalized.index(want_norm)
            return None

        resolved = {}
        for role in ("name_col", "phone_col", "city_col"):
            wanted = (mapping.get(role) or "").strip()
            if not wanted:
                raise ValueError(f"Column mapping is missing '{role}'")
            idx = find(wanted)
            if idx is None:
                raise ValueError(
                    f"Mapped column '{wanted}' was not found in the Excel headers"
                )
            resolved[role] = idx
        if len({resolved["name_col"], resolved["phone_col"], resolved["city_col"]}) < 3:
            raise ValueError("Name, Phone Number and City must map to different columns")
        return resolved

    def apply_mapping(
        self, headers: List[str], rows: List[List[str]], mapping: dict
    ) -> tuple[List[str], List[List[str]]]:
        """Apply a column mapping, returning mapped (headers, rows).

        Output context variables: name, phone_number, city, plus every other
        column under its normalized header name.
        """
        resolved = self._resolve_mapping(headers, mapping)
        extra_indices = [
            i
            for i in range(len(headers))
            if i
            not in (resolved["name_col"], resolved["phone_col"], resolved["city_col"])
        ]
        normalized = CampaignSourceSyncService.normalize_headers(headers)

        mapped_headers = [MAPPED_NAME_KEY, MAPPED_PHONE_KEY, MAPPED_CITY_KEY] + [
            normalized[i] or f"column_{i + 1}" for i in extra_indices
        ]
        mapped_rows = []
        for row in rows:
            padded = list(row) + [""] * (len(headers) - len(row))
            mapped_rows.append(
                [
                    padded[resolved["name_col"]].strip(),
                    # Excel mangles leading "+" (formula parsing), so users type
                    # numbers without it — normalize to E.164 here.
                    _normalize_phone_number(padded[resolved["phone_col"]]),
                    padded[resolved["city_col"]].strip(),
                ]
                + [padded[i].strip() for i in extra_indices]
            )
        return mapped_headers, mapped_rows

    async def validate_source(
        self, source_id: str, organization_id: Optional[int] = None
    ) -> ValidationResult:
        """Structural validation only (column mapping is applied later)."""
        try:
            excel_data = await self._fetch_excel_data(source_id)
        except ValueError as e:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(message=str(e)),
            )

        if not excel_data or len(excel_data) < 2:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(
                    message="Excel file must have a header row and at least one data row"
                ),
            )

        headers = [h if h else f"Column {i + 1}" for i, h in enumerate(excel_data[0])]
        return ValidationResult(
            is_valid=True, headers=headers, rows=excel_data[1:]
        )

    async def get_mapped_data(
        self, source_id: str, mapping: dict
    ) -> tuple[List[str], List[List[str]]]:
        """Fetch + validate + map Excel data. Raises ValueError on any problem."""
        mapped_validation = await self.validate_mapped_source(source_id, mapping)
        if not mapped_validation.is_valid:
            raise ValueError(mapped_validation.error.message)

        excel_data = await self._fetch_excel_data(source_id)
        headers = [h if h else f"Column {i + 1}" for i, h in enumerate(excel_data[0])]
        return self.apply_mapping(headers, excel_data[1:], mapping)

    async def validate_mapped_source(
        self, source_id: str, mapping: dict
    ) -> ValidationResult:
        """Full validation (phone format, duplicates, template vars) on mapped data."""
        try:
            excel_data = await self._fetch_excel_data(source_id)
        except ValueError as e:
            return ValidationResult(
                is_valid=False, error=ValidationError(message=str(e))
            )

        if not excel_data or len(excel_data) < 2:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(message="Excel file has no data rows"),
            )

        headers = [h if h else f"Column {i + 1}" for i, h in enumerate(excel_data[0])]
        try:
            mapped_headers, mapped_rows = self.apply_mapping(
                headers, excel_data[1:], mapping
            )
        except ValueError as e:
            return ValidationResult(
                is_valid=False, error=ValidationError(message=str(e))
            )

        return self.validate_source_data(mapped_headers, mapped_rows)

    async def sync_source_data(self, campaign_id: int) -> int:
        """Fetch Excel data, apply the stored column mapping, create queued_runs."""
        campaign = await db_client.get_campaign_by_id(campaign_id)
        if not campaign:
            raise ValueError(f"Campaign {campaign_id} not found")

        mapping = (campaign.orchestrator_metadata or {}).get("column_mapping")
        if not mapping:
            raise ValueError(
                f"Campaign {campaign_id} has no column mapping configured"
            )

        file_key = campaign.source_id
        excel_data = await self._fetch_excel_data(file_key)

        if not excel_data or len(excel_data) < 2:
            logger.warning(f"No data found in Excel for campaign {campaign_id}")
            return 0

        headers = [h if h else f"Column {i + 1}" for i, h in enumerate(excel_data[0])]
        mapped_headers, mapped_rows = self.apply_mapping(headers, excel_data[1:], mapping)

        # Reuse phone-format and duplicate validation on the mapped data.
        validation = self.validate_source_data(mapped_headers, mapped_rows)
        if not validation.is_valid:
            raise ValueError(
                f"Excel data failed validation: {validation.error.message}"
            )

        file_hash = hashlib.md5(file_key.encode()).hexdigest()[:8]

        queued_runs = []
        for idx, row_values in enumerate(mapped_rows, 1):
            padded_row = row_values + [""] * (len(mapped_headers) - len(row_values))
            context_vars = dict(zip(mapped_headers, padded_row))

            if not context_vars.get("phone_number"):
                logger.debug(f"Skipping row {idx}: no phone_number")
                continue

            queued_runs.append(
                {
                    "campaign_id": campaign_id,
                    "source_uuid": f"excel_{file_hash}_row_{idx}",
                    "context_variables": context_vars,
                    "state": "queued",
                }
            )

        if queued_runs:
            await db_client.bulk_create_queued_runs(queued_runs)
            logger.info(
                f"Created {len(queued_runs)} queued runs for campaign {campaign_id}"
            )

        await db_client.update_campaign(
            campaign_id=campaign_id,
            total_rows=len(queued_runs),
            source_sync_status="completed",
        )

        return len(queued_runs)
