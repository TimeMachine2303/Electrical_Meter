"""
Reads meter readings that have accumulated in the local SQLite database
since the last run, and pushes them to a cloud Postgres database (e.g. a
free Supabase or Neon project) so they're available even if the Pi's disk
is lost.

Setup: add a "cloud" section to config/settings.yaml with your Postgres
connection string (see config/settings_TEMPLATE.yaml), then schedule this
to run periodically on the Pi via cron, e.g. every 5 minutes:
    */5 * * * * /usr/bin/python3 /path/to/AutoMeter/src/cloud_sync.py

Run manually with:  python src/cloud_sync.py
"""
from pathlib import Path
import sqlite3

import psycopg2
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"
STATE_PATH = PROJECT_ROOT / "data" / "cloud_sync_state.txt"

with open(SETTINGS_PATH, "r") as f:
    settings = yaml.safe_load(f)

db_path = PROJECT_ROOT / settings["database"]["path"]
cloud_url = settings["cloud"]["database_url"]

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY,
    timestamp TIMESTAMPTZ NOT NULL,
    unit_id TEXT NOT NULL,
    meter_id TEXT,
    active_energy DOUBLE PRECISION,
    reactive_energy DOUBLE PRECISION,
    power DOUBLE PRECISION
)
"""

INSERT_ROW = """
INSERT INTO readings (id, timestamp, unit_id, meter_id, active_energy, reactive_energy, power)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO NOTHING
"""


def read_last_synced_id():
    if STATE_PATH.exists():
        return int(STATE_PATH.read_text().strip())
    return 0


def write_last_synced_id(row_id):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(str(row_id))


def fetch_new_rows(last_id):
    local = sqlite3.connect(db_path)
    try:
        return local.execute(
            """
            SELECT id, timestamp, unit_id, meter_id, active_energy, reactive_energy, power
            FROM readings
            WHERE id > ?
            ORDER BY id
            """,
            (last_id,),
        ).fetchall()
    finally:
        local.close()


def push_rows(rows):
    cloud = psycopg2.connect(cloud_url)
    try:
        with cloud.cursor() as cur:
            cur.execute(CREATE_TABLE)
            cur.executemany(INSERT_ROW, rows)
        cloud.commit()
    finally:
        cloud.close()


def main():
    last_id = read_last_synced_id()
    rows = fetch_new_rows(last_id)

    if not rows:
        print("No new readings to sync.")
        return

    push_rows(rows)
    write_last_synced_id(rows[-1][0])
    print(f"Synced {len(rows)} reading(s), up to local id {rows[-1][0]}.")


if __name__ == "__main__":
    main()
