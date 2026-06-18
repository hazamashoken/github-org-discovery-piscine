import tempfile
import unittest
from pathlib import Path

from storage import init_db, list_roster_rows, save_roster_rows


class StorageTest(unittest.TestCase):
    def test_save_and_list_roster_rows_by_course_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            init_db(db_path)

            save_roster_rows(
                db_path,
                [
                    {
                        "email": "student@example.com",
                        "intra_login": "jdoe",
                        "github_username": "octocat",
                        "repo_name": "discovery-2026-jdoe",
                        "permission": "push",
                        "course_run": "Discovery 2026",
                        "repo_type": "individual",
                    },
                    {
                        "email": "other@example.com",
                        "intra_login": "other",
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
                    "intra_login": "jdoe",
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
                "intra_login": "jdoe",
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


if __name__ == "__main__":
    unittest.main()
