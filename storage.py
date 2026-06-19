import sqlite3
from pathlib import Path


DEFAULT_DB_PATH = Path("repo_controller.sqlite3")


ROSTER_COLUMNS = [
    "id",
    "email",
    "first_name",
    "last_name",
    "intra_login",
    "intra_user_id",
    "github_username",
    "repo_name",
    "permission",
    "course_run",
    "repo_type",
]

COURSE_RUN_COLUMNS = [
    "id",
    "name",
    "slug",
    "description",
    "repo_private",
    "description_prefix",
    "start_at",
    "end_at",
    "archived_at",
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
            CREATE TABLE IF NOT EXISTS course_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                description TEXT NOT NULL DEFAULT '',
                repo_private INTEGER NOT NULL DEFAULT 1,
                description_prefix TEXT NOT NULL DEFAULT 'Student workspace',
                start_at TEXT NOT NULL DEFAULT '',
                end_at TEXT NOT NULL DEFAULT '',
                archived_at TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        course_run_columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(course_runs)").fetchall()
        }
        if "start_at" not in course_run_columns:
            connection.execute(
                "ALTER TABLE course_runs "
                "ADD COLUMN start_at TEXT NOT NULL DEFAULT ''"
            )
        if "end_at" not in course_run_columns:
            connection.execute(
                "ALTER TABLE course_runs "
                "ADD COLUMN end_at TEXT NOT NULL DEFAULT ''"
            )
        if "archived_at" not in course_run_columns:
            connection.execute(
                "ALTER TABLE course_runs "
                "ADD COLUMN archived_at TEXT NOT NULL DEFAULT ''"
            )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS roster_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL,
                first_name TEXT NOT NULL DEFAULT '',
                last_name TEXT NOT NULL DEFAULT '',
                intra_login TEXT NOT NULL DEFAULT '',
                intra_user_id TEXT NOT NULL DEFAULT '',
                github_username TEXT NOT NULL DEFAULT '',
                repo_name TEXT NOT NULL,
                permission TEXT NOT NULL DEFAULT 'push',
                course_run TEXT NOT NULL,
                repo_type TEXT NOT NULL DEFAULT 'individual',
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(course_run, email)
            )
            """
        )
        columns = {
            row["name"]
            for row in connection.execute("PRAGMA table_info(roster_entries)").fetchall()
        }
        table_info = connection.execute("PRAGMA table_info(roster_entries)").fetchall()
        if "repo_type" not in columns:
            connection.execute(
                "ALTER TABLE roster_entries "
                "ADD COLUMN repo_type TEXT NOT NULL DEFAULT 'individual'"
            )
        if "first_name" not in columns:
            connection.execute(
                "ALTER TABLE roster_entries "
                "ADD COLUMN first_name TEXT NOT NULL DEFAULT ''"
            )
        if "last_name" not in columns:
            connection.execute(
                "ALTER TABLE roster_entries "
                "ADD COLUMN last_name TEXT NOT NULL DEFAULT ''"
            )
        if "intra_user_id" not in columns:
            connection.execute(
                "ALTER TABLE roster_entries "
                "ADD COLUMN intra_user_id TEXT NOT NULL DEFAULT ''"
            )
        table_info = connection.execute("PRAGMA table_info(roster_entries)").fetchall()
        intra_login_column = next(row for row in table_info if row["name"] == "intra_login")
        if (
            intra_login_column["dflt_value"] is None
            or not has_course_run_email_unique_index(connection)
        ):
            rebuild_roster_entries_for_optional_intra_login(connection)
        connection.commit()
    finally:
        connection.close()


def has_course_run_email_unique_index(connection):
    indexes = connection.execute("PRAGMA index_list(roster_entries)").fetchall()
    for index in indexes:
        if not index["unique"]:
            continue
        columns = [
            row["name"]
            for row in connection.execute(f"PRAGMA index_info({index['name']})").fetchall()
        ]
        if columns == ["course_run", "email"]:
            return True
    return False


def rebuild_roster_entries_for_optional_intra_login(connection):
    connection.execute("ALTER TABLE roster_entries RENAME TO roster_entries_old")
    connection.execute(
        """
        CREATE TABLE roster_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            first_name TEXT NOT NULL DEFAULT '',
            last_name TEXT NOT NULL DEFAULT '',
            intra_login TEXT NOT NULL DEFAULT '',
            intra_user_id TEXT NOT NULL DEFAULT '',
            github_username TEXT NOT NULL DEFAULT '',
            repo_name TEXT NOT NULL,
            permission TEXT NOT NULL DEFAULT 'push',
            course_run TEXT NOT NULL,
            repo_type TEXT NOT NULL DEFAULT 'individual',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(course_run, email)
        )
        """
    )
    old_columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(roster_entries_old)").fetchall()
    }
    first_name_expr = "first_name" if "first_name" in old_columns else "''"
    last_name_expr = "last_name" if "last_name" in old_columns else "''"
    intra_user_id_expr = "intra_user_id" if "intra_user_id" in old_columns else "''"
    repo_type_expr = "repo_type" if "repo_type" in old_columns else "'individual'"
    connection.execute(
        f"""
        INSERT INTO roster_entries (
            id,
            email,
            first_name,
            last_name,
            intra_login,
            intra_user_id,
            github_username,
            repo_name,
            permission,
            course_run,
            repo_type,
            created_at,
            updated_at
        )
        SELECT
            id,
            email,
            {first_name_expr},
            {last_name_expr},
            COALESCE(intra_login, ''),
            {intra_user_id_expr},
            github_username,
            repo_name,
            permission,
            course_run,
            {repo_type_expr},
            created_at,
            updated_at
        FROM roster_entries_old
        """
    )
    connection.execute("DROP TABLE roster_entries_old")


def row_to_course_run(row):
    return {
        "id": row["id"],
        "name": row["name"],
        "slug": row["slug"],
        "description": row["description"],
        "repo_private": bool(row["repo_private"]),
        "description_prefix": row["description_prefix"],
        "start_at": row["start_at"],
        "end_at": row["end_at"],
        "archived_at": row["archived_at"],
    }


def create_course_run(
    db_path,
    name,
    slug,
    description="",
    repo_private=True,
    description_prefix="Student workspace",
    start_at="",
    end_at="",
):
    connection = connect(db_path)
    try:
        cursor = connection.execute(
            """
            INSERT INTO course_runs (
                name,
                slug,
                description,
                repo_private,
                description_prefix,
                start_at,
                end_at,
                archived_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, '')
            ON CONFLICT(slug)
            DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                repo_private = excluded.repo_private,
                description_prefix = excluded.description_prefix,
                start_at = excluded.start_at,
                end_at = excluded.end_at,
                archived_at = '',
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, name, slug, description, repo_private, description_prefix, start_at, end_at, archived_at
            """,
            (name, slug, description, int(repo_private), description_prefix, start_at, end_at),
        )
        row = cursor.fetchone()
        connection.commit()
        return row_to_course_run(row)
    finally:
        connection.close()


def list_course_runs(db_path, include_archived=False):
    connection = connect(db_path)
    try:
        where_clause = "" if include_archived else "WHERE archived_at = ''"
        rows = connection.execute(
            f"""
            SELECT id, name, slug, description, repo_private, description_prefix, start_at, end_at, archived_at
            FROM course_runs
            {where_clause}
            ORDER BY id
            """
        ).fetchall()
    finally:
        connection.close()

    return [row_to_course_run(row) for row in rows]


def archive_course_run(db_path, slug):
    connection = connect(db_path)
    try:
        cursor = connection.execute(
            """
            UPDATE course_runs
            SET archived_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE slug = ?
            """,
            (slug,),
        )
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


def delete_course_run(db_path, slug):
    connection = connect(db_path)
    try:
        connection.execute("DELETE FROM roster_entries WHERE course_run = ?", (slug,))
        cursor = connection.execute("DELETE FROM course_runs WHERE slug = ?", (slug,))
        connection.commit()
        return cursor.rowcount
    finally:
        connection.close()


def save_roster_rows(db_path, rows):
    if not rows:
        return 0
    rows = [{**row, "intra_user_id": row.get("intra_user_id", "")} for row in rows]

    connection = connect(db_path)
    try:
        connection.executemany(
            """
            INSERT INTO roster_entries (
                email,
                first_name,
                last_name,
                intra_login,
                intra_user_id,
                github_username,
                repo_name,
                permission,
                course_run,
                repo_type
            )
            VALUES (
                :email,
                :first_name,
                :last_name,
                :intra_login,
                :intra_user_id,
                :github_username,
                :repo_name,
                :permission,
                :course_run,
                :repo_type
            )
            ON CONFLICT(course_run, email)
            DO UPDATE SET
                github_username = excluded.github_username,
                first_name = excluded.first_name,
                last_name = excluded.last_name,
                intra_login = excluded.intra_login,
                intra_user_id = excluded.intra_user_id,
                repo_name = excluded.repo_name,
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
            SELECT id, email, first_name, last_name, intra_login, intra_user_id, github_username, repo_name, permission, course_run, repo_type
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


def update_roster_rows(db_path, rows):
    if not rows:
        return 0

    connection = connect(db_path)
    try:
        connection.executemany(
            """
            UPDATE roster_entries
            SET
                email = :email,
                first_name = :first_name,
                last_name = :last_name,
                intra_login = :intra_login,
                intra_user_id = :intra_user_id,
                github_username = :github_username,
                repo_name = :repo_name,
                permission = :permission,
                course_run = :course_run,
                repo_type = :repo_type,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = :id
            """,
            rows,
        )
        connection.commit()
    finally:
        connection.close()

    return len(rows)
