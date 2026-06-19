import tempfile
import unittest
from pathlib import Path

from storage import (
    archive_course_run,
    create_course_run,
    delete_course_run,
    init_db,
    list_course_runs,
    list_roster_rows,
    save_roster_rows,
    update_roster_rows,
)


class StorageTest(unittest.TestCase):
    def test_create_and_list_course_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)

            created = create_course_run(
                db_path,
                name="Discovery Piscine 2026",
                slug="discovery-2026",
                description="June intake",
                repo_private=True,
                description_prefix="Student workspace",
                start_at="2026-06-19 09:00:00 UTC",
                end_at="2026-07-19 18:00:00 UTC",
            )
            rows = list_course_runs(db_path)

        self.assertEqual(created["slug"], "discovery-2026")
        self.assertEqual(
            rows,
            [
                {
                    "id": 1,
                    "name": "Discovery Piscine 2026",
                    "slug": "discovery-2026",
                    "description": "June intake",
                    "repo_private": True,
                    "description_prefix": "Student workspace",
                    "start_at": "2026-06-19 09:00:00 UTC",
                    "end_at": "2026-07-19 18:00:00 UTC",
                    "archived_at": "",
                }
            ],
        )

    def test_create_course_run_reuses_existing_slug(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)

            first = create_course_run(db_path, name="Discovery", slug="discovery")
            second = create_course_run(db_path, name="Discovery Updated", slug="discovery")
            rows = list_course_runs(db_path)

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Discovery Updated")
        self.assertEqual(rows[0]["start_at"], "")
        self.assertEqual(rows[0]["end_at"], "")
        self.assertEqual(rows[0]["archived_at"], "")

    def test_archive_course_run_hides_it_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)
            create_course_run(db_path, name="Discovery", slug="discovery")

            archived_count = archive_course_run(db_path, "discovery")

            self.assertEqual(archived_count, 1)
            self.assertEqual(list_course_runs(db_path), [])
            self.assertEqual(len(list_course_runs(db_path, include_archived=True)), 1)

    def test_delete_course_run_removes_course_and_roster_rows(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)
            create_course_run(db_path, name="Discovery", slug="discovery")
            save_roster_rows(
                db_path,
                [
                    {
                        "email": "student@example.com",
                        "first_name": "John",
                        "last_name": "Doe",
                        "intra_login": "",
                        "github_username": "",
                        "repo_name": "",
                        "permission": "push",
                        "course_run": "discovery",
                        "repo_type": "individual",
                    }
                ],
            )

            deleted_count = delete_course_run(db_path, "discovery")

            self.assertEqual(deleted_count, 1)
            self.assertEqual(list_course_runs(db_path, include_archived=True), [])
            self.assertEqual(list_roster_rows(db_path, "discovery"), [])

    def test_save_and_list_roster_rows_by_course_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)

            save_roster_rows(
                db_path,
                [
                    {
                        "email": "student@example.com",
                        "first_name": "John",
                        "last_name": "Doe",
                        "intra_login": "jdoe",
                        "intra_user_id": "123",
                        "github_username": "octocat",
                        "repo_name": "discovery-2026-jdoe",
                        "permission": "push",
                        "course_run": "Discovery 2026",
                        "repo_type": "individual",
                    },
                    {
                        "email": "other@example.com",
                        "first_name": "Other",
                        "last_name": "Student",
                        "intra_login": "other",
                        "intra_user_id": "",
                        "github_username": "",
                        "repo_name": "other-2026-other",
                        "permission": "pull",
                        "course_run": "Other 2026",
                        "repo_type": "group_project",
                    },
                ],
            )

            rows = list_roster_rows(db_path, "Discovery 2026")

        self.assertEqual(
            rows,
            [
                {
                    "id": 1,
                    "email": "student@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                    "intra_login": "jdoe",
                    "intra_user_id": "123",
                    "github_username": "octocat",
                    "repo_name": "discovery-2026-jdoe",
                    "permission": "push",
                    "course_run": "Discovery 2026",
                    "repo_type": "individual",
                }
            ],
        )

    def test_save_roster_rows_updates_existing_identity(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)
            row = {
                "email": "student@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "intra_login": "jdoe",
                "intra_user_id": "",
                "github_username": "",
                "repo_name": "discovery-2026-jdoe",
                "permission": "pull",
                "course_run": "Discovery 2026",
                "repo_type": "individual",
            }

            save_roster_rows(db_path, [row])
            save_roster_rows(db_path, [{**row, "github_username": "octocat", "permission": "push"}])
            rows = list_roster_rows(db_path, "Discovery 2026")

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["github_username"], "octocat")
        self.assertEqual(rows[0]["permission"], "push")

    def test_save_roster_rows_allows_identity_only_roster_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)

            save_roster_rows(
                db_path,
                [
                    {
                        "email": "student@example.com",
                        "first_name": "John",
                        "last_name": "Doe",
                        "intra_login": "",
                        "intra_user_id": "",
                        "github_username": "",
                        "repo_name": "",
                        "permission": "push",
                        "course_run": "Discovery 2026",
                        "repo_type": "individual",
                    }
                ],
            )
            rows = list_roster_rows(db_path, "Discovery 2026")

        self.assertEqual(rows[0]["intra_login"], "")
        self.assertEqual(rows[0]["repo_name"], "")

    def test_update_roster_rows_updates_intra_login_by_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)
            save_roster_rows(
                db_path,
                [
                    {
                        "email": "student@example.com",
                        "first_name": "John",
                        "last_name": "Doe",
                        "intra_login": "",
                        "intra_user_id": "",
                        "github_username": "",
                        "repo_name": "",
                        "permission": "push",
                        "course_run": "Discovery 2026",
                        "repo_type": "individual",
                    }
                ],
            )
            row = list_roster_rows(db_path, "Discovery 2026")[0]

            update_roster_rows(
                db_path,
                [
                    {
                        **row,
                        "intra_login": "jdoe",
                        "repo_name": "discovery-2026-jdoe",
                        "intra_user_id": "123",
                    }
                ],
            )
            rows = list_roster_rows(db_path, "Discovery 2026")

        self.assertEqual(rows[0]["intra_login"], "jdoe")
        self.assertEqual(rows[0]["intra_user_id"], "123")
        self.assertEqual(rows[0]["repo_name"], "discovery-2026-jdoe")

    def test_update_roster_rows_updates_identity_fields_by_id(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)
            save_roster_rows(
                db_path,
                [
                    {
                        "email": "old@example.com",
                        "first_name": "Old",
                        "last_name": "Name",
                        "intra_login": "",
                        "intra_user_id": "",
                        "github_username": "",
                        "repo_name": "",
                        "permission": "push",
                        "course_run": "Discovery 2026",
                        "repo_type": "individual",
                    }
                ],
            )
            row = list_roster_rows(db_path, "Discovery 2026")[0]

            update_roster_rows(
                db_path,
                [
                    {
                        **row,
                        "email": "new@example.com",
                        "first_name": "New",
                        "last_name": "Person",
                    }
                ],
            )
            rows = list_roster_rows(db_path, "Discovery 2026")

        self.assertEqual(rows[0]["email"], "new@example.com")
        self.assertEqual(rows[0]["first_name"], "New")
        self.assertEqual(rows[0]["last_name"], "Person")


if __name__ == "__main__":
    unittest.main()
