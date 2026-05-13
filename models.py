import sqlite3
import os
from paths import DATABASE


def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spreadsheet_url TEXT NOT NULL,
                spreadsheet_title TEXT DEFAULT '',
                fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                label TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS snapshot_details (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
                sheet_title TEXT NOT NULL,
                worker_name TEXT NOT NULL,
                round TEXT NOT NULL,
                completed_count INTEGER DEFAULT 0,
                total_count INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS efficiency_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_from_id INTEGER REFERENCES snapshots(id),
                snapshot_to_id INTEGER REFERENCES snapshots(id),
                worker_name TEXT NOT NULL,
                round TEXT NOT NULL,
                work_done INTEGER NOT NULL,
                work_hours REAL NOT NULL,
                sheet_title TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS worker_list (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                worker_name TEXT NOT NULL UNIQUE,
                default_hours REAL DEFAULT 8.0,
                company TEXT DEFAULT ''
            );
        """)

    # Run migrations
    current = _schema_version()
    _run_migrations(current)


def _schema_version():
    with get_db() as conn:
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
            return row[0] or 0
        except sqlite3.OperationalError:
            return 0


def _run_migrations(current):
    if current < 1:
        with get_db() as conn:
            conn.execute("INSERT INTO schema_migrations (version) VALUES (1)")
    if current < 2:
        with get_db() as conn:
            try:
                conn.execute("ALTER TABLE efficiency_records ADD COLUMN sheet_title TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass  # Column may already exist in fresh DB
            conn.execute("INSERT INTO schema_migrations (version) VALUES (2)")
    if current < 3:
        with get_db() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS worker_list (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    worker_name TEXT NOT NULL UNIQUE
                );
            """)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (3)")
    if current < 4:
        with get_db() as conn:
            try:
                conn.execute("ALTER TABLE worker_list ADD COLUMN default_hours REAL DEFAULT 8.0")
            except sqlite3.OperationalError:
                pass
            conn.execute("INSERT INTO schema_migrations (version) VALUES (4)")
    if current < 5:
        with get_db() as conn:
            try:
                conn.execute("ALTER TABLE worker_list ADD COLUMN company TEXT DEFAULT ''")
            except sqlite3.OperationalError:
                pass
            conn.execute("INSERT INTO schema_migrations (version) VALUES (5)")


# ---- Snapshot CRUD ----

def create_snapshot(url, title=""):
    with get_db() as conn:
        cur = conn.execute(
            "INSERT INTO snapshots (spreadsheet_url, spreadsheet_title) VALUES (?, ?)",
            (url, title)
        )
        return cur.lastrowid


def save_snapshot_details(snapshot_id, details):
    """details: list of (sheet_title, worker_name, round, completed_count, total_count)"""
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO snapshot_details (snapshot_id, sheet_title, worker_name, round, completed_count, total_count) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [(snapshot_id, *d) for d in details]
        )


def list_snapshots():
    with get_db() as conn:
        return conn.execute(
            "SELECT id, spreadsheet_url, spreadsheet_title, fetched_at, label "
            "FROM snapshots ORDER BY fetched_at DESC"
        ).fetchall()


def get_snapshot(snapshot_id):
    with get_db() as conn:
        snap = conn.execute("SELECT * FROM snapshots WHERE id=?", (snapshot_id,)).fetchone()
        details = conn.execute(
            "SELECT * FROM snapshot_details WHERE snapshot_id=? ORDER BY sheet_title, round, worker_name",
            (snapshot_id,)
        ).fetchall()
        return snap, details


def get_snapshot_worker_summary(snapshot_id):
    """Return per-worker summary: worker_name, round, total completed, total assigned"""
    with get_db() as conn:
        return conn.execute(
            "SELECT worker_name, round, SUM(completed_count) as completed, SUM(total_count) as total "
            "FROM snapshot_details WHERE snapshot_id=? "
            "GROUP BY worker_name, round ORDER BY round, worker_name",
            (snapshot_id,)
        ).fetchall()


def get_snapshot_details_by_sheet(snapshot_id):
    """Return per-sheet, per-worker breakdown."""
    with get_db() as conn:
        return conn.execute(
            "SELECT sheet_title, worker_name, round, completed_count, total_count "
            "FROM snapshot_details WHERE snapshot_id=? "
            "ORDER BY sheet_title, worker_name, round",
            (snapshot_id,)
        ).fetchall()


def update_snapshot_label(snapshot_id, label):
    with get_db() as conn:
        conn.execute("UPDATE snapshots SET label=? WHERE id=?", (label, snapshot_id))


def delete_snapshot(snapshot_id):
    with get_db() as conn:
        conn.execute("DELETE FROM snapshots WHERE id=?", (snapshot_id,))


# ---- Efficiency Record CRUD ----

def save_efficiency_records(records):
    """records: list of (snapshot_from_id, snapshot_to_id, worker_name, work_done, work_hours)"""
    with get_db() as conn:
        conn.executemany(
            "INSERT INTO efficiency_records (snapshot_from_id, snapshot_to_id, worker_name, work_done, work_hours) "
            "VALUES (?, ?, ?, ?, ?)",
            records
        )


def list_efficiency_records():
    with get_db() as conn:
        return conn.execute(
            "SELECT e.*, s1.label as from_label, s2.label as to_label "
            "FROM efficiency_records e "
            "LEFT JOIN snapshots s1 ON e.snapshot_from_id = s1.id "
            "LEFT JOIN snapshots s2 ON e.snapshot_to_id = s2.id "
            "ORDER BY e.id DESC"
        ).fetchall()


def get_latest_efficiency(from_id, to_id):
    """Return latest efficiency records for a given snapshot pair, grouped by worker."""
    with get_db() as conn:
        return conn.execute(
            "SELECT worker_name, SUM(work_done) as work_done, SUM(work_hours) as work_hours "
            "FROM efficiency_records "
            "WHERE snapshot_from_id=? AND snapshot_to_id=? "
            "GROUP BY worker_name ORDER BY worker_name",
            (from_id, to_id)
        ).fetchall()


def get_snapshot_worker_agg(snapshot_id):
    """Return per-worker aggregated completion (sum across all sheets and rounds)."""
    with get_db() as conn:
        return conn.execute(
            "SELECT worker_name, SUM(completed_count) as completed "
            "FROM snapshot_details WHERE snapshot_id=? "
            "GROUP BY worker_name ORDER BY worker_name",
            (snapshot_id,)
        ).fetchall()


# ---- Worker List CRUD ----

def add_worker(name, company=""):
    with get_db() as conn:
        try:
            conn.execute("INSERT INTO worker_list (worker_name, company) VALUES (?, ?)", (name, company))
            return True
        except sqlite3.IntegrityError:
            return False


def remove_worker(worker_id):
    with get_db() as conn:
        conn.execute("DELETE FROM worker_list WHERE id=?", (worker_id,))


def update_worker_hours(worker_id, hours):
    with get_db() as conn:
        conn.execute("UPDATE worker_list SET default_hours=? WHERE id=?", (hours, worker_id))


def update_worker_company(worker_id, company):
    with get_db() as conn:
        conn.execute("UPDATE worker_list SET company=? WHERE id=?", (company, worker_id))


def list_workers():
    with get_db() as conn:
        return conn.execute("SELECT * FROM worker_list ORDER BY worker_name").fetchall()


def get_worker_hours_map():
    """Return {worker_name: default_hours} dict."""
    with get_db() as conn:
        rows = conn.execute("SELECT worker_name, default_hours FROM worker_list").fetchall()
        return {r["worker_name"]: r["default_hours"] for r in rows}


def get_worker_info_map():
    """Return {worker_name: {company, default_hours}} dict."""
    with get_db() as conn:
        rows = conn.execute("SELECT worker_name, company, default_hours FROM worker_list").fetchall()
        return {r["worker_name"]: {"company": r["company"], "hours": r["default_hours"]} for r in rows}
