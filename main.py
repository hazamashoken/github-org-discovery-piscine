from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import datetime as dt

import pandas as pd
import requests
import streamlit as st

from intra import (
    apply_intra_create_result,
    build_intra_user_payload,
    create_intra_user,
    format_intra_datetime,
    format_singapore_display,
    get_intra_access_token,
    list_cursus_users,
    list_user_project_users,
    load_cursus_options,
    now_singapore,
)
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
from storage import (
    DEFAULT_DB_PATH,
    archive_course_run,
    create_course_run,
    delete_course_run,
    delete_roster_rows,
    init_db,
    list_course_runs,
    list_roster_rows,
    save_roster_rows,
    update_roster_rows,
)

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GITHUB_ORG = st.secrets["GITHUB_ORG"]

API_BASE = "https://api.github.com"

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

PERMISSIONS = ["push", "pull", "triage", "maintain", "admin"]


def github_request(method, url, **kwargs):
    response = requests.request(method, url, headers=HEADERS, timeout=30, **kwargs)

    if response.status_code in [200, 201, 202, 204]:
        if response.text:
            return True, response.json()
        return True, {}

    return False, {
        "status_code": response.status_code,
        "message": response.text,
    }


def repo_exists(repo_name):
    url = f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}"
    ok, _ = github_request("GET", url)
    return ok


def create_org_repo(repo_name, description="", private=True):
    url = f"{API_BASE}/orgs/{GITHUB_ORG}/repos"

    payload = {
        "name": repo_name,
        "description": description,
        "private": private,
        "auto_init": True,
        "has_issues": True,
        "has_projects": False,
        "has_wiki": False,
    }

    return github_request("POST", url, json=payload)


def add_collaborator(repo_name, username, permission="push"):
    url = f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}/collaborators/{username}"
    return github_request("PUT", url, json={"permission": permission})


def remove_collaborator(repo_name, username):
    url = f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}/collaborators/{username}"
    return github_request("DELETE", url)


def delete_repo(repo_name):
    url = f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}"
    return github_request("DELETE", url)


def set_repo_topics(repo_name, topics):
    url = f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}/topics"
    return github_request("PUT", url, json={"names": topics})


def list_org_repos():
    repos = []
    page = 1

    while True:
        url = f"{API_BASE}/orgs/{GITHUB_ORG}/repos"
        ok, data = github_request(
            "GET",
            url,
            params={"per_page": 100, "page": page, "type": "all"},
        )

        if not ok:
            return ok, data
        if not data:
            return True, repos

        repos.extend(data)
        page += 1


def get_repo_topics(repo_name):
    url = f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}/topics"
    ok, data = github_request("GET", url)
    if not ok:
        return ok, data
    return True, data.get("names", [])


def list_repo_collaborators(repo_name):
    collaborators = []
    page = 1

    while True:
        url = f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}/collaborators"
        ok, data = github_request(
            "GET",
            url,
            params={"per_page": 100, "page": page, "affiliation": "all"},
        )

        if not ok:
            return ok, data
        if not data:
            return True, collaborators

        collaborators.extend(data)
        page += 1


def get_latest_repo_commit(repo_name):
    url = f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}/commits"
    ok, data = github_request("GET", url, params={"per_page": 1})
    if not ok:
        return ok, data
    if not data:
        return True, {}
    return True, data[0]


def github_error_message(error):
    if not error:
        return ""
    if isinstance(error, dict):
        status_code = error.get("status_code")
        message = str(error.get("message", ""))
        if status_code == 403 and "Resource not accessible by personal access token" in message:
            return "GitHub token needs Contents: read permission to read commits for this repo"
        if status_code:
            return f"GitHub API {status_code}: {message}"
        return str(error)
    return str(error)


def get_repo_commit_count(repo_name):
    url = f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}/commits"
    response = requests.get(
        url,
        headers=HEADERS,
        params={"per_page": 1},
        timeout=30,
    )
    if response.status_code not in [200, 201, 202, 204]:
        return False, {
            "status_code": response.status_code,
            "message": response.text,
        }

    data = response.json()
    if not data:
        return True, 0

    link_header = response.headers.get("Link", "")
    if 'rel="last"' not in link_header:
        return True, len(data)

    for part in link_header.split(","):
        if 'rel="last"' not in part:
            continue
        marker = "page="
        if marker not in part:
            continue
        page_text = part.split(marker, 1)[1].split(">", 1)[0].split("&", 1)[0]
        try:
            return True, int(page_text)
        except ValueError:
            break

    return True, len(data)


def get_repo_activity(repo_name):
    repo_name = str(repo_name or "").strip()
    if not repo_name:
        return {
            "github_repo_exists": False,
            "github_error": "Missing repo_name",
        }

    ok, repo_or_error = github_request(
        "GET",
        f"{API_BASE}/repos/{GITHUB_ORG}/{repo_name}",
    )
    if not ok:
        return {
            "github_repo_exists": False,
            "github_error": github_error_message(repo_or_error),
        }

    ok, commit_or_error = get_latest_repo_commit(repo_name)
    latest_commit = commit_or_error if ok else {}
    commit = latest_commit.get("commit") or {}
    author = commit.get("author") or {}
    commit_error = "" if ok else github_error_message(commit_or_error)

    ok, count_or_error = get_repo_commit_count(repo_name)
    commit_count = count_or_error if ok else ""
    if not ok and not commit_error:
        commit_error = github_error_message(count_or_error)

    return {
        "github_repo_exists": True,
        "repo_html_url": repo_or_error.get("html_url", ""),
        "repo_private": repo_or_error.get("private", ""),
        "repo_default_branch": repo_or_error.get("default_branch", ""),
        "repo_pushed_at": repo_or_error.get("pushed_at", ""),
        "repo_updated_at": repo_or_error.get("updated_at", ""),
        "repo_open_issues": repo_or_error.get("open_issues_count", ""),
        "repo_size": repo_or_error.get("size", ""),
        "repo_commit_count": commit_count,
        "latest_commit_sha": latest_commit.get("sha", ""),
        "latest_commit_at": author.get("date", ""),
        "latest_commit_message": commit.get("message", ""),
        "github_error": commit_error,
    }


def list_collaborators_for_repos(repos):
    rows = []

    for repo in repos:
        ok, collaborators_or_error = list_repo_collaborators(repo["repo_name"])
        if not ok:
            return ok, collaborators_or_error

        for collaborator in collaborators_or_error:
            permissions = collaborator.get("permissions") or {}
            rows.append(
                {
                    "repo_name": repo["repo_name"],
                    "github_username": collaborator.get("login", ""),
                    "permission": effective_permission(permissions),
                    "role_name": collaborator.get("role_name", ""),
                    "pull": permissions.get("pull", False),
                    "triage": permissions.get("triage", False),
                    "push": permissions.get("push", False),
                    "maintain": permissions.get("maintain", False),
                    "admin": permissions.get("admin", False),
                    "html_url": collaborator.get("html_url", ""),
                }
            )

    return True, rows


def list_repos_for_course_run(course_run):
    required_topics = set(roster_topics(course_run))
    ok, repos_or_error = list_org_repos()

    if not ok:
        return ok, repos_or_error

    matching = []

    for repo in repos_or_error:
        ok, topics_or_error = get_repo_topics(repo["name"])
        if not ok:
            return ok, topics_or_error

        topics = set(topics_or_error)
        if required_topics.issubset(topics):
            matching.append(
                {
                    "repo_name": repo["name"],
                    "private": repo.get("private", False),
                    "html_url": repo.get("html_url", ""),
                    "topics": ", ".join(sorted(topics)),
                }
            )

    return True, matching


def create_repositories(roster, course_run, description_prefix, repo_private):
    roster = unique_repo_rows(roster)
    results = []
    progress = st.progress(0)
    topics = roster_topics(course_run)

    for index, row in enumerate(roster):
        repo_name = row["repo_name"]
        result = {
            **row,
            "repo_created": False,
            "repo_already_exists": False,
            "topics_added": False,
            "error": "",
        }

        try:
            if repo_exists(repo_name):
                result["repo_already_exists"] = True
            else:
                ok, data = create_org_repo(
                    repo_name=repo_name,
                    description=(
                        f"{description_prefix}: "
                        f"{row['intra_login']} <{row['email']}>"
                    ),
                    private=repo_private,
                )

                if not ok:
                    result["error"] = f"Create repo failed: {data}"
                    results.append(result)
                    continue

                result["repo_created"] = True

            ok, data = set_repo_topics(repo_name, topics)
            if ok:
                result["topics_added"] = True
            else:
                result["error"] = f"Set topics failed: {data}"

        except Exception as exc:
            result["error"] = str(exc)

        results.append(result)
        progress.progress((index + 1) / len(roster))
        time.sleep(0.2)

    return results


def add_collaborators(roster, action_label="collaborator"):
    results = []
    progress = st.progress(0)

    for index, row in enumerate(roster):
        github_username = row["github_username"]
        result = {
            **row,
            f"{action_label}_updated": False,
            "skipped": False,
            "error": "",
        }

        try:
            if not github_username:
                result["skipped"] = True
                result["error"] = "Missing github_username"
                results.append(result)
                continue

            ok, data = add_collaborator(
                repo_name=row["repo_name"],
                username=github_username,
                permission=row["permission"],
            )

            if ok:
                result[f"{action_label}_updated"] = True
            else:
                result["error"] = f"Update collaborator failed: {data}"

        except Exception as exc:
            result["error"] = str(exc)

        results.append(result)
        progress.progress((index + 1) / len(roster))
        time.sleep(0.2)

    return results


def create_intra_users(roster, campus_id, cursus, begin_at, end_at, course_run):
    ok, token_or_error = get_intra_access_token(st.secrets)
    if not ok:
        return [], token_or_error

    results = []
    updated_rows = []
    progress = st.progress(0)

    for index, row in enumerate(roster):
        result = {
            **row,
            "intra_created": False,
            "intra_user_id": "",
            "intra_url": "",
            "error": "",
        }

        try:
            payload = build_intra_user_payload(
                row=row,
                campus_id=campus_id,
                cursus=cursus,
                begin_at=begin_at,
                end_at=end_at,
            )
            ok, data = create_intra_user(token_or_error, payload)
            if ok:
                result["intra_created"] = True
                result["intra_user_id"] = data.get("id", "")
                result["intra_url"] = data.get("url", "")
                updated_row = apply_intra_create_result(
                    row=row,
                    result=data,
                    course_run=course_run,
                )
                updated_rows.append(updated_row)
                result["intra_login"] = updated_row["intra_login"]
                result["repo_name"] = updated_row["repo_name"]
            else:
                result["error"] = f"Create Intra user failed: {data}"
        except Exception as exc:
            result["error"] = str(exc)

        results.append(result)
        progress.progress((index + 1) / len(roster))
        time.sleep(0.2)

    if updated_rows:
        update_roster_rows(DEFAULT_DB_PATH, updated_rows)

    return results, ""


def fetch_cursus_users(cursus_id, campus_id, active_only):
    ok, token_or_error = get_intra_access_token(st.secrets)
    if not ok:
        return ok, token_or_error

    return list_cursus_users(
        access_token=token_or_error,
        cursus_id=cursus_id,
        campus_id=campus_id,
        active_only=active_only,
    )


def fetch_cursus_users_by_begin_at(cursus_id, campus_id, start_at, end_at, active_only):
    ok, token_or_error = get_intra_access_token(st.secrets)
    if not ok:
        return ok, token_or_error

    return list_cursus_users(
        access_token=token_or_error,
        cursus_id=cursus_id,
        campus_id=campus_id,
        active_only=active_only,
        begin_at_range=(start_at, end_at),
    )


def cursus_user_stats(rows):
    return {
        "active_users": len(rows),
        "with_login": sum(1 for row in rows if row.get("login")),
        "with_email": sum(1 for row in rows if row.get("email")),
        "unique_campus_ids": len({row.get("campus_id") for row in rows if row.get("campus_id")}),
    }


def fetch_student_intra_projects(student, cursus_id, campus_id, access_token=None):
    intra_user = student.get("intra_user_id") or student.get("intra_login")
    if not intra_user:
        return True, []

    if access_token is None:
        ok, token_or_error = get_intra_access_token(st.secrets)
        if not ok:
            return ok, token_or_error
        access_token = token_or_error

    return list_user_project_users(
        access_token=access_token,
        user_id=intra_user,
        cursus_id=cursus_id,
        campus_id=campus_id,
    )


def student_display_name(student):
    name = " ".join(
        value
        for value in [student.get("first_name", ""), student.get("last_name", "")]
        if value
    )
    return name or student.get("email", "")


def project_overview_row(student, github_activity, intra_projects):
    project_count = len(intra_projects)
    finished_count = sum(1 for project in intra_projects if project.get("status") == "finished")
    validated_count = sum(1 for project in intra_projects if project.get("validated") == "True")
    in_progress = [
        project["project_name"]
        for project in intra_projects
        if project.get("status") in {"in_progress", "creating_group", "waiting_for_correction"}
    ]

    return {
        "student": student_display_name(student),
        "email": student.get("email", ""),
        "intra_login": student.get("intra_login", ""),
        "github_username": student.get("github_username", ""),
        "repo_name": student.get("repo_name", ""),
        "repo_exists": github_activity.get("github_repo_exists", False),
        "repo_commit_count": github_activity.get("repo_commit_count", ""),
        "repo_pushed_at": github_activity.get("repo_pushed_at", ""),
        "latest_commit_at": github_activity.get("latest_commit_at", ""),
        "latest_commit_sha": github_activity.get("latest_commit_sha", ""),
        "intra_projects": project_count,
        "finished_projects": finished_count,
        "validated_projects": validated_count,
        "current_projects": ", ".join(in_progress),
        "github_error": github_activity.get("github_error", ""),
    }


def fetch_student_project_status(student, cursus_id, campus_id, intra_access_token=None):
    github_activity = get_repo_activity(student.get("repo_name"))
    ok, intra_projects_or_error = fetch_student_intra_projects(
        student=student,
        cursus_id=cursus_id,
        campus_id=campus_id,
        access_token=intra_access_token,
    )
    if not ok:
        intra_projects = []
        intra_error = intra_projects_or_error
    else:
        intra_projects = intra_projects_or_error
        intra_error = ""

    return {
        "overview": project_overview_row(student, github_activity, intra_projects),
        "github": github_activity,
        "intra_projects": intra_projects,
        "intra_error": intra_error,
    }


def fetch_project_statuses_parallel(roster, cursus_id, campus_id, progress):
    ok, token_or_error = get_intra_access_token(st.secrets)
    if not ok:
        return False, token_or_error, {}

    max_workers = min(8, max(1, len(roster)))
    completed = 0
    statuses_by_index = {}
    detail_by_email = {}

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                fetch_student_project_status,
                student,
                cursus_id,
                campus_id,
                token_or_error,
            ): (index, student)
            for index, student in enumerate(roster)
        }

        for future in as_completed(futures):
            index, student = futures[future]
            try:
                status = future.result()
            except Exception as exc:
                github_activity = {
                    "github_repo_exists": False,
                    "github_error": str(exc),
                }
                status = {
                    "overview": project_overview_row(student, github_activity, []),
                    "github": github_activity,
                    "intra_projects": [],
                    "intra_error": str(exc),
                }

            statuses_by_index[index] = status
            detail_by_email[student["email"]] = status
            completed += 1
            progress.progress(completed / len(roster))

    overview_rows = [
        statuses_by_index[index]["overview"]
        for index in sorted(statuses_by_index)
    ]
    return True, overview_rows, detail_by_email


def is_true_value(value):
    return str(value).strip().lower() == "true"


def project_progress_value(project):
    if is_true_value(project.get("validated")):
        return 100
    status = project.get("status", "")
    if status == "finished":
        return 80
    if status in {"waiting_for_correction", "in_progress"}:
        return 60
    if status == "creating_group":
        return 30
    return 10 if status else 0


def project_chart_rows(detail_by_email):
    projects = {}

    for status in detail_by_email.values():
        for project in status.get("intra_projects", []):
            project_name = project.get("project_name") or project.get("project_slug")
            if not project_name:
                continue
            row = projects.setdefault(
                project_name,
                {
                    "project": project_name,
                    "completed": 0,
                    "doing": 0,
                    "attempted": 0,
                },
            )
            row["attempted"] += 1
            if is_true_value(project.get("validated")):
                row["completed"] += 1
            elif project.get("status") in {
                "creating_group",
                "in_progress",
                "waiting_for_correction",
            }:
                row["doing"] += 1

    return sorted(
        projects.values(),
        key=lambda row: (row["completed"], row["doing"], row["attempted"], row["project"]),
        reverse=True,
    )


def student_chart_rows(overview_rows):
    rows = []
    for row in overview_rows:
        doing_count = len(
            [
                project
                for project in row.get("current_projects", "").split(", ")
                if project
            ]
        )
        rows.append(
            {
                "student": row["student"],
                "validated": row["validated_projects"],
                "finished": row["finished_projects"],
                "doing": doing_count,
                "commits": row.get("repo_commit_count") or 0,
            }
        )
    return rows


def update_repo_collaborators(repos, github_username, permission):
    results = []
    progress = st.progress(0)

    for index, repo in enumerate(repos):
        result = {
            "repo_name": repo["repo_name"],
            "github_username": github_username,
            "permission": permission,
            "collaborator_updated": False,
            "error": "",
        }

        try:
            ok, data = add_collaborator(
                repo_name=repo["repo_name"],
                username=github_username,
                permission=permission,
            )
            if ok:
                result["collaborator_updated"] = True
            else:
                result["error"] = f"Update collaborator failed: {data}"
        except Exception as exc:
            result["error"] = str(exc)

        results.append(result)
        progress.progress((index + 1) / len(repos))
        time.sleep(0.2)

    return results


def remove_repo_collaborators(repos, github_username):
    results = []
    progress = st.progress(0)

    for index, repo in enumerate(repos):
        result = {
            "repo_name": repo["repo_name"],
            "github_username": github_username,
            "collaborator_removed": False,
            "error": "",
        }

        try:
            ok, data = remove_collaborator(
                repo_name=repo["repo_name"],
                username=github_username,
            )
            if ok:
                result["collaborator_removed"] = True
            else:
                result["error"] = f"Remove collaborator failed: {data}"
        except Exception as exc:
            result["error"] = str(exc)

        results.append(result)
        progress.progress((index + 1) / len(repos))
        time.sleep(0.2)

    return results


def delete_repositories(repos):
    results = []
    progress = st.progress(0)

    for index, repo in enumerate(repos):
        result = {
            "repo_name": repo["repo_name"],
            "repo_deleted": False,
            "error": "",
        }

        try:
            ok, data = delete_repo(repo["repo_name"])
            if ok:
                result["repo_deleted"] = True
            else:
                result["error"] = f"Delete repo failed: {data}"
        except Exception as exc:
            result["error"] = str(exc)

        results.append(result)
        progress.progress((index + 1) / len(repos))
        time.sleep(0.2)

    return results


def show_result_table(title, results, filename):
    result_df = pd.DataFrame(results)
    st.subheader(title)
    st.dataframe(result_df, width="stretch")
    st.download_button(
        label="Download result CSV",
        data=result_df.to_csv(index=False),
        file_name=filename,
        mime="text/csv",
    )


def selected_roster_from_editor(roster, key):
    editor_df = pd.DataFrame({"selected": [False] * len(roster), **pd.DataFrame(roster).to_dict("list")})
    edited_df = st.data_editor(
        editor_df,
        key=key,
        width="stretch",
        hide_index=True,
        disabled=[column for column in editor_df.columns if column != "selected"],
    )
    return select_roster_rows(roster, edited_df["selected"].tolist())


def editable_identity_roster_from_editor(roster, key):
    editor_df = pd.DataFrame({"selected": [False] * len(roster), **pd.DataFrame(roster).to_dict("list")})
    editable_columns = {"selected", "email", "first_name", "last_name"}
    edited_df = st.data_editor(
        editor_df,
        key=key,
        width="stretch",
        hide_index=True,
        disabled=[column for column in editor_df.columns if column not in editable_columns],
    )
    edited_rows = edited_df.drop(columns=["selected"]).to_dict("records")
    return select_roster_rows(edited_rows, edited_df["selected"].tolist())


def editable_individual_roster_from_editor(roster, key):
    editor_df = pd.DataFrame({"selected": [False] * len(roster), **pd.DataFrame(roster).to_dict("list")})
    editable_columns = {"selected", "intra_login", "repo_name", "github_username", "permission"}
    edited_df = st.data_editor(
        editor_df,
        key=key,
        width="stretch",
        hide_index=True,
        disabled=[column for column in editor_df.columns if column not in editable_columns],
    )
    edited_rows = edited_df.drop(columns=["selected"]).to_dict("records")
    selected_rows = select_roster_rows(edited_rows, edited_df["selected"].tolist())
    return selected_rows


def editable_intra_roster_from_editor(roster, key):
    editor_df = pd.DataFrame({"selected": [False] * len(roster), **pd.DataFrame(roster).to_dict("list")})
    editable_columns = {"selected", "intra_login", "github_username", "permission"}
    edited_df = st.data_editor(
        editor_df,
        key=key,
        width="stretch",
        hide_index=True,
        disabled=[column for column in editor_df.columns if column not in editable_columns],
    )
    edited_rows = edited_df.drop(columns=["selected"]).to_dict("records")
    return select_roster_rows(edited_rows, edited_df["selected"].tolist())


def selected_repos_from_editor(repos, key):
    editor_df = pd.DataFrame({"selected": [False] * len(repos), **pd.DataFrame(repos).to_dict("list")})
    edited_df = st.data_editor(
        editor_df,
        key=key,
        width="stretch",
        hide_index=True,
        disabled=[column for column in editor_df.columns if column != "selected"],
    )
    return select_roster_rows(repos, edited_df["selected"].tolist())


def parse_stored_datetime(value, fallback):
    if not value:
        return fallback
    try:
        utc_value = dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC")
        utc_value = utc_value.replace(tzinfo=dt.timezone.utc)
        return utc_value.astimezone(now_singapore().tzinfo).replace(tzinfo=None)
    except ValueError:
        return fallback


st.set_page_config(page_title="Repo Group Controller", layout="wide")
init_db(DEFAULT_DB_PATH)
st.title("Repo Group Controller")

with st.sidebar:
    st.header("Course run")
    show_archived_course_runs = st.checkbox("Show archived course runs", value=False)
    course_runs = list_course_runs(
        DEFAULT_DB_PATH,
        include_archived=show_archived_course_runs,
    )

    with st.expander("Create course run", expanded=not course_runs):
        with st.form("create_course_run"):
            course_run_name = st.text_input("Name", value="")
            course_run_slug = st.text_input("GitHub topic slug", value="")
            course_run_description = st.text_area("Description", value="")
            default_course_start = now_singapore().replace(second=0, microsecond=0)
            default_course_end = default_course_start + dt.timedelta(days=30)
            course_start_date = st.date_input("Start date (Asia/Singapore)", value=default_course_start.date())
            course_start_time = st.time_input("Start time (Asia/Singapore)", value=default_course_start.time())
            course_end_date = st.date_input("End date (Asia/Singapore)", value=default_course_end.date())
            course_end_time = st.time_input("End time (Asia/Singapore)", value=default_course_end.time())
            new_repo_private = st.checkbox("Default private repositories", value=True)
            new_description_prefix = st.text_input(
                "Repo description prefix",
                value="Student workspace",
            )
            create_submitted = st.form_submit_button("Save course run")

        if create_submitted:
            slug = course_run_slug or normalize_topic(course_run_name)
            if not course_run_name:
                st.error("Course run name is required")
            elif not slug:
                st.error("GitHub topic slug is required")
            else:
                create_course_run(
                    DEFAULT_DB_PATH,
                    name=course_run_name,
                    slug=slug,
                    description=course_run_description,
                    repo_private=new_repo_private,
                    description_prefix=new_description_prefix,
                    start_at=format_intra_datetime(course_start_date, course_start_time),
                    end_at=format_intra_datetime(course_end_date, course_end_time),
                )
                st.success("Course run saved")
                st.rerun()

    course_runs = list_course_runs(
        DEFAULT_DB_PATH,
        include_archived=show_archived_course_runs,
    )

    if not course_runs:
        st.warning("Create a course run before managing rosters or repositories.")
        st.stop()

    selected_course_run = st.selectbox(
        "Select course run",
        course_runs,
        format_func=lambda row: f"{row['name']} ({row['slug']})",
    )
    course_run = selected_course_run["slug"]
    repo_private = selected_course_run["repo_private"]
    description_prefix = selected_course_run["description_prefix"]
    st.caption(selected_course_run["description"] or "No description")
    st.caption(
        f"{format_singapore_display(selected_course_run['start_at']) or 'No start'} -> "
        f"{format_singapore_display(selected_course_run['end_at']) or 'No end'}"
    )
    if selected_course_run["archived_at"]:
        st.warning(f"Archived at {selected_course_run['archived_at']}")

    with st.expander("Update selected course run"):
        with st.form("update_course_run"):
            fallback_start = now_singapore().replace(second=0, microsecond=0)
            fallback_end = fallback_start + dt.timedelta(days=30)
            selected_start = parse_stored_datetime(selected_course_run["start_at"], fallback_start)
            selected_end = parse_stored_datetime(selected_course_run["end_at"], fallback_end)
            updated_name = st.text_input(
                "Name",
                value=selected_course_run["name"],
                key="update_course_run_name",
            )
            updated_description = st.text_area(
                "Description",
                value=selected_course_run["description"],
                key="update_course_run_description",
            )
            updated_start_date = st.date_input(
                "Start date (Asia/Singapore)",
                value=selected_start.date(),
                key="update_course_run_start_date",
            )
            updated_start_time = st.time_input(
                "Start time (Asia/Singapore)",
                value=selected_start.time(),
                key="update_course_run_start_time",
            )
            updated_end_date = st.date_input(
                "End date (Asia/Singapore)",
                value=selected_end.date(),
                key="update_course_run_end_date",
            )
            updated_end_time = st.time_input(
                "End time (Asia/Singapore)",
                value=selected_end.time(),
                key="update_course_run_end_time",
            )
            updated_repo_private = st.checkbox(
                "Default private repositories",
                value=selected_course_run["repo_private"],
                key="update_course_run_repo_private",
            )
            updated_description_prefix = st.text_input(
                "Repo description prefix",
                value=selected_course_run["description_prefix"],
                key="update_course_run_description_prefix",
            )
            update_submitted = st.form_submit_button("Update course run")

        if update_submitted:
            if not updated_name:
                st.error("Course run name is required")
            else:
                create_course_run(
                    DEFAULT_DB_PATH,
                    name=updated_name,
                    slug=selected_course_run["slug"],
                    description=updated_description,
                    repo_private=updated_repo_private,
                    description_prefix=updated_description_prefix,
                    start_at=format_intra_datetime(updated_start_date, updated_start_time),
                    end_at=format_intra_datetime(updated_end_date, updated_end_time),
                )
                st.success("Course run updated")
                st.rerun()

    with st.expander("Archive or delete course run"):
        if selected_course_run["archived_at"]:
            st.info("This course run is already archived.")
        else:
            if st.button("Archive selected course run"):
                archive_course_run(DEFAULT_DB_PATH, selected_course_run["slug"])
                st.success("Course run archived")
                st.rerun()

        st.write("Deleting also removes this course run's local roster rows.")
        delete_phrase = st.text_input(
            "Type DELETE COURSE RUN to confirm",
            key="delete_course_run_phrase",
        )
        if st.button(
            "Delete selected course run",
            disabled=delete_phrase != "DELETE COURSE RUN",
        ):
            delete_course_run(DEFAULT_DB_PATH, selected_course_run["slug"])
            st.success("Course run deleted")
            st.rerun()

st.caption(
    f"Managing course run `{selected_course_run['name']}` "
    f"with topic `{course_run}` in GitHub org `{GITHUB_ORG}`"
)
st.caption(f"Local DB: `{DEFAULT_DB_PATH}`")

(
    tab_roster,
    tab_intra,
    tab_cursus_users,
    tab_statistics,
    tab_project_status,
    tab_individual,
    tab_group,
    tab_collab,
    tab_permission,
    tab_manage,
) = st.tabs(
    [
        "Roster",
        "Intra users",
        "Cursus users",
        "Statistics",
        "Project status",
        "Individual repos",
        "Group project",
        "Add collaborators",
        "Edit permissions",
        "Manage group",
    ]
)

with tab_roster:
    left, right = st.columns([1, 1])

    with left:
        st.subheader("Upload roster CSV")
        st.download_button(
            label="Download CSV template",
            data=csv_template(),
            file_name="roster_template.csv",
            mime="text/csv",
        )
        uploaded_file = st.file_uploader("CSV columns: email, first_name, last_name", type=["csv"])
        uploaded_roster = []
        if uploaded_file:
            try:
                uploaded_df = read_roster_csv(uploaded_file)
                uploaded_roster = validate_roster(uploaded_df, course_run=course_run)
                st.dataframe(pd.DataFrame(uploaded_roster), width="stretch")
                if st.button("Save uploaded roster"):
                    saved_count = save_roster_rows(DEFAULT_DB_PATH, uploaded_roster)
                    st.success(f"Saved {saved_count} roster rows")
                    st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    with right:
        st.subheader("Direct entry")
        with st.form("manual_student"):
            email = st.text_input("Email")
            first_name = st.text_input("First name")
            last_name = st.text_input("Last name")
            submitted = st.form_submit_button("Save to roster")

        if submitted:
            try:
                row = build_manual_row(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    intra_login="",
                    github_username="",
                    repo_name="",
                    permission="push",
                    course_run=course_run,
                    repo_type="individual",
                )
                validate_roster([row], course_run=course_run)
                save_roster_rows(DEFAULT_DB_PATH, [row])
                st.success("Saved row to local roster")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))

    roster = list_roster_rows(DEFAULT_DB_PATH, course_run)
    st.session_state.current_roster = roster

    st.subheader("Saved roster")
    if roster:
        try:
            validate_roster(roster, course_run=course_run)
        except ValueError as exc:
            st.error(f"Saved roster validation error: {exc}")
        selected_roster = editable_identity_roster_from_editor(roster, "saved_roster_selection")
        st.caption(f"{len(roster)} saved rows, {len(selected_roster)} selected")
        if st.button("Save selected identity edits", disabled=not selected_roster):
            try:
                validate_roster(selected_roster, course_run=course_run)
                updated_count = update_roster_rows(DEFAULT_DB_PATH, selected_roster)
                st.success(f"Saved identity edits for {updated_count} rows")
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
        if st.button("Delete selected saved rows", disabled=not selected_roster):
            deleted_count = delete_roster_rows(
                DEFAULT_DB_PATH,
                [row["id"] for row in selected_roster],
            )
            st.success(f"Deleted {deleted_count} roster rows")
            st.rerun()
    else:
        st.info("Upload a CSV or save a direct-entry row.")

with tab_intra:
    roster = st.session_state.get("current_roster", [])
    st.subheader("Create intra users")
    st.write("Select roster rows, choose a cursus and date range, then create external Intra users before repo creation.")

    cursus_options = load_cursus_options()
    campus_id = st.text_input("Campus ID", value=st.secrets.get("INTRA_CAMPUS_ID", ""))

    if cursus_options:
        selected_cursus = st.selectbox(
            "Cursus",
            cursus_options,
            format_func=lambda item: f"{item['cursus_title']} ({item['cursus_id']})",
        )
    else:
        selected_cursus = None
        st.warning("No cursus options found in cursus.json")

    fallback_begin = now_singapore().replace(second=0, microsecond=0)
    fallback_end = fallback_begin + dt.timedelta(days=30)
    course_begin = parse_stored_datetime(selected_course_run["start_at"], fallback_begin)
    course_end = parse_stored_datetime(selected_course_run["end_at"], fallback_end)
    use_course_datetime = st.checkbox("Use course run start/end datetime", value=True)

    if use_course_datetime:
        begin_date = course_begin.date()
        begin_time = course_begin.time()
        end_date = course_end.date()
        end_time = course_end.time()
        st.text_input("Cursus begin_at", value=format_intra_datetime(begin_date, begin_time), disabled=True)
        st.text_input("Cursus end_at", value=format_intra_datetime(end_date, end_time), disabled=True)
    else:
        begin_date = st.date_input("Cursus begin date (Asia/Singapore)", value=course_begin.date())
        begin_time = st.time_input("Cursus begin time (Asia/Singapore)", value=course_begin.time())
        end_date = st.date_input("Cursus end date (Asia/Singapore)", value=course_end.date())
        end_time = st.time_input("Cursus end time (Asia/Singapore)", value=course_end.time())

    if roster:
        selected_roster = editable_intra_roster_from_editor(roster, "intra_user_selection")
        st.caption(f"{len(selected_roster)} selected")
    else:
        selected_roster = []
        st.info("Build a roster first.")

    if st.button("Save selected intra users", disabled=not selected_roster):
        prepared_roster = prepare_intra_user_rows(selected_roster, course_run=course_run)
        updated_count = update_roster_rows(DEFAULT_DB_PATH, prepared_roster)
        st.success(f"Saved intra details for {updated_count} rows")
        st.rerun()

    create_intra_disabled = not selected_roster or not selected_cursus or not campus_id

    if st.button("Create selected Intra users", disabled=create_intra_disabled):
        begin_at = format_intra_datetime(begin_date, begin_time)
        end_at = format_intra_datetime(end_date, end_time)
        results, error = create_intra_users(
            roster=selected_roster,
            campus_id=campus_id,
            cursus=selected_cursus,
            begin_at=begin_at,
            end_at=end_at,
            course_run=course_run,
        )
        if error:
            st.error(error)
        else:
            show_result_table("Intra user creation result", results, "intra_user_creation_result.csv")
            st.session_state.current_roster = list_roster_rows(DEFAULT_DB_PATH, course_run)

with tab_cursus_users:
    st.subheader("Fetch cursus users")
    st.write("Fetch active Intra users for a cursus and campus. Defaults to campus 64 and active cursus users.")

    cursus_options = load_cursus_options()
    if cursus_options:
        selected_fetch_cursus = st.selectbox(
            "Cursus",
            cursus_options,
            format_func=lambda item: f"{item['cursus_title']} ({item['cursus_id']})",
            key="fetch_cursus_users_cursus",
        )
        fetch_cursus_id = selected_fetch_cursus["cursus_id"]
    else:
        selected_fetch_cursus = None
        fetch_cursus_id = st.number_input(
            "Cursus ID",
            min_value=1,
            value=80,
            step=1,
            key="fetch_cursus_users_manual_cursus_id",
        )
        st.warning("No cursus options found in cursus.json")

    fetch_campus_id = st.text_input(
        "Campus ID",
        value=st.secrets.get("INTRA_CAMPUS_ID", "64"),
        key="fetch_cursus_users_campus_id",
    )
    fetch_active_only = st.checkbox(
        "Only users without an end date",
        value=True,
        key="fetch_cursus_users_active_only",
    )

    if st.button("Fetch cursus users", disabled=not fetch_cursus_id or not fetch_campus_id):
        ok, data = fetch_cursus_users(
            cursus_id=fetch_cursus_id,
            campus_id=fetch_campus_id,
            active_only=fetch_active_only,
        )
        if ok:
            st.session_state.cursus_users = data
            st.success(f"Fetched {len(data)} cursus users")
        else:
            st.error(f"Fetch cursus users failed: {data}")

    cursus_users = st.session_state.get("cursus_users", [])
    if cursus_users:
        show_result_table(
            "Cursus users",
            cursus_users,
            f"cursus_{fetch_cursus_id}_campus_{fetch_campus_id}_users.csv",
        )
    else:
        st.info("Fetch cursus users to view them here.")

with tab_statistics:
    st.subheader("Intra user statistics")
    st.write("Fetch active users whose cursus begin_at is within a date range for the selected cursus.")

    cursus_options = load_cursus_options()
    if cursus_options:
        selected_stats_cursus = st.selectbox(
            "Cursus",
            cursus_options,
            format_func=lambda item: f"{item['cursus_title']} ({item['cursus_id']})",
            key="stats_cursus",
        )
        stats_cursus_id = selected_stats_cursus["cursus_id"]
    else:
        stats_cursus_id = st.number_input(
            "Cursus ID",
            min_value=1,
            value=80,
            step=1,
            key="stats_manual_cursus_id",
        )
        st.warning("No cursus options found in cursus.json")

    stats_campus_id = st.text_input(
        "Campus ID",
        value=st.secrets.get("INTRA_CAMPUS_ID", "64"),
        key="stats_campus_id",
    )
    stats_active_only = st.checkbox(
        "Only users without an end date",
        value=True,
        key="stats_active_only",
    )

    fallback_stats_start = now_singapore().replace(second=0, microsecond=0)
    fallback_stats_end = fallback_stats_start + dt.timedelta(days=30)
    course_stats_start = parse_stored_datetime(
        selected_course_run["start_at"],
        fallback_stats_start,
    )
    course_stats_end = parse_stored_datetime(
        selected_course_run["end_at"],
        fallback_stats_end,
    )
    use_course_stats_range = st.checkbox(
        "Use course run start/end datetime",
        value=True,
        key="stats_use_course_datetime",
    )

    if use_course_stats_range:
        stats_start_date = course_stats_start.date()
        stats_start_time = course_stats_start.time()
        stats_end_date = course_stats_end.date()
        stats_end_time = course_stats_end.time()
        st.text_input(
            "Begin at start",
            value=format_intra_datetime(stats_start_date, stats_start_time),
            disabled=True,
            key="stats_begin_start_display",
        )
        st.text_input(
            "Begin at end",
            value=format_intra_datetime(stats_end_date, stats_end_time),
            disabled=True,
            key="stats_begin_end_display",
        )
    else:
        stats_start_date = st.date_input(
            "Begin at start date (Asia/Singapore)",
            value=course_stats_start.date(),
            key="stats_start_date",
        )
        stats_start_time = st.time_input(
            "Begin at start time (Asia/Singapore)",
            value=course_stats_start.time(),
            key="stats_start_time",
        )
        stats_end_date = st.date_input(
            "Begin at end date (Asia/Singapore)",
            value=course_stats_end.date(),
            key="stats_end_date",
        )
        stats_end_time = st.time_input(
            "Begin at end time (Asia/Singapore)",
            value=course_stats_end.time(),
            key="stats_end_time",
        )

    stats_start_at = format_intra_datetime(stats_start_date, stats_start_time)
    stats_end_at = format_intra_datetime(stats_end_date, stats_end_time)
    stats_fetch_label = (
        "Fetch active users for statistics"
        if stats_active_only
        else "Fetch users for statistics"
    )

    if st.button(
        stats_fetch_label,
        disabled=not stats_cursus_id or not stats_campus_id,
    ):
        ok, data = fetch_cursus_users_by_begin_at(
            cursus_id=stats_cursus_id,
            campus_id=stats_campus_id,
            start_at=stats_start_at,
            end_at=stats_end_at,
            active_only=stats_active_only,
        )
        if ok:
            st.session_state.statistics_cursus_users = data
            fetched_label = "active users" if stats_active_only else "users"
            st.success(f"Fetched {len(data)} {fetched_label}")
        else:
            st.error(f"Fetch statistics failed: {data}")

    statistics_rows = st.session_state.get("statistics_cursus_users", [])
    if statistics_rows:
        stats = cursus_user_stats(statistics_rows)
        metric_cols = st.columns(4)
        metric_cols[0].metric("Active users", stats["active_users"])
        metric_cols[1].metric("With login", stats["with_login"])
        metric_cols[2].metric("With email", stats["with_email"])
        metric_cols[3].metric("Campuses", stats["unique_campus_ids"])
        show_result_table(
            "Active users",
            statistics_rows,
            f"active_cursus_{stats_cursus_id}_campus_{stats_campus_id}_users.csv",
        )
    else:
        st.info("Fetch active users to view statistics here.")

with tab_project_status:
    roster = st.session_state.get("current_roster", [])
    st.subheader("Project status")
    st.write("Fetch GitHub repository activity and 42 Intra project progress for students in the selected roster.")

    cursus_options = load_cursus_options()
    if cursus_options:
        selected_project_cursus = st.selectbox(
            "Cursus",
            cursus_options,
            format_func=lambda item: f"{item['cursus_title']} ({item['cursus_id']})",
            key="project_status_cursus",
        )
        project_cursus_id = selected_project_cursus["cursus_id"]
    else:
        project_cursus_id = st.number_input(
            "Cursus ID",
            min_value=1,
            value=80,
            step=1,
            key="project_status_manual_cursus_id",
        )
        st.warning("No cursus options found in cursus.json")

    project_campus_id = st.text_input(
        "Campus ID",
        value=st.secrets.get("INTRA_CAMPUS_ID", "64"),
        key="project_status_campus_id",
    )

    if not roster:
        st.info("Build a roster first.")
    else:
        st.caption(f"{len(roster)} roster students")
        if st.button(
            "Refresh project overview",
            disabled=not project_cursus_id or not project_campus_id,
        ):
            progress = st.progress(0)
            ok, overview_rows_or_error, detail_by_email = fetch_project_statuses_parallel(
                roster=roster,
                cursus_id=project_cursus_id,
                campus_id=project_campus_id,
                progress=progress,
            )
            if ok:
                st.session_state.project_status_overview = overview_rows_or_error
                st.session_state.project_status_detail_by_email = detail_by_email
                st.success(f"Fetched project status for {len(overview_rows_or_error)} students")
            else:
                st.error(overview_rows_or_error)

        overview_rows = st.session_state.get("project_status_overview", [])
        if overview_rows:
            detail_by_email = st.session_state.get("project_status_detail_by_email", {})
            stats_cols = st.columns(4)
            stats_cols[0].metric("Students", len(overview_rows))
            stats_cols[1].metric(
                "Repos found",
                sum(1 for row in overview_rows if row["repo_exists"]),
            )
            stats_cols[2].metric(
                "With Intra projects",
                sum(1 for row in overview_rows if row["intra_projects"]),
            )
            stats_cols[3].metric(
                "Validated projects",
                sum(row["validated_projects"] for row in overview_rows),
            )

            project_rows = project_chart_rows(detail_by_email)
            student_rows = student_chart_rows(overview_rows)

            if project_rows:
                st.subheader("Project completion")
                project_chart_df = pd.DataFrame(project_rows).set_index("project")
                st.bar_chart(
                    project_chart_df[["completed", "doing", "attempted"]],
                    width="stretch",
                )
            else:
                st.info("No Intra project data available for project charts.")

            if student_rows:
                st.subheader("Student progress")
                student_chart_df = pd.DataFrame(student_rows).set_index("student")
                st.bar_chart(
                    student_chart_df[["validated", "finished", "doing"]],
                    width="stretch",
                )

            overview_df = pd.DataFrame(overview_rows)
            st.download_button(
                label="Download project overview CSV",
                data=overview_df.to_csv(index=False),
                file_name=f"{course_run}_project_overview.csv",
                mime="text/csv",
            )

        st.divider()
        st.subheader("Individual student")
        selected_student = st.selectbox(
            "Student",
            roster,
            format_func=lambda row: (
                f"{student_display_name(row)} | "
                f"{row.get('intra_login') or 'no intra'} | "
                f"{row.get('repo_name') or 'no repo'}"
            ),
            key="project_status_student",
        )

        if st.button(
            "Load selected student progress",
            disabled=not project_cursus_id or not project_campus_id,
        ):
            status = fetch_student_project_status(
                student=selected_student,
                cursus_id=project_cursus_id,
                campus_id=project_campus_id,
            )
            st.session_state.selected_project_status = status

        selected_status = st.session_state.get("selected_project_status")
        if selected_status:
            overview = selected_status["overview"]
            github = selected_status["github"]
            student_cols = st.columns(4)
            student_cols[0].metric("Repo", "Found" if overview["repo_exists"] else "Missing")
            student_cols[1].metric("Commits", overview.get("repo_commit_count") or 0)
            student_cols[2].metric("Validated", overview["validated_projects"])
            student_cols[3].metric("Doing", len([p for p in overview["current_projects"].split(", ") if p]))

            repo_url = github.get("repo_html_url")
            if repo_url:
                st.link_button("Open GitHub repo", repo_url)
            if github.get("github_error"):
                st.warning(github["github_error"])

            st.subheader("Project progress")
            if selected_status["intra_error"]:
                st.error(selected_status["intra_error"])
            elif selected_status["intra_projects"]:
                for project in selected_status["intra_projects"]:
                    project_name = project.get("project_name") or project.get("project_slug") or "Unnamed project"
                    status_text = project.get("status") or "unknown"
                    mark_text = project.get("final_mark") or "-"
                    validated_text = "validated" if is_true_value(project.get("validated")) else "not validated"
                    st.progress(
                        project_progress_value(project),
                        text=f"{project_name} | {status_text} | mark {mark_text} | {validated_text}",
                    )
            else:
                st.info("No Intra project rows found for this student.")

with tab_individual:
    roster = st.session_state.get("current_roster", [])
    individual_roster = [row for row in roster if row.get("repo_type") == "individual"]
    st.subheader("Create individual repositories")
    st.write("Select roster rows, fill intra login if missing, then save the repo details or create repositories.")

    if individual_roster:
        selected_roster = editable_individual_roster_from_editor(individual_roster, "individual_repo_selection")
        st.caption(f"{len(selected_roster)} selected")
    else:
        selected_roster = []
        st.info("Build a roster with individual rows first.")

    if st.button("Save selected repo details", disabled=not selected_roster):
        try:
            prepared_roster = prepare_individual_repo_rows(selected_roster, course_run=course_run)
            updated_count = update_roster_rows(DEFAULT_DB_PATH, prepared_roster)
            st.success(f"Saved repo details for {updated_count} rows")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    if st.button("Create selected individual repos", disabled=not selected_roster):
        try:
            prepared_roster = prepare_individual_repo_rows(selected_roster, course_run=course_run)
            update_roster_rows(DEFAULT_DB_PATH, prepared_roster)
            results = create_repositories(
                roster=prepared_roster,
                course_run=course_run,
                description_prefix=description_prefix,
                repo_private=repo_private,
            )
            show_result_table("Individual repo result", results, "individual_repo_creation_result.csv")
        except ValueError as exc:
            st.error(str(exc))

with tab_group:
    roster = st.session_state.get("current_roster", [])
    st.subheader("Create group project repository")
    st.write("Enter one group repo name, select collaborators from the saved roster, create the repo once, then add the selected collaborators.")

    group_repo_name = st.text_input("Group project repo name")
    group_permission = st.selectbox(
        "Collaborator permission",
        PERMISSIONS,
        index=PERMISSIONS.index("push"),
        key="group_project_permission",
    )

    if roster:
        selected_students = selected_roster_from_editor(roster, "group_project_roster_selection")
        group_rows = build_group_project_rows(
            selected_students,
            repo_name=group_repo_name,
            permission=group_permission,
        )
        st.caption(f"{len(selected_students)} collaborators selected")
        if group_rows:
            st.dataframe(pd.DataFrame(group_rows), width="stretch")
    else:
        selected_students = []
        group_rows = []
        st.info("Build a roster first.")

    group_disabled = not group_repo_name or not group_rows

    left_action, right_action = st.columns([1, 1])
    with left_action:
        if st.button("Create group repo", disabled=group_disabled):
            results = create_repositories(
                roster=group_rows,
                course_run=course_run,
                description_prefix=description_prefix,
                repo_private=repo_private,
            )
            show_result_table("Group repo creation result", results, "group_repo_creation_result.csv")

    with right_action:
        if st.button("Add group collaborators", disabled=group_disabled):
            results = add_collaborators(group_rows, action_label="group_collaborator")
            show_result_table("Group collaborator result", results, "group_collaborator_result.csv")

with tab_collab:
    roster = st.session_state.get("current_roster", [])
    st.subheader("Add collaborators only")
    st.write("Select staged roster rows to add as collaborators. This uses `github_username`; rows without a GitHub username are skipped.")

    if roster:
        selected_roster = selected_roster_from_editor(roster, "collaborator_selection")
        st.caption(f"{len(selected_roster)} selected")
    else:
        selected_roster = []
        st.info("Build a roster first.")

    if st.button("Add selected collaborators", disabled=not selected_roster):
        results = add_collaborators(selected_roster, action_label="collaborator")
        show_result_table("Collaborator result", results, "collaborator_result.csv")

with tab_permission:
    roster = st.session_state.get("current_roster", [])
    st.subheader("Edit collaborator permissions")
    st.write("Select staged rows that are already collaborators, choose the target permission, then update GitHub.")
    target_permission = st.selectbox("Target permission", PERMISSIONS, index=PERMISSIONS.index("push"))

    if roster:
        selected_roster = selected_roster_from_editor(roster, "permission_selection")
        selected_roster = apply_permission(selected_roster, target_permission)
        st.caption(f"{len(selected_roster)} selected")
    else:
        selected_roster = []
        st.info("Build a roster first.")

    if st.button("Update selected permissions", disabled=not selected_roster):
        results = add_collaborators(selected_roster, action_label="permission")
        show_result_table("Permission update result", results, "permission_update_result.csv")

with tab_manage:
    st.subheader("Course run repositories")
    st.write("Load repositories tagged with the selected course run, then manage collaborators or delete selected repositories.")

    group_topics = roster_topics(course_run)
    st.text_input("GitHub topics for this course run", value=", ".join(group_topics), disabled=True)

    if st.button("Load course run repos"):
        ok, data = list_repos_for_course_run(course_run)
        if ok:
            st.session_state.manage_repos = data
            if not data:
                st.info("No repositories found for this course run.")
        else:
            st.error(f"Load repos failed: {data}")

    manage_repos = st.session_state.get("manage_repos", [])

    if manage_repos:
        selected_repos = selected_repos_from_editor(manage_repos, "manage_repo_selection")
        st.caption(f"{len(manage_repos)} loaded repos, {len(selected_repos)} selected")
    else:
        selected_repos = []

    if selected_repos:
        st.divider()
        collab_col, delete_col = st.columns([1, 1])

        with collab_col:
            st.subheader("Collaborator controls")
            manage_github_username = st.text_input("GitHub username", key="manage_github_username")
            manage_permission = st.selectbox(
                "Permission",
                PERMISSIONS,
                index=PERMISSIONS.index("push"),
                key="manage_permission",
            )

            update_disabled = not manage_github_username
            if st.button("Add or update collaborator", disabled=update_disabled):
                results = update_repo_collaborators(
                    repos=selected_repos,
                    github_username=manage_github_username,
                    permission=manage_permission,
                )
                show_result_table(
                    "Repo collaborator update result",
                    results,
                    "repo_collaborator_update_result.csv",
                )

            if st.button("Remove collaborator", disabled=update_disabled):
                results = remove_repo_collaborators(
                    repos=selected_repos,
                    github_username=manage_github_username,
                )
                show_result_table(
                    "Repo collaborator removal result",
                    results,
                    "repo_collaborator_removal_result.csv",
                )

            if st.button("Load collaborators for selected repos"):
                ok, data = list_collaborators_for_repos(selected_repos)
                if ok:
                    st.session_state.manage_collaborators = data
                else:
                    st.error(f"Load collaborators failed: {data}")

            manage_collaborators = st.session_state.get("manage_collaborators", [])
            if manage_collaborators:
                st.dataframe(pd.DataFrame(manage_collaborators), width="stretch")

        with delete_col:
            st.subheader("Delete repositories")
            confirm_delete = st.checkbox(
                "I understand this permanently deletes the selected repositories",
                key="confirm_repo_delete",
            )
            delete_phrase = st.text_input("Type DELETE to confirm", key="repo_delete_phrase")
            delete_disabled = not confirm_delete or delete_phrase != "DELETE"

            if st.button("Delete selected repositories", disabled=delete_disabled):
                results = delete_repositories(selected_repos)
                show_result_table("Repo delete result", results, "repo_delete_result.csv")
                st.session_state.manage_repos = [
                    repo
                    for repo in manage_repos
                    if repo["repo_name"] not in {selected["repo_name"] for selected in selected_repos}
                ]
