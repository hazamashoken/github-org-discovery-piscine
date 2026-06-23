import io
import unittest

from provisioning import (
    apply_permission,
    build_group_project_rows,
    build_manual_row,
    csv_template,
    effective_permission,
    normalize_topic,
    prepare_intra_user_rows,
    prepare_individual_repo_rows,
    read_roster_csv,
    roster_topics,
    select_roster_rows,
    unique_repo_rows,
    validate_roster,
)


class ProvisioningTest(unittest.TestCase):
    def test_build_manual_row_uses_intra_login_for_default_repo_name(self):
        row = build_manual_row(
            email=" student@example.com ",
            first_name=" Jane ",
            last_name=" Smith ",
            intra_login=" JSmith ",
            github_username="",
            course_run="Discovery 2026",
        )

        self.assertEqual(
            row,
            {
                "email": "student@example.com",
                "first_name": "Jane",
                "last_name": "Smith",
                "intra_login": "JSmith",
                "intra_user_id": "",
                "github_username": "",
                "repo_name": "discovery-2026-jsmith",
                "permission": "push",
                "course_run": "Discovery 2026",
                "repo_type": "individual",
            },
        )

    def test_validate_roster_accepts_email_and_intra_login_without_github_username(self):
        records = [
            {
                "email": "student@example.com",
                "first_name": "John",
                "last_name": "Doe",
                "intra_login": "jdoe",
            }
        ]

        roster = validate_roster(records, course_run="Discovery 2026")

        self.assertEqual(roster[0]["first_name"], "John")
        self.assertEqual(roster[0]["last_name"], "Doe")
        self.assertEqual(roster[0]["github_username"], "")
        self.assertEqual(roster[0]["repo_name"], "discovery-2026-jdoe")
        self.assertEqual(roster[0]["permission"], "push")
        self.assertEqual(roster[0]["repo_type"], "individual")

    def test_validate_roster_allows_identity_only_row(self):
        roster = validate_roster(
            [
                {
                    "email": "student@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                }
            ],
            course_run="Discovery 2026",
        )

        self.assertEqual(roster[0]["intra_login"], "")
        self.assertEqual(roster[0]["repo_name"], "")

    def test_validate_roster_allows_multiple_identity_only_rows(self):
        roster = validate_roster(
            [
                {
                    "email": "one@example.com",
                    "first_name": "One",
                    "last_name": "Student",
                },
                {
                    "email": "two@example.com",
                    "first_name": "Two",
                    "last_name": "Student",
                },
            ],
            course_run="Discovery 2026",
        )

        self.assertEqual([row["repo_name"] for row in roster], ["", ""])

    def test_read_roster_csv_handles_cp1252_non_breaking_space(self):
        csv_file = io.BytesIO(
            b"email,first_name,last_name\nstudent@example.com,John,Doe\xa0\n"
        )

        roster = validate_roster(read_roster_csv(csv_file), course_run="Discovery 2026")

        self.assertEqual(roster[0]["last_name"], "Doe")

    def test_prepare_individual_repo_rows_requires_intra_or_repo_name(self):
        with self.assertRaisesRegex(ValueError, "missing repo_name"):
            prepare_individual_repo_rows(
                [
                    {
                        "email": "student@example.com",
                        "first_name": "John",
                        "last_name": "Doe",
                    }
                ],
                course_run="Discovery 2026",
            )

    def test_prepare_individual_repo_rows_derives_repo_name_after_intra_is_filled(self):
        prepared = prepare_individual_repo_rows(
            [
                {
                    "email": "student@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                    "intra_login": "jdoe",
                    "repo_name": "",
                    "permission": "push",
                    "course_run": "Discovery 2026",
                    "repo_type": "individual",
                }
            ],
            course_run="Discovery 2026",
        )

        self.assertEqual(prepared[0]["repo_name"], "discovery-2026-jdoe")

    def test_prepare_intra_user_rows_derives_repo_name_when_intra_is_filled(self):
        prepared = prepare_intra_user_rows(
            [
                {
                    "email": "student@example.com",
                    "first_name": "John",
                    "last_name": "Doe",
                    "intra_login": "jdoe",
                    "github_username": "octocat",
                    "repo_name": "",
                    "permission": "push",
                    "course_run": "Discovery 2026",
                    "repo_type": "individual",
                }
            ],
            course_run="Discovery 2026",
        )

        self.assertEqual(prepared[0]["intra_login"], "jdoe")
        self.assertEqual(prepared[0]["repo_name"], "discovery-2026-jdoe")

    def test_validate_roster_rejects_invalid_permission(self):
        with self.assertRaisesRegex(ValueError, "invalid permission"):
            validate_roster(
                [
                    {
                        "email": "student@example.com",
                        "intra_login": "jdoe",
                        "permission": "owner",
                    }
                ],
                course_run="Discovery 2026",
            )

    def test_validate_roster_rejects_duplicate_individual_repo_name(self):
        with self.assertRaisesRegex(ValueError, "duplicate individual repo_name"):
            validate_roster(
                [
                    {
                        "email": "one@example.com",
                        "intra_login": "one",
                        "repo_name": "shared-repo",
                    },
                    {
                        "email": "two@example.com",
                        "intra_login": "two",
                        "repo_name": "shared-repo",
                    },
                ],
                course_run="Discovery 2026",
            )

    def test_validate_roster_allows_duplicate_group_project_repo_name(self):
        roster = validate_roster(
            [
                {
                    "email": "one@example.com",
                    "intra_login": "one",
                    "repo_name": "shared-repo",
                    "repo_type": "group_project",
                },
                {
                    "email": "two@example.com",
                    "intra_login": "two",
                    "repo_name": "shared-repo",
                    "repo_type": "group_project",
                },
            ],
            course_run="Discovery 2026",
        )

        self.assertEqual([row["repo_type"] for row in roster], ["group_project", "group_project"])

    def test_unique_repo_rows_keeps_one_row_per_repo_name(self):
        rows = [
            {"repo_name": "shared-repo", "intra_login": "one"},
            {"repo_name": "shared-repo", "intra_login": "two"},
            {"repo_name": "solo-repo", "intra_login": "three"},
        ]

        self.assertEqual(
            unique_repo_rows(rows),
            [
                {"repo_name": "shared-repo", "intra_login": "one"},
                {"repo_name": "solo-repo", "intra_login": "three"},
            ],
        )

    def test_build_group_project_rows_uses_selected_roster_as_collaborators(self):
        rows = build_group_project_rows(
            [
                {
                    "email": "one@example.com",
                    "first_name": "One",
                    "last_name": "Student",
                    "intra_login": "one",
                    "intra_user_id": "",
                    "github_username": "one-gh",
                    "permission": "pull",
                    "course_run": "Discovery 2026",
                },
                {
                    "email": "two@example.com",
                    "first_name": "Two",
                    "last_name": "Student",
                    "intra_login": "two",
                    "intra_user_id": "",
                    "github_username": "two-gh",
                    "permission": "pull",
                    "course_run": "Discovery 2026",
                },
            ],
            repo_name="team-01",
            permission="push",
        )

        self.assertEqual(
            rows,
            [
                {
                    "email": "one@example.com",
                    "first_name": "One",
                    "last_name": "Student",
                    "intra_login": "one",
                    "intra_user_id": "",
                    "github_username": "one-gh",
                    "repo_name": "team-01",
                    "permission": "push",
                    "course_run": "Discovery 2026",
                    "repo_type": "group_project",
                },
                {
                    "email": "two@example.com",
                    "first_name": "Two",
                    "last_name": "Student",
                    "intra_login": "two",
                    "intra_user_id": "",
                    "github_username": "two-gh",
                    "repo_name": "team-01",
                    "permission": "push",
                    "course_run": "Discovery 2026",
                    "repo_type": "group_project",
                },
            ],
        )

    def test_csv_template_contains_supported_roster_columns(self):
        template = csv_template()

        self.assertEqual(
            template,
            "email,first_name,last_name\n"
            "student@example.com,John,Doe\n",
        )

    def test_effective_permission_returns_highest_true_permission(self):
        self.assertEqual(
            effective_permission(
                {
                    "pull": True,
                    "triage": True,
                    "push": True,
                    "maintain": False,
                    "admin": False,
                }
            ),
            "push",
        )

    def test_effective_permission_returns_blank_when_no_permission_is_true(self):
        self.assertEqual(effective_permission({}), "")

    def test_normalize_topic_creates_github_topic_safe_slugs(self):
        self.assertEqual(normalize_topic("Discovery 2026 / Team A"), "discovery-2026-team-a")

    def test_roster_topics_group_by_course_run_only(self):
        self.assertEqual(roster_topics("Discovery 2026"), ["discovery-2026", "student-workspace"])

    def test_select_roster_rows_returns_only_checked_rows(self):
        roster = [
            {"email": "a@example.com", "intra_login": "a"},
            {"email": "b@example.com", "intra_login": "b"},
        ]

        selected = select_roster_rows(roster, [False, True])

        self.assertEqual(selected, [{"email": "b@example.com", "intra_login": "b"}])

    def test_apply_permission_updates_selected_rows_without_mutating_original(self):
        roster = [{"email": "a@example.com", "permission": "pull"}]

        updated = apply_permission(roster, "push")

        self.assertEqual(updated, [{"email": "a@example.com", "permission": "push"}])
        self.assertEqual(roster, [{"email": "a@example.com", "permission": "pull"}])

    def test_validate_roster_keeps_nan_github_username_blank(self):
        roster = validate_roster(
            [
                {
                    "email": "student@example.com",
                    "intra_login": "jdoe",
                    "github_username": float("nan"),
                }
            ],
            course_run="Discovery 2026",
        )

        self.assertEqual(roster[0]["github_username"], "")


if __name__ == "__main__":
    unittest.main()
