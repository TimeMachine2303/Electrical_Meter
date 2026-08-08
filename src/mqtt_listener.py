"""
Listens for meter readings from the RS485-to-WiFi converters over MQTT,
and saves each one into a SQLite database.

Setup: copy config/settings_TEMPLATE.yaml to config/settings.yaml and fill
in your real WiFi/MQTT/converter details first.

Run with:  python src/mqtt_listener.py
"""
import json
import sqlite3
from datetime import datetime
from pathlib import Path

import paho.mqtt.client as mqtt
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

with open(SETTINGS_PATH, "r") as f:
    settings = yaml.safe_load(f)

db_path = PROJECT_ROOT / settings["database"]["path"]
db_path.parent.mkdir(parents=True, exist_ok=True)
db = sqlite3.connect(db_path)
db.execute(
    """
    CREATE TABLE IF NOT EXISTS readings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp DATETIME NOT NULL,
        unit_id TEXT NOT NULL,
        meter_id TEXT,
        active_energy REAL,
        reactive_energy REAL,
        power REAL
    )
    """
)
db.commit()

# "building/+/meter" matches building/unit1/meter, building/unit2/meter, etc.
TOPIC_FILTER = "building/+/meter"


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"Connected to MQTT broker (reason_code={reason_code})")
    client.subscribe(TOPIC_FILTER)
    print(f"Subscribed to {TOPIC_FILTER}")


def on_message(client, userdata, msg):
    unit_id = msg.topic.split("/")[1]
    try:
        payload = json.loads(msg.payload.decode())
    except json.JSONDecodeError:
        print(f"Ignoring non-JSON message on {msg.topic}: {msg.payload!r}")
        return

    # payload.get(...) below expects the Waveshare converter's per-register
    # JSON keywords to be named "active_energy", "reactive_energy", "power"
    # (set when you map each Modbus register in the converter's own config).
    # Anything named differently comes through as None — the print at the
    # end of this function always shows the raw payload, so a None where you
    # expected a number means the keyword doesn't match yet.
    db.execute(
        """
        INSERT INTO readings (timestamp, unit_id, meter_id, active_energy, reactive_energy, power)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now().isoformat(),
            unit_id,
            payload.get("meter_id"),
            payload.get("active_energy"),
            payload.get("reactive_energy"),
            payload.get("power"),
        ),
    )
    db.commit()
    print(f"Stored reading for {unit_id}: {payload}")


client = mqtt.Client(callback_api_version=mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message
client.connect(settings["mqtt"]["broker_host"], settings["mqtt"]["broker_port"])
client.loop_forever()
