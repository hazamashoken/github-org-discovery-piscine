import csv
import io
import re


CSV_TEMPLATE_COLUMNS = [
    "email",
    "first_name",
    "last_name",
]

PERMISSION_PRIORITY = ["admin", "maintain", "push", "triage", "pull"]
ALLOWED_PERMISSIONS = {"pull", "triage", "push", "maintain", "admin"}
ALLOWED_REPO_TYPES = {"individual", "group_project"}


def clean_text(value):
    if value is None:
        return ""
    if value != value:
        return ""
    return str(value).strip()


def normalize_topic(value):
    topic = clean_text(value).lower()
    topic = re.sub(r"[^a-z0-9-]+", "-", topic)
    topic = re.sub(r"-+", "-", topic).strip("-")
    return topic[:50]


def build_repo_name(course_run, intra_login):
    course_slug = normalize_topic(course_run)
    login_slug = normalize_topic(intra_login)
    if course_slug and login_slug:
        return f"{course_slug}-{login_slug}"
    return login_slug or course_slug


def build_manual_row(
    email,
    intra_login,
    github_username="",
    intra_user_id="",
    first_name="",
    last_name="",
    repo_name="",
    permission="push",
    course_run="",
    repo_type="individual",
):
    email = clean_text(email)
    intra_login = clean_text(intra_login)
    repo_name = clean_text(repo_name)
    if not repo_name and intra_login:
        repo_name = build_repo_name(course_run, intra_login)
    permission = clean_text(permission) or "push"
    repo_type = clean_text(repo_type) or "individual"

    return {
        "email": email,
        "first_name": clean_text(first_name),
        "last_name": clean_text(last_name),
        "intra_login": intra_login,
        "intra_user_id": clean_text(intra_user_id),
        "github_username": clean_text(github_username),
        "repo_name": repo_name,
        "permission": permission,
        "course_run": clean_text(course_run),
        "repo_type": repo_type,
    }


def validate_roster(roster, course_run=""):
    records = roster.to_dict("records") if hasattr(roster, "to_dict") else roster
    normalized = []

    for index, row in enumerate(records, start=1):
        email = clean_text(row.get("email"))
        intra_login = clean_text(row.get("intra_login") or row.get("login"))
        permission = clean_text(row.get("permission", "push")) or "push"
        repo_type = clean_text(row.get("repo_type", "individual")) or "individual"

        if not email:
            raise ValueError(f"Row {index}: missing email")
        if permission not in ALLOWED_PERMISSIONS:
            raise ValueError(f"Row {index}: invalid permission '{permission}'")
        if repo_type not in ALLOWED_REPO_TYPES:
            raise ValueError(f"Row {index}: invalid repo_type '{repo_type}'")

        normalized.append(
            build_manual_row(
                email=email,
                first_name=row.get("first_name", ""),
                last_name=row.get("last_name", ""),
                intra_login=intra_login,
                intra_user_id=row.get("intra_user_id", ""),
                github_username=row.get("github_username", ""),
                repo_name=row.get("repo_name", ""),
                permission=permission,
                course_run=row.get("course_run", course_run),
                repo_type=repo_type,
            )
        )

    individual_repo_names = {}
    for index, row in enumerate(normalized, start=1):
        if row["repo_type"] != "individual":
            continue
        repo_name = row["repo_name"]
        if not repo_name:
            continue
        if repo_name in individual_repo_names:
            first_index = individual_repo_names[repo_name]
            raise ValueError(
                f"Row {index}: duplicate individual repo_name '{repo_name}' "
                f"also used on row {first_index}"
            )
        individual_repo_names[repo_name] = index

    return normalized


def prepare_individual_repo_rows(roster, course_run=""):
    prepared = []

    for index, row in enumerate(roster, start=1):
        repo_name = clean_text(row.get("repo_name"))
        intra_login = clean_text(row.get("intra_login"))

        if not repo_name and intra_login:
            repo_name = build_repo_name(course_run, intra_login)
        if not repo_name:
            raise ValueError(f"Row {index}: missing repo_name when intra_login is blank")

        prepared.append({**row, "repo_name": repo_name, "intra_login": intra_login})

    return prepared


def prepare_intra_user_rows(roster, course_run=""):
    prepared = []

    for row in roster:
        intra_login = clean_text(row.get("intra_login"))
        repo_name = clean_text(row.get("repo_name"))

        if not repo_name and intra_login:
            repo_name = build_repo_name(course_run, intra_login)

        prepared.append(
            {
                **row,
                "intra_login": intra_login,
                "intra_user_id": clean_text(row.get("intra_user_id")),
                "github_username": clean_text(row.get("github_username")),
                "repo_name": repo_name,
                "permission": clean_text(row.get("permission")) or "push",
                "repo_type": clean_text(row.get("repo_type")) or "individual",
            }
        )

    return prepared


def roster_topics(course_run):
    topics = [
        normalize_topic(course_run),
        "student-workspace",
    ]
    return [topic for topic in topics if topic]


def select_roster_rows(roster, selected_flags):
    return [row for row, selected in zip(roster, selected_flags) if selected]


def unique_repo_rows(rows):
    unique_rows = []
    seen_repo_names = set()

    for row in rows:
        repo_name = row["repo_name"]
        if repo_name in seen_repo_names:
            continue
        unique_rows.append(row)
        seen_repo_names.add(repo_name)

    return unique_rows


def build_group_project_rows(roster_rows, repo_name, permission="push"):
    repo_name = clean_text(repo_name)
    permission = clean_text(permission) or "push"

    return [
        build_manual_row(
            email=row.get("email", ""),
            first_name=row.get("first_name", ""),
            last_name=row.get("last_name", ""),
            intra_login=row.get("intra_login", ""),
            intra_user_id=row.get("intra_user_id", ""),
            github_username=row.get("github_username", ""),
            repo_name=repo_name,
            permission=permission,
            course_run=row.get("course_run", ""),
            repo_type="group_project",
        )
        for row in roster_rows
    ]


def apply_permission(roster, permission):
    selected_permission = clean_text(permission) or "push"
    return [{**row, "permission": selected_permission} for row in roster]


def csv_template():
    return (
        ",".join(CSV_TEMPLATE_COLUMNS)
        + "\n"
        + "student@example.com,John,Doe\n"
    )


def read_roster_csv(file_like):
    if hasattr(file_like, "getvalue"):
        raw_data = file_like.getvalue()
    else:
        raw_data = file_like.read()

    if isinstance(raw_data, str):
        raw_data = raw_data.encode("utf-8")

    last_error = None
    for encoding in ["utf-8-sig", "utf-8", "cp1252", "latin1"]:
        try:
            decoded = raw_data.decode(encoding)
            return list(csv.DictReader(io.StringIO(decoded)))
        except UnicodeDecodeError as exc:
            last_error = exc

    raise ValueError(f"Could not decode roster CSV: {last_error}")


def effective_permission(permissions):
    for permission in PERMISSION_PRIORITY:
        if permissions.get(permission):
            return permission
    return ""


def is_true_value(value):
    return str(value).strip().lower() == "true"


def project_status_bucket(project):
    if is_true_value(project.get("validated")):
        return "completed"
    if project.get("status") == "finished" or clean_text(project.get("final_mark")):
        return "attempted"
    if project.get("status") in {
        "creating_group",
        "in_progress",
        "waiting_for_correction",
    }:
        return "doing"
    return ""


def project_chart_rows(detail_by_email):
    project_user_buckets = {}
    bucket_priority = {
        "doing": 1,
        "attempted": 2,
        "completed": 3,
    }

    for user_key, status in detail_by_email.items():
        for project in status.get("intra_projects", []):
            project_name = project.get("project_name") or project.get("project_slug")
            if not project_name:
                continue
            bucket = project_status_bucket(project)
            if not bucket:
                continue

            project_buckets = project_user_buckets.setdefault(project_name, {})
            current_bucket = project_buckets.get(user_key, "")
            if bucket_priority[bucket] > bucket_priority.get(current_bucket, 0):
                project_buckets[user_key] = bucket

    projects = []
    for project_name, user_buckets in project_user_buckets.items():
        projects.append(
            {
                "project": project_name,
                "completed": sum(1 for bucket in user_buckets.values() if bucket == "completed"),
                "attempted": sum(1 for bucket in user_buckets.values() if bucket == "attempted"),
                "doing": sum(1 for bucket in user_buckets.values() if bucket == "doing"),
            }
        )

    return sorted(
        projects,
        key=lambda row: (row["completed"], row["attempted"], row["doing"], row["project"]),
        reverse=True,
    )


def python_module_number(project):
    project_name = clean_text(project.get("project_name") or project.get("project_slug"))
    match = re.search(r"\bmodule[\s_-]*(\d+)\b", project_name, flags=re.IGNORECASE)
    if not match:
        return None

    module_number = int(match.group(1))
    if 0 <= module_number <= 9:
        return module_number
    return None


def student_progress_rows(detail_by_email):
    rows = []
    bucket_priority = {
        "in_progress": 1,
        "waiting_for_correction": 2,
        "finished": 3,
    }

    for status in detail_by_email.values():
        overview = status.get("overview", {})
        module_buckets = {}

        for project in status.get("intra_projects", []):
            module_number = python_module_number(project)
            if module_number is None:
                continue

            if is_true_value(project.get("validated")):
                bucket = "finished"
            else:
                bucket = project.get("status")
            if bucket not in bucket_priority:
                continue

            current_bucket = module_buckets.get(module_number, "")
            if bucket_priority[bucket] > bucket_priority.get(current_bucket, 0):
                module_buckets[module_number] = bucket

        rows.append(
            {
                "student": overview.get("student") or overview.get("email", ""),
                "finished": sum(1 for bucket in module_buckets.values() if bucket == "finished"),
                "waiting_for_correction": sum(
                    1
                    for bucket in module_buckets.values()
                    if bucket == "waiting_for_correction"
                ),
                "in_progress": sum(1 for bucket in module_buckets.values() if bucket == "in_progress"),
            }
        )

    return sorted(rows, key=lambda row: row["student"])
