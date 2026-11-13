import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from loguru import logger

# Dialing code applied to phone numbers that do not carry one.
DEFAULT_DIALING_CODE = "91"


@dataclass
class ValidationError:
    """Represents a validation error with details."""

    message: str
    invalid_rows: Optional[List[int]] = None


@dataclass
class ValidationResult:
    """Result of source validation."""

    is_valid: bool
    error: Optional[ValidationError] = None
    headers: Optional[List[str]] = field(default=None, repr=False)
    rows: Optional[List[List[str]]] = field(default=None, repr=False)


class CampaignSourceSyncService(ABC):
    """Base class for campaign data source synchronization"""

    @staticmethod
    def normalize_headers(headers: List[str]) -> List[str]:
        """Normalize headers by stripping whitespace and lowercasing."""
        return [h.strip().lower() for h in headers]

    @staticmethod
    def normalize_phone_number(value: str) -> str:
        """Normalize a phone number to E.164, defaulting to +91.

        Users often paste numbers without a country code, with a trunk prefix
        (leading 0), or with spaces/dashes/parentheses. Returns "" when the
        value cannot be turned into a dialable number so the caller can drop it.
        """
        cleaned = (value or "").strip().lstrip("'").strip()
        if not cleaned or not re.fullmatch(r"\+?[\d\s\-().]+", cleaned):
            return ""

        digits = re.sub(r"\D", "", cleaned)
        if not digits:
            return ""

        # Numbers that already carry a country code keep it as-is.
        if cleaned.startswith("+"):
            return f"+{digits}" if len(digits) <= 15 else ""

        digits = digits.lstrip("0")
        if not digits:
            return ""
        # At most 10 digits means no country code was supplied.
        if len(digits) <= 10:
            return f"+{DEFAULT_DIALING_CODE}{digits}"
        return f"+{digits}" if len(digits) <= 15 else ""

    @classmethod
    def sanitize_source_rows(
        cls, headers: List[str], rows: List[List[str]]
    ) -> tuple[List[str], List[List[str]]]:
        """Clean source rows so a campaign can start without manual edits.

        - Adds the country code to phone numbers that lack one.
        - Drops rows whose phone number is empty or unusable.
        - Drops duplicate phone numbers, keeping the first occurrence.
        """
        normalized_headers = cls.normalize_headers(headers)
        if "phone_number" not in normalized_headers:
            return normalized_headers, rows

        phone_idx = normalized_headers.index("phone_number")
        seen_phones: Set[str] = set()
        sanitized_rows: List[List[str]] = []
        dropped_empty = 0
        dropped_duplicate = 0

        for row in rows:
            padded_row = list(row) + [""] * (len(normalized_headers) - len(row))
            phone_number = cls.normalize_phone_number(padded_row[phone_idx])

            if not phone_number:
                dropped_empty += 1
                continue
            if phone_number in seen_phones:
                dropped_duplicate += 1
                continue

            seen_phones.add(phone_number)
            padded_row[phone_idx] = phone_number
            sanitized_rows.append(padded_row)

        if dropped_empty or dropped_duplicate:
            logger.info(
                f"Cleaned source data: dropped {dropped_empty} rows without a "
                f"usable phone number and {dropped_duplicate} duplicate rows; "
                f"{len(sanitized_rows)} rows remain"
            )

        return normalized_headers, sanitized_rows

    @classmethod
    def validate_source_data(
        cls, headers: List[str], rows: List[List[str]]
    ) -> ValidationResult:
        """
        Validate source data for campaign creation.

        Phone numbers are normalized in place (country code added, duplicates
        and empty numbers removed) so the returned rows are ready to sync.

        Args:
            headers: List of column headers
            rows: List of data rows (excluding header)

        Returns:
            ValidationResult with is_valid=True if valid, or error details if invalid
        """
        normalized_headers = cls.normalize_headers(headers)

        # Check for phone_number column
        if "phone_number" not in normalized_headers:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(
                    message="Source must contain a 'phone_number' column"
                ),
            )

        normalized_headers, sanitized_rows = cls.sanitize_source_rows(headers, rows)

        if rows and not sanitized_rows:
            return ValidationResult(
                is_valid=False,
                error=ValidationError(
                    message="No valid phone numbers found. Every row is either "
                    "missing a phone number or duplicates another row."
                ),
            )

        return ValidationResult(
            is_valid=True, headers=normalized_headers, rows=sanitized_rows
        )

    @staticmethod
    def validate_template_columns(
        headers: List[str],
        rows: List[List[str]],
        required_columns: Set[str],
    ) -> ValidationResult:
        """Validate that template variable columns exist and are non-empty in all rows."""
        normalized_headers = CampaignSourceSyncService.normalize_headers(headers)

        # Check for missing columns
        missing = required_columns - set(normalized_headers)
        if missing:
            missing_str = ", ".join(f"'{c}'" for c in sorted(missing))
            return ValidationResult(
                is_valid=False,
                error=ValidationError(
                    message=f"Workflow uses template variables that are missing from the source data: {missing_str}. "
                    "Add the missing columns or remove them from the workflow."
                ),
            )

        # Check for empty values in required columns
        col_indices = {col: normalized_headers.index(col) for col in required_columns}

        for col, idx in col_indices.items():
            empty_rows = []
            for row_idx, row in enumerate(rows, start=2):
                if len(row) <= idx or not row[idx].strip():
                    empty_rows.append(row_idx)

            if empty_rows:
                if len(empty_rows) > 5:
                    rows_str = f"{', '.join(map(str, empty_rows[:5]))} and {len(empty_rows) - 5} more"
                else:
                    rows_str = ", ".join(map(str, empty_rows))

                return ValidationResult(
                    is_valid=False,
                    error=ValidationError(
                        message=f"Template variable '{col}' is empty in rows: {rows_str}. "
                        "All template variables used in the workflow must have values in every row.",
                        invalid_rows=empty_rows,
                    ),
                )

        return ValidationResult(is_valid=True)

    @abstractmethod
    async def validate_source(
        self, source_id: str, organization_id: Optional[int] = None
    ) -> ValidationResult:
        """Validate source data before campaign creation."""
        pass

    @abstractmethod
    async def sync_source_data(self, campaign_id: int) -> int:
        """
        Fetches data from source and creates queued_runs
        Each record gets a unique source_uuid based on source type
        Returns: number of records synced
        """
        pass

    async def get_source_credentials(
        self, organization_id: int, source_type: str
    ) -> Dict[str, Any]:
        """Gets OAuth tokens or API credentials via Nango"""
        # This would be implemented to work with Nango service
        # For now, returning placeholder
        logger.info(
            f"Getting credentials for org {organization_id}, source {source_type}"
        )
        return {}
