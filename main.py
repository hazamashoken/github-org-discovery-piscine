import time

import pandas as pd
import requests
import streamlit as st

from provisioning import (
    apply_permission,
    build_group_project_rows,
    build_manual_row,
    csv_template,
    effective_permission,
    roster_topics,
    select_roster_rows,
    unique_repo_rows,
    validate_roster,
)
from storage import DEFAULT_DB_PATH, delete_roster_rows, init_db, list_roster_rows, save_roster_rows

GITHUB_TOKEN = st.secrets["GITHUB_TOKEN"]
GITHUB_ORG = st.secrets["GITHUB_ORG"]

API_BASE = "https://api.github.com"

HEADERS = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}

PERMISSIONS = ["push", "pull", "triage", "maintain", "admin"]
REPO_TYPES = ["individual", "group_project"]


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


st.set_page_config(page_title="Repo Group Controller", layout="wide")
init_db(DEFAULT_DB_PATH)
st.title("Repo Group Controller")

with st.sidebar:
    st.header("Course run")
    course_run = st.text_input("Course run", value="discovery-2026")
    repo_private = st.checkbox("Create private repositories", value=True)
    description_prefix = st.text_input("Repo description prefix", value="Student workspace")

st.caption(f"Managing course run `{course_run}` in GitHub org `{GITHUB_ORG}`")
st.caption(f"Local DB: `{DEFAULT_DB_PATH}`")

tab_roster, tab_individual, tab_group, tab_collab, tab_permission, tab_manage = st.tabs(
    [
        "Roster",
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
        uploaded_file = st.file_uploader("CSV columns: email, intra_login, optional github_username, repo_name, permission", type=["csv"])
        uploaded_roster = []
        if uploaded_file:
            try:
                uploaded_df = pd.read_csv(uploaded_file)
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
            intra_login = st.text_input("Intra login")
            github_username = st.text_input("GitHub username, optional")
            repo_name = st.text_input("Repo name, optional")
            permission = st.selectbox("Permission", PERMISSIONS, index=0)
            repo_type = st.selectbox("Repo type", REPO_TYPES, index=0)
            submitted = st.form_submit_button("Save to roster")

        if submitted:
            try:
                row = build_manual_row(
                    email=email,
                    intra_login=intra_login,
                    github_username=github_username,
                    repo_name=repo_name,
                    permission=permission,
                    course_run=course_run,
                    repo_type=repo_type,
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
        selected_roster = selected_roster_from_editor(roster, "saved_roster_selection")
        st.caption(f"{len(roster)} saved rows, {len(selected_roster)} selected")
        if st.button("Delete selected saved rows", disabled=not selected_roster):
            deleted_count = delete_roster_rows(
                DEFAULT_DB_PATH,
                [row["id"] for row in selected_roster],
            )
            st.success(f"Deleted {deleted_count} roster rows")
            st.rerun()
    else:
        st.info("Upload a CSV or save a direct-entry row.")

with tab_individual:
    roster = st.session_state.get("current_roster", [])
    individual_roster = [row for row in roster if row.get("repo_type") == "individual"]
    st.subheader("Create individual repositories")
    st.write("Each selected roster row creates one individual student repository. Roster upload and direct entry only stage data; they do not create repositories.")

    if individual_roster:
        selected_roster = selected_roster_from_editor(individual_roster, "individual_repo_selection")
        st.caption(f"{len(selected_roster)} selected")
    else:
        selected_roster = []
        st.info("Build a roster with individual rows first.")

    if st.button("Create selected individual repos", disabled=not selected_roster):
        results = create_repositories(
            roster=selected_roster,
            course_run=course_run,
            description_prefix=description_prefix,
            repo_private=repo_private,
        )
        show_result_table("Individual repo result", results, "individual_repo_creation_result.csv")

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
