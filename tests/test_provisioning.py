import unittest

from provisioning import (
    apply_permission,
    build_group_project_rows,
    build_manual_row,
    csv_template,
    effective_permission,
    normalize_topic,
    roster_topics,
    select_roster_rows,
    unique_repo_rows,
    validate_roster,
)


class ProvisioningTest(unittest.TestCase):
    def test_build_manual_row_uses_intra_login_for_default_repo_name(self):
        row = build_manual_row(
            email=" student@example.com ",
            intra_login=" JSmith ",
            github_username="",
            course_run="Discovery 2026",
        )

        self.assertEqual(
            row,
            {
                "email": "student@example.com",
                "intra_login": "JSmith",
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
                "intra_login": "jdoe",
            }
        ]

        roster = validate_roster(records, course_run="Discovery 2026")

        self.assertEqual(roster[0]["github_username"], "")
        self.assertEqual(roster[0]["repo_name"], "discovery-2026-jdoe")
        self.assertEqual(roster[0]["permission"], "push")
        self.assertEqual(roster[0]["repo_type"], "individual")

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
                    "intra_login": "one",
                    "github_username": "one-gh",
                    "permission": "pull",
                    "course_run": "Discovery 2026",
                },
                {
                    "email": "two@example.com",
                    "intra_login": "two",
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
                    "intra_login": "one",
                    "github_username": "one-gh",
                    "repo_name": "team-01",
                    "permission": "push",
                    "course_run": "Discovery 2026",
                    "repo_type": "group_project",
                },
                {
                    "email": "two@example.com",
                    "intra_login": "two",
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
            "email,intra_login,github_username,repo_name,permission,repo_type\n"
            "student@example.com,jdoe,github-user,,push,individual\n",
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
