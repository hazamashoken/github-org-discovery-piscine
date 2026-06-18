import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("repo_controller.sqlite3")


ROSTER_COLUMNS = [
    "id",
    "email",
    "intra_login",
    "github_username",
    "repo_name",
    "permission",
    "course_run",
    "repo_type",
]


def connect(db_path=DEFAULT_DB_PATH):
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    return connection


def init_db(db_path=DEFAULT_DB_PATH):
    connection = connect(db_path)
    try:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS roster_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                intra_login TEXT NOT NULL,
                github_username TEXT NOT NULL DEFAULT '',
                repo_name TEXT NOT NULL,
                permission TEXT NOT NULL DEFAULT 'push',
                course_run TEXT NOT NULL,
                repo_type TEXT NOT NULL DEFAULT 'individual',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(course_run, email, intra_login, repo_name)
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(roster_entries)").fetchall()
        }
        if "repo_type" not in columns:
            connection.execute(
                "ALTER TABLE roster_entries "
                "ADD COLUMN repo_type TEXT NOT NULL DEFAULT 'individual'"
            )
        connection.commit()
    finally:
        connection.close()


def save_roster_rows(db_path, rows):
    if not rows:
        return 0

    connection = connect(db_path)
    try:
        connection.executemany(
            """
            INSERT INTO roster_entries (
                email,
                intra_login,
                github_username,
                repo_name,
                permission,
                course_run,
                repo_type
            )
            VALUES (
                :email,
                :intra_login,
                :github_username,
                :repo_name,
                :permission,
                :course_run,
                :repo_type
            )
            ON CONFLICT(course_run, email, intra_login, repo_name)
            DO UPDATE SET
                github_username = excluded.github_username,
                permission = excluded.permission,
                repo_type = excluded.repo_type,
                updated_at = CURRENT_TIMESTAMP
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()

    return len(rows)


def list_roster_rows(db_path, course_run):
    connection = connect(db_path)
    try:
        rows = connection.execute(
            """
            SELECT id, email, intra_login, github_username, repo_name, permission, course_run, repo_type
            FROM roster_entries
            WHERE course_run = ?
            ORDER BY id
            """,
            (course_run,),
        ).fetchall()
    finally:
        connection.close()

    return [{column: row[column] for column in ROSTER_COLUMNS} for row in rows]


def delete_roster_rows(db_path, row_ids):
    if not row_ids:
        return 0

    placeholders = ", ".join(["?"] * len(row_ids))
    connection = connect(db_path)
    try:
        cursor = connection.execute(
            f"DELETE FROM roster_entries WHERE id IN ({placeholders})",
            row_ids,
        )
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()
