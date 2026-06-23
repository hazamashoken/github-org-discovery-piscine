import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from intra import (
    apply_intra_create_result,
    build_intra_user_payload,
    format_intra_datetime,
    format_singapore_display,
    list_cursus_users,
    list_user_project_users,
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

    def test_list_cursus_users_fetches_active_campus_users_by_cursus(self):
        first_response = Mock()
        first_response.status_code = 200
        first_response.json.return_value = [
            {
                "id": 987,
                "begin_at": "2026-06-19T01:30:00.000Z",
                "end_at": None,
                "user": {
                    "id": 123,
                    "login": "jdoe",
                    "email": "student@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                },
                "cursus": {
                    "id": 80,
                    "name": "Discovery Piscine - Core Python Programming",
                },
                "campus": {"id": 64},
            }
        ]
        last_response = Mock()
        last_response.status_code = 200
        last_response.json.return_value = []

        with patch("intra.requests.get", side_effect=[first_response, last_response]) as get:
            ok, rows = list_cursus_users("token", cursus_id=80, campus_id="64")

        self.assertTrue(ok)
        self.assertEqual(
            rows,
            [
                {
                    "cursus_user_id": "987",
                    "user_id": "123",
                    "login": "jdoe",
                    "email": "student@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                    "cursus_id": "80",
                    "cursus_name": "Discovery Piscine - Core Python Programming",
                    "campus_id": "64",
                    "begin_at": "2026-06-19T01:30:00.000Z",
                    "end_at": "",
                    "created_at": "",
                }
            ],
        )
        self.assertEqual(
            get.call_args_list[0].kwargs["params"],
            {
                "filter[campus_id]": "64",
                "filter[end]": "false",
                "per_page": 100,
                "page": 1,
            },
        )
        self.assertEqual(get.call_args_list[1].kwargs["params"]["page"], 2)

    def test_list_cursus_users_can_fetch_without_active_filter(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = []

        with patch("intra.requests.get", return_value=response) as get:
            ok, rows = list_cursus_users(
                "token",
                cursus_id=80,
                campus_id="64",
                active_only=False,
            )

        self.assertTrue(ok)
        self.assertEqual(rows, [])
        self.assertNotIn("filter[end]", get.call_args.kwargs["params"])

    def test_list_cursus_users_can_filter_by_begin_at_range(self):
        response = Mock()
        response.status_code = 200
        response.json.return_value = []

        with patch("intra.requests.get", return_value=response) as get:
            ok, rows = list_cursus_users(
                "token",
                cursus_id=80,
                campus_id="64",
                begin_at_range=(
                    "2026-06-01 00:00:00 UTC",
                    "2026-06-30 23:59:00 UTC",
                ),
            )

        self.assertTrue(ok)
        self.assertEqual(rows, [])
        self.assertEqual(
            get.call_args.kwargs["params"]["range[begin_at]"],
            "2026-06-01 00:00:00 UTC,2026-06-30 23:59:00 UTC",
        )
        self.assertEqual(get.call_args.kwargs["params"]["filter[end]"], "false")

    def test_list_user_project_users_fetches_project_progress(self):
        first_response = Mock()
        first_response.status_code = 200
        first_response.json.return_value = [
            {
                "id": 456,
                "current_team_id": 789,
                "status": "finished",
                "final_mark": 100,
                "validated?": True,
                "marked_at": "2026-06-20T10:00:00.000Z",
                "updated_at": "2026-06-20T10:00:00.000Z",
                "project": {
                    "id": 80,
                    "name": "Python Basics",
                    "slug": "python-basics",
                },
                "teams": [
                    {
                        "id": 789,
                        "name": "jdoe's group",
                        "status": "finished",
                        "final_mark": 100,
                        "validated?": True,
                        "closed?": True,
                        "closed_at": "2026-06-20T10:00:00.000Z",
                        "repo_url": "https://vogsphere.example/jdoe/python-basics",
                    }
                ],
            }
        ]
        last_response = Mock()
        last_response.status_code = 200
        last_response.json.return_value = []

        with patch("intra.requests.get", side_effect=[first_response, last_response]) as get:
            ok, rows = list_user_project_users(
                "token",
                user_id="jdoe",
                cursus_id=80,
                campus_id=64,
            )

        self.assertTrue(ok)
        self.assertEqual(
            rows,
            [
                {
                    "projects_user_id": "456",
                    "project_id": "80",
                    "project_name": "Python Basics",
                    "project_slug": "python-basics",
                    "status": "finished",
                    "final_mark": "100",
                    "validated": "True",
                    "marked_at": "2026-06-20T10:00:00.000Z",
                    "updated_at": "2026-06-20T10:00:00.000Z",
                    "team_id": "789",
                    "team_name": "jdoe's group",
                    "team_status": "finished",
                    "team_final_mark": "100",
                    "team_validated": "True",
                    "team_closed": "True",
                    "team_closed_at": "2026-06-20T10:00:00.000Z",
                    "team_repo_url": "https://vogsphere.example/jdoe/python-basics",
                }
            ],
        )
        self.assertEqual(
            get.call_args_list[0].args[0],
            "https://api.intra.42.fr/v2/users/jdoe/projects_users",
        )
        self.assertEqual(
            get.call_args_list[0].kwargs["params"],
            {
                "page[size]": 100,
                "page[number]": 1,
                "filter[cursus]": "80",
                "filter[campus]": "64",
            },
        )


if __name__ == "__main__":
    unittest.main()
