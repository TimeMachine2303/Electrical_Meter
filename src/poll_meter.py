"""
Polls live values directly from the Schneider PM2230 over Modbus TCP, via
the Waveshare converter's Modbus TCP-to-RTU gateway mode, and saves each
reading into the local SQLite database. Supports multiple meters/converters
in a single run (e.g. one per floor) — a failure on one meter is logged and
skipped, it doesn't stop the others from being read and stored.

Polls the meter directly instead of relying on the converter's built-in
MQTT publishing, which depends on undocumented, unreliable firmware
behavior.

Setup: fill in the "meters" list in config/settings.yaml (one entry per
converter), then schedule this to run periodically via cron, e.g. every
5 minutes:
    */5 * * * * /path/to/AutoMeter/venv/bin/python /path/to/AutoMeter/src/poll_meter.py

Run manually with:  python src/poll_meter.py
"""
from datetime import datetime
from pathlib import Path
import sqlite3
import sys

import yaml
from pymodbus.client import ModbusTcpClient
from pymodbus.client.mixin import ModbusClientMixin

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

with open(SETTINGS_PATH, "r") as f:
    settings = yaml.safe_load(f)

if "meters" not in settings:
    raise KeyError(
        "settings.yaml has no 'meters' list. The config format changed from a "
        "single 'meter:' dict to a 'meters:' list (one entry per converter) — "
        "update your config/settings.yaml accordingly."
    )

meters = settings["meters"]
db_path = PROJECT_ROOT / settings["database"]["path"]

DEFAULT_MODBUS_TCP_PORT = 8899
DEFAULT_MODBUS_ADDRESS = 1

# PM2230 holding registers, each a 32-bit float spanning 2 registers.
# Add more from Schneider's register map as you need them for billing.
REGISTERS = {
    "voltage_avg_v": 3035,
    "total_active_power_w": 3059,
    "power_factor": 3083,
    "frequency_hz": 3109,
}

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME NOT NULL,
    unit_id TEXT NOT NULL,
    voltage_avg_v REAL,
    total_active_power_w REAL,
    power_factor REAL,
    frequency_hz REAL
)
"""

INSERT_ROW = """
INSERT INTO readings (timestamp, unit_id, voltage_avg_v, total_active_power_w, power_factor, frequency_hz)
VALUES (?, ?, ?, ?, ?, ?)
"""


def read_float(client, address, unit):
    result = client.read_holding_registers(address, count=2, device_id=unit)
    if result.isError():
        raise IOError(f"Modbus error reading register {address}: {result}")
    # If these values come back as nonsense, the meter likely expects the
    # opposite word order — try word_order="little" instead.
    return client.convert_from_registers(
        result.registers,
        data_type=ModbusClientMixin.DATATYPE.FLOAT32,
        word_order="big",
    )


def read_all_registers(client, modbus_address):
    return {
        name: read_float(client, address, modbus_address)
        for name, address in REGISTERS.items()
    }


def store_reading(unit_id, values):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    try:
        db.execute(CREATE_TABLE)
        db.execute(
            INSERT_ROW,
            (
                datetime.now().isoformat(),
                unit_id,
                values["voltage_avg_v"],
                values["total_active_power_w"],
                values["power_factor"],
                values["frequency_hz"],
            ),
        )
        db.commit()
    finally:
        db.close()


def poll_one_meter(meter_cfg):
    converter_ip = meter_cfg["converter_ip"]
    port = meter_cfg.get("modbus_tcp_port", DEFAULT_MODBUS_TCP_PORT)
    modbus_address = meter_cfg.get("modbus_address", DEFAULT_MODBUS_ADDRESS)
    unit_id = meter_cfg["unit_id"]

    client = ModbusTcpClient(converter_ip, port=port, timeout=5)
    if not client.connect():
        raise ConnectionError(f"Could not reach converter at {converter_ip}:{port}")
    try:
        values = read_all_registers(client, modbus_address)
    finally:
        client.close()

    store_reading(unit_id, values)
    return values


def main():
    ok, failed = 0, []
    for meter_cfg in meters:
        unit_id = meter_cfg.get("unit_id", meter_cfg.get("converter_ip", "?"))
        try:
            values = poll_one_meter(meter_cfg)
        except Exception as e:
            failed.append(unit_id)
            print(f"[{unit_id}] ERROR: {e}")
            continue
        ok += 1
        print(f"[{unit_id}] Stored reading: {values}")

    print(f"Done: {ok}/{len(meters)} meter(s) polled successfully.")
    if failed:
        print(f"Failed: {', '.join(failed)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
