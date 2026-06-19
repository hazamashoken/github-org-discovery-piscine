import datetime as dt
import tempfile
import unittest
from pathlib import Path

from intra import (
    apply_intra_create_result,
    build_intra_user_payload,
    format_intra_datetime,
    format_singapore_display,
    load_cursus_options,
    now_singapore,
    pool_month_year,
)


class IntraTest(unittest.TestCase):
    def test_load_cursus_options_reads_expected_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cursus.json"
            path.write_text(
                '[{"cursus_id": 21, "cursus_title": "42cursus"}]',
                encoding="utf-8",
            )

            options = load_cursus_options(path)

        self.assertEqual(options, [{"cursus_id": 21, "cursus_title": "42cursus"}])

    def test_pool_month_year_uses_current_date(self):
        self.assertEqual(
            pool_month_year(dt.date(2026, 6, 19)),
            {"pool_month": "june", "pool_year": "2026"},
        )

    def test_format_intra_datetime_treats_picker_value_as_singapore_time(self):
        self.assertEqual(
            format_intra_datetime(dt.date(2026, 6, 19), dt.time(9, 30)),
            "2026-06-19 01:30:00 UTC",
        )

    def test_now_singapore_uses_asia_singapore_timezone(self):
        self.assertEqual(str(now_singapore().tzinfo), "Asia/Singapore")

    def test_format_singapore_display_shows_local_time_without_timezone_suffix(self):
        self.assertEqual(
            format_singapore_display("2026-06-19 01:30:00 UTC"),
            "2026-06-19 09:30",
        )

    def test_format_singapore_display_handles_blank_value(self):
        self.assertEqual(format_singapore_display(""), "")

    def test_build_intra_user_payload_sets_external_kind_and_cursus(self):
        payload = build_intra_user_payload(
            row={
                "email": "student@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "intra_login": "jdoe",
            },
            campus_id="42",
            cursus={"cursus_id": 21, "cursus_title": "42cursus"},
            begin_at="2026-06-19 09:30:00 UTC",
            end_at="2026-07-19 18:00:00 UTC",
            pool_date=dt.date(2026, 6, 19),
        )

        self.assertEqual(
            payload,
            {
                "user": {
                    "login": "jdoe",
                    "email": "student@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                    "usual_first_name": "John",
                    "campus_id": "42",
                    "pool_month": "june",
                    "pool_year": "2026",
                    "kind": "external",
                    "cursus_users_attributes": [
                        {
                            "cursus_id": 21,
                            "begin_at": "2026-06-19 09:30:00 UTC",
                            "end_at": "2026-07-19 18:00:00 UTC",
                        }
                    ],
                }
            },
        )

    def test_apply_intra_create_result_saves_returned_login_and_repo_name(self):
        row = apply_intra_create_result(
            row={
                "email": "student@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "intra_login": "",
                "repo_name": "",
            },
            result={"login": "jdoe"},
            course_run="discovery-2026",
        )

        self.assertEqual(row["intra_login"], "jdoe")
        self.assertEqual(row["repo_name"], "discovery-2026-jdoe")

    def test_apply_intra_create_result_saves_returned_id(self):
        row = apply_intra_create_result(
            row={
                "email": "student@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "intra_login": "",
                "repo_name": "",
            },
            result={"id": 123, "login": "jdoe"},
            course_run="discovery-2026",
        )

        self.assertEqual(row["intra_user_id"], "123")


if __name__ == "__main__":
    unittest.main()
