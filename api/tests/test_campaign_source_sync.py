from api.services.campaign.source_sync import CampaignSourceSyncService

PHONE_HEADERS = ["name", "phone_number", "city"]


class TestNormalizePhoneNumber:
    def test_adds_default_country_code_to_local_number(self):
        assert (
            CampaignSourceSyncService.normalize_phone_number("9876543210")
            == "+919876543210"
        )

    def test_keeps_number_that_already_has_country_code(self):
        assert (
            CampaignSourceSyncService.normalize_phone_number("919876543210")
            == "+919876543210"
        )

    def test_keeps_existing_plus_and_strips_formatting(self):
        assert (
            CampaignSourceSyncService.normalize_phone_number("+91 98765-43210")
            == "+919876543210"
        )

    def test_replaces_trunk_prefix_zero(self):
        assert (
            CampaignSourceSyncService.normalize_phone_number("09876543210")
            == "+919876543210"
        )

    def test_does_not_prefix_country_code_when_number_has_one(self):
        assert (
            CampaignSourceSyncService.normalize_phone_number("14155552671")
            == "+14155552671"
        )

    def test_returns_empty_for_missing_or_unusable_values(self):
        for value in ("", "   ", "abc", "+", "1234567890123456"):
            assert CampaignSourceSyncService.normalize_phone_number(value) == ""


class TestSanitizeSourceRows:
    def test_normalizes_deduplicates_and_drops_empty_phone_numbers(self):
        rows = [
            ["Alice", "9876543210", "Pune"],
            ["Bob", "+91 98765 43210", "Pune"],  # duplicate of Alice
            ["Carol", "", "Mumbai"],  # no phone number
            ["Dave", "919123456789", "Delhi"],
            ["Eve"],  # missing phone column value
        ]

        headers, sanitized = CampaignSourceSyncService.sanitize_source_rows(
            PHONE_HEADERS, rows
        )

        assert headers == PHONE_HEADERS
        assert sanitized == [
            ["Alice", "+919876543210", "Pune"],
            ["Dave", "+919123456789", "Delhi"],
        ]

    def test_normalized_header_spellings_are_matched(self):
        headers, sanitized = CampaignSourceSyncService.sanitize_source_rows(
            ["Name", " Phone_Number ", "City"], [["Alice", "9876543210", "Pune"]]
        )

        assert headers == PHONE_HEADERS
        assert sanitized[0][1] == "+919876543210"


class TestValidateSourceData:
    def test_returns_cleaned_rows_so_no_user_action_is_needed(self):
        result = CampaignSourceSyncService.validate_source_data(
            PHONE_HEADERS,
            [
                ["Alice", "9876543210", "Pune"],
                ["Bob", "09876543210", "Pune"],
            ],
        )

        assert result.is_valid
        assert result.rows == [["Alice", "+919876543210", "Pune"]]

    def test_requires_phone_number_column(self):
        result = CampaignSourceSyncService.validate_source_data(
            ["name", "city"], [["Alice", "Pune"]]
        )

        assert not result.is_valid
        assert "phone_number" in result.error.message

    def test_fails_when_no_valid_phone_numbers_remain(self):
        result = CampaignSourceSyncService.validate_source_data(
            PHONE_HEADERS, [["Alice", "", "Pune"]]
        )

        assert not result.is_valid
        assert "No valid phone numbers" in result.error.message
