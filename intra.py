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
