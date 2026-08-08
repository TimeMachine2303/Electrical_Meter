"""
Reads live values directly from the Schneider PM2230 over Modbus TCP,
via the Waveshare converter's Modbus TCP-to-RTU passthrough — bypassing
MQTT entirely. Use this to confirm wiring, the meter's Modbus address,
and register numbers are correct before trusting the converter's MQTT
gateway mode to publish them on its own.

Setup: copy config/settings_TEMPLATE.yaml to config/settings.yaml and fill
in the "meter" section with the converter's IP once it's on your WiFi.

Run with:  python src/read_meter.py
"""
from pathlib import Path

import yaml
from pymodbus.client import ModbusTcpClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

with open(SETTINGS_PATH, "r") as f:
    settings = yaml.safe_load(f)

meter = settings["meter"]

# PM2230 holding registers, each a 32-bit float spanning 2 registers.
# Add more from Schneider's register map as you need them for billing.
REGISTERS = {
    "voltage_avg_v": 3035,
    "total_active_power_w": 3059,
    "power_factor": 3083,
    "frequency_hz": 3109,
}


def read_float(client, address, unit):
    result = client.read_holding_registers(address, count=2, slave=unit)
    if result.isError():
        raise IOError(f"Modbus error reading register {address}: {result}")
    # If these values come back as nonsense, the meter likely expects the
    # opposite word order — try Endian.LITTLE for wordorder instead.
    decoder = BinaryPayloadDecoder.fromRegisters(
        result.registers, byteorder=Endian.BIG, wordorder=Endian.BIG
    )
    return decoder.decode_32bit_float()


def main():
    client = ModbusTcpClient(meter["converter_ip"], port=meter["modbus_tcp_port"])
    if not client.connect():
        raise ConnectionError(f"Could not reach converter at {meter['converter_ip']}")

    print(f"Connected. Reading from meter address {meter['modbus_address']}...")
    for name, address in REGISTERS.items():
        value = read_float(client, address, meter["modbus_address"])
        print(f"  {name}: {value:.2f}")

    client.close()


if __name__ == "__main__":
    main()
