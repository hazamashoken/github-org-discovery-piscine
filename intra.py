import datetime as dt
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from provisioning import build_repo_name, clean_text

INTRA_API_BASE = "https://api.intra.42.fr"
CURSUS_OPTIONS_PATH = Path("cursus.json")
SINGAPORE_TZ = ZoneInfo("Asia/Singapore")
UTC_TZ = dt.timezone.utc


def load_cursus_options(path=CURSUS_OPTIONS_PATH):
    path = Path(path)
    if not path.exists():
        return []

    with path.open(encoding="utf-8") as file:
        data = json.load(file)

    options = []
    for item in data:
        cursus_id = item.get("cursus_id")
        cursus_title = clean_text(item.get("cursus_title"))
        if cursus_id is None or not cursus_title:
            continue
        options.append(
            {
                "cursus_id": int(cursus_id),
                "cursus_title": cursus_title,
            }
        )
    return options


def now_singapore():
    return dt.datetime.now(SINGAPORE_TZ)


def pool_month_year(today=None):
    today = today or now_singapore().date()
    return {
        "pool_month": today.strftime("%B").lower(),
        "pool_year": str(today.year),
    }


def format_intra_datetime(date_value, time_value):
    singapore_value = dt.datetime.combine(date_value, time_value, tzinfo=SINGAPORE_TZ)
    utc_value = singapore_value.astimezone(UTC_TZ)
    return utc_value.strftime("%Y-%m-%d %H:%M:%S UTC")


def format_singapore_display(value):
    if not value:
        return ""
    utc_value = dt.datetime.strptime(value, "%Y-%m-%d %H:%M:%S UTC")
    utc_value = utc_value.replace(tzinfo=UTC_TZ)
    singapore_value = utc_value.astimezone(SINGAPORE_TZ)
    return singapore_value.strftime("%Y-%m-%d %H:%M")


def build_intra_user_payload(row, campus_id, cursus, begin_at, end_at, pool_date=None):
    user = {
        "email": clean_text(row.get("email")),
        "first_name": clean_text(row.get("first_name")),
        "last_name": clean_text(row.get("last_name")),
        "usual_first_name": clean_text(row.get("first_name")),
        "campus_id": clean_text(campus_id),
        "kind": "external",
        "cursus_users_attributes": [
            {
                "cursus_id": int(cursus["cursus_id"]),
                "begin_at": begin_at,
                "end_at": end_at,
            }
        ],
    }

    intra_login = clean_text(row.get("intra_login"))
    if intra_login:
        user["login"] = intra_login

    user.update(pool_month_year(pool_date))

    return {"user": user}


def apply_intra_create_result(row, result, course_run):
    intra_login = clean_text(result.get("login")) or clean_text(row.get("intra_login"))
    repo_name = clean_text(row.get("repo_name"))

    if intra_login and not repo_name:
        repo_name = build_repo_name(course_run, intra_login)

    return {
        **row,
        "intra_login": intra_login,
        "intra_user_id": clean_text(result.get("id")) or clean_text(row.get("intra_user_id")),
        "repo_name": repo_name,
    }


def get_intra_access_token(secrets):
    access_token = clean_text(secrets.get("INTRA_ACCESS_TOKEN", ""))
    if access_token:
        return True, access_token

    uid = clean_text(secrets.get("INTRA_UID", ""))
    secret = clean_text(secrets.get("INTRA_SECRET", ""))
    if not uid or not secret:
        return False, "Missing INTRA_ACCESS_TOKEN or INTRA_UID/INTRA_SECRET"

    response = requests.post(
        f"{INTRA_API_BASE}/oauth/token",
        json={
            "grant_type": "client_credentials",
            "client_id": uid,
            "client_secret": secret,
        },
        timeout=30,
    )
    if response.status_code != 200:
        return False, response.text

    return True, response.json()["access_token"]


def create_intra_user(access_token, payload):
    response = requests.post(
        f"{INTRA_API_BASE}/v2/users",
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=30,
    )

    if response.status_code in [200, 201]:
        return True, response.json()

    return False, {
        "status_code": response.status_code,
        "message": response.text,
    }


def simplify_cursus_user(cursus_user):
    user = cursus_user.get("user") or {}
    cursus = cursus_user.get("cursus") or {}
    campus = cursus_user.get("campus") or {}

    return {
        "cursus_user_id": clean_text(cursus_user.get("id")),
        "user_id": clean_text(user.get("id")),
        "login": clean_text(user.get("login")),
        "email": clean_text(user.get("email")),
        "first_name": clean_text(user.get("first_name")),
        "last_name": clean_text(user.get("last_name")),
        "cursus_id": clean_text(cursus.get("id") or cursus_user.get("cursus_id")),
        "cursus_name": clean_text(cursus.get("name")),
        "campus_id": clean_text(campus.get("id") or cursus_user.get("campus_id")),
        "begin_at": clean_text(cursus_user.get("begin_at")),
        "end_at": clean_text(cursus_user.get("end_at")),
        "created_at": clean_text(cursus_user.get("created_at")),
    }


def list_cursus_users(
    access_token,
    cursus_id,
    campus_id="64",
    active_only=True,
    begin_at_range=None,
):
    rows = []
    page = 1

    while True:
        params = {
            "filter[campus_id]": clean_text(campus_id),
            "per_page": 100,
            "page": page,
        }
        if active_only:
            params["filter[end]"] = "false"
        if begin_at_range:
            start_at, end_at = begin_at_range
            params["range[begin_at]"] = f"{clean_text(start_at)},{clean_text(end_at)}"

        response = requests.get(
            f"{INTRA_API_BASE}/v2/cursus/{int(cursus_id)}/cursus_users",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params=params,
            timeout=30,
        )

        if response.status_code != 200:
            return False, {
                "status_code": response.status_code,
                "message": response.text,
            }

        data = response.json()
        if not data:
            return True, rows

        rows.extend(simplify_cursus_user(item) for item in data)
        page += 1


def simplify_project_user(project_user):
    project = project_user.get("project") or {}
    teams = project_user.get("teams") or []
    current_team = next(
        (
            team
            for team in teams
            if clean_text(team.get("id")) == clean_text(project_user.get("current_team_id"))
        ),
        teams[0] if teams else {},
    )

    return {
        "projects_user_id": clean_text(project_user.get("id")),
        "project_id": clean_text(project.get("id") or project_user.get("project_id")),
        "project_name": clean_text(project.get("name")),
        "project_slug": clean_text(project.get("slug")),
        "status": clean_text(project_user.get("status")),
        "final_mark": clean_text(project_user.get("final_mark")),
        "validated": clean_text(project_user.get("validated?")),
        "marked_at": clean_text(project_user.get("marked_at")),
        "updated_at": clean_text(project_user.get("updated_at")),
        "team_id": clean_text(current_team.get("id")),
        "team_name": clean_text(current_team.get("name")),
        "team_status": clean_text(current_team.get("status")),
        "team_final_mark": clean_text(current_team.get("final_mark")),
        "team_validated": clean_text(current_team.get("validated?")),
        "team_closed": clean_text(current_team.get("closed?")),
        "team_closed_at": clean_text(current_team.get("closed_at")),
        "team_repo_url": clean_text(current_team.get("repo_url")),
    }


def list_user_project_users(access_token, user_id, cursus_id="", campus_id=""):
    rows = []
    page = 1

    while True:
        params = {
            "page[size]": 100,
            "page[number]": page,
        }
        if clean_text(cursus_id):
            params["filter[cursus]"] = clean_text(cursus_id)
        if clean_text(campus_id):
            params["filter[campus]"] = clean_text(campus_id)

        response = requests.get(
            f"{INTRA_API_BASE}/v2/users/{clean_text(user_id)}/projects_users",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            params=params,
            timeout=30,
        )

        if response.status_code != 200:
            return False, {
                "status_code": response.status_code,
                "message": response.text,
            }

        data = response.json()
        if not data:
            return True, rows

        rows.extend(simplify_project_user(item) for item in data)
        page += 1
