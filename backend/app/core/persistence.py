"""
Simple SQLite persistence for projects.
No ORM — just sqlite3 with JSON blobs for spec/model.
"""
import sqlite3
import json
import os

_DB_PATH = os.path.join(os.path.dirname(__file__), "../../projects.db")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS projects (
                id           TEXT PRIMARY KEY,
                name         TEXT NOT NULL,
                address      TEXT DEFAULT '',
                status       TEXT DEFAULT 'created',
                spec         TEXT NOT NULL,
                building_model TEXT,
                stories      INTEGER DEFAULT 0,
                units        INTEGER DEFAULT 0,
                sqft         INTEGER DEFAULT 0,
                seismic      TEXT DEFAULT 'D',
                flood        TEXT DEFAULT 'X',
                created_at   TEXT DEFAULT (datetime('now')),
                updated_at   TEXT DEFAULT (datetime('now'))
            )
        """)


def upsert_project(
    pid: str,
    name: str,
    address: str,
    spec: dict,
    status: str = "created",
    building_model: dict | None = None,
    stories: int = 0,
    units: int = 0,
    sqft: int = 0,
    seismic: str = "D",
    flood: str = "X",
) -> None:
    with _conn() as db:
        db.execute(
            """
            INSERT INTO projects
                (id, name, address, status, spec, building_model,
                 stories, units, sqft, seismic, flood, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(id) DO UPDATE SET
                name=excluded.name,
                address=excluded.address,
                status=excluded.status,
                spec=excluded.spec,
                building_model=excluded.building_model,
                stories=excluded.stories,
                units=excluded.units,
                sqft=excluded.sqft,
                seismic=excluded.seismic,
                flood=excluded.flood,
                updated_at=datetime('now')
            """,
            (
                pid, name, address, status,
                json.dumps(spec),
                json.dumps(building_model) if building_model else None,
                stories, units, sqft, seismic, flood,
            ),
        )


def get_project(pid: str) -> dict | None:
    with _conn() as db:
        row = db.execute("SELECT * FROM projects WHERE id = ?", (pid,)).fetchone()
    return _hydrate(row) if row else None


def list_projects() -> list:
    with _conn() as db:
        rows = db.execute(
            "SELECT * FROM projects ORDER BY updated_at DESC"
        ).fetchall()
    return [_hydrate(r) for r in rows]


def _hydrate(row: sqlite3.Row) -> dict:
    d = dict(row)
    d["spec"] = json.loads(d["spec"]) if d["spec"] else {}
    d["building_model"] = json.loads(d["building_model"]) if d["building_model"] else None
    return d
