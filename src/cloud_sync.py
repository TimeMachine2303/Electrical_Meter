"""
Reads meter readings that have accumulated in the local SQLite database
since the last run, and pushes them to a cloud Postgres database (e.g. a
free Supabase or Neon project) so they're available even if the Pi's disk
is lost.

Setup: add a "cloud" section to config/settings.yaml with your Postgres
connection string, then schedule this to run periodically on the Pi via
cron, e.g. every 15 minutes, a couple minutes after poll_meter.py:
    2,17,32,47 * * * * /usr/bin/python3 /path/to/AutoMeter/src/cloud_sync.py

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
    converter_id TEXT,
    voltage_avg_v DOUBLE PRECISION,
    total_active_power_w DOUBLE PRECISION,
    power_factor DOUBLE PRECISION,
    frequency_hz DOUBLE PRECISION
)
"""

# ADD COLUMN IF NOT EXISTS so a table created by an older version of this
# script (before meter_id/converter_id existed) gets migrated in place.
ALTER_TABLE = """
ALTER TABLE readings
    ADD COLUMN IF NOT EXISTS meter_id TEXT,
    ADD COLUMN IF NOT EXISTS converter_id TEXT
"""

INSERT_ROW = """
INSERT INTO readings (id, timestamp, unit_id, meter_id, converter_id, voltage_avg_v, total_active_power_w, power_factor, frequency_hz)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (id) DO NOTHING
"""


def read_last_synced_id():
    if STATE_PATH.exists():
        return int(STATE_PATH.read_text().strip())
    return 0


def write_last_synced_id(row_id):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(str(row_id))


def ensure_local_schema(local):
    """Guard against running against a local DB that predates
    meter_id/converter_id (normally poll_meter.py already migrated it)."""
    columns = {row[1] for row in local.execute("PRAGMA table_info(readings)")}
    if not columns:
        return  # readings table doesn't exist yet — nothing to migrate
    if "meter_id" not in columns:
        local.execute("ALTER TABLE readings ADD COLUMN meter_id TEXT")
    if "converter_id" not in columns:
        local.execute("ALTER TABLE readings ADD COLUMN converter_id TEXT")
    local.execute("UPDATE readings SET meter_id = unit_id WHERE meter_id IS NULL")
    local.execute("UPDATE readings SET converter_id = unit_id WHERE converter_id IS NULL")
    local.commit()


def fetch_new_rows(last_id):
    local = sqlite3.connect(db_path)
    try:
        ensure_local_schema(local)
        return local.execute(
            """
            SELECT id, timestamp, unit_id, meter_id, converter_id,
                   voltage_avg_v, total_active_power_w, power_factor, frequency_hz
            FROM readings
            WHERE id > ?
            ORDER BY id
            """,
            (last_id,),
        ).fetchall()
    finally:
        local.close()


def ensure_cloud_schema():
    cloud = psycopg2.connect(cloud_url)
    try:
        with cloud.cursor() as cur:
            cur.execute(CREATE_TABLE)
            cur.execute(ALTER_TABLE)
        cloud.commit()
    finally:
        cloud.close()


def push_rows(rows):
    cloud = psycopg2.connect(cloud_url)
    try:
        with cloud.cursor() as cur:
            cur.executemany(INSERT_ROW, rows)
        cloud.commit()
    finally:
        cloud.close()


def main():
    # Runs even with no new rows so a fresh/older cloud table gets
    # created or migrated to the current schema (e.g. the dashboard
    # needs meter_id/converter_id to exist even between syncs).
    ensure_cloud_schema()

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
