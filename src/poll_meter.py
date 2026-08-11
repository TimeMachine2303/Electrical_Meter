"""
Polls live values directly from the Schneider PM2230 over Modbus TCP, via
the Waveshare converter's Modbus TCP-to-RTU gateway mode, and saves each
reading into the local SQLite database.

Polls the meter directly instead of relying on the converter's built-in
MQTT publishing, which depends on undocumented, unreliable firmware
behavior.

Setup: copy config/settings_TEMPLATE.yaml to config/settings.yaml and fill
in the "meter" section, then schedule this to run periodically via cron,
e.g. every 5 minutes:
    */5 * * * * /path/to/AutoMeter/venv/bin/python /path/to/AutoMeter/src/poll_meter.py

Run manually with:  python src/poll_meter.py
"""
from datetime import datetime
from pathlib import Path
import sqlite3

import yaml
from pymodbus.client import ModbusTcpClient
from pymodbus.client.mixin import ModbusClientMixin

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

with open(SETTINGS_PATH, "r") as f:
    settings = yaml.safe_load(f)

meter = settings["meter"]
db_path = PROJECT_ROOT / settings["database"]["path"]

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


def read_all_registers(client):
    return {
        name: read_float(client, address, meter["modbus_address"])
        for name, address in REGISTERS.items()
    }


def store_reading(values):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    try:
        db.execute(CREATE_TABLE)
        db.execute(
            INSERT_ROW,
            (
                datetime.now().isoformat(),
                meter["unit_id"],
                values["voltage_avg_v"],
                values["total_active_power_w"],
                values["power_factor"],
                values["frequency_hz"],
            ),
        )
        db.commit()
    finally:
        db.close()


def main():
    client = ModbusTcpClient(meter["converter_ip"], port=meter["modbus_tcp_port"])
    if not client.connect():
        raise ConnectionError(f"Could not reach converter at {meter['converter_ip']}")

    try:
        values = read_all_registers(client)
    finally:
        client.close()

    store_reading(values)
    print(f"Stored reading for {meter['unit_id']}: {values}")


if __name__ == "__main__":
    main()
