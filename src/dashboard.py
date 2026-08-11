"""
Website for the readings cloud_sync.py pushes to the cloud Postgres
database — shown meter-by-meter and converter-by-converter.

Local run:
    streamlit run src/dashboard.py

Deploy (Streamlit Community Cloud):
    Push this repo to GitHub, create an app pointing at src/dashboard.py,
    then in the app's Settings -> Secrets paste:
        [cloud]
        database_url = "postgresql://...same value as config/settings.yaml..."
    (see .streamlit/secrets.toml.example). Falls back to
    config/settings.yaml for local runs where secrets.toml isn't set up.
"""
import warnings
from pathlib import Path

import pandas as pd
import psycopg2
import streamlit as st
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_PATH = PROJECT_ROOT / "config" / "settings.yaml"

TIME_RANGES = {
    "Last 24 hours": 24,
    "Last 7 days": 24 * 7,
    "Last 30 days": 24 * 30,
    "All time": None,
}

COLUMN_LABELS = {
    "converter_id": "Converter",
    "voltage_avg_v": "Voltage (V)",
    "total_active_power_w": "Power (W)",
    "power_factor": "Power factor",
    "frequency_hz": "Frequency (Hz)",
    "meters": "Meters",
}

st.set_page_config(page_title="AutoMeter", page_icon="⚡", layout="wide")


def get_database_url():
    try:
        secret = st.secrets["cloud"]["database_url"]
    except (KeyError, FileNotFoundError, st.errors.StreamlitSecretNotFoundError):
        secret = None
    if secret:
        return secret
    if SETTINGS_PATH.exists():
        with open(SETTINGS_PATH, "r") as f:
            settings = yaml.safe_load(f) or {}
        db_url = settings.get("cloud", {}).get("database_url")
        if db_url:
            return db_url
    st.error(
        "No cloud database URL found. Add one to .streamlit/secrets.toml "
        "(see .streamlit/secrets.toml.example) or to config/settings.yaml."
    )
    st.stop()


@st.cache_data(ttl=60)
def load_readings():
    conn = psycopg2.connect(get_database_url())
    try:
        with warnings.catch_warnings():
            # pandas warns about non-SQLAlchemy connections; psycopg2 works fine here.
            warnings.simplefilter("ignore", UserWarning)
            df = pd.read_sql(
                """
                SELECT timestamp, unit_id, meter_id, converter_id,
                       voltage_avg_v, total_active_power_w, power_factor, frequency_hz
                FROM readings
                ORDER BY timestamp
                """,
                conn,
            )
    finally:
        conn.close()

    df["timestamp"] = pd.to_datetime(df["timestamp"])
    # Rows written before meter_id/converter_id existed only have unit_id.
    df["meter_id"] = df["meter_id"].fillna(df["unit_id"])
    df["converter_id"] = df["converter_id"].fillna(df["unit_id"])
    return df


def latest_per_meter(df):
    return df.sort_values("timestamp").groupby("meter_id").tail(1).set_index("meter_id")


def render_meter_tab(df, latest):
    st.subheader("Latest reading per meter")
    table = latest[["converter_id", "voltage_avg_v", "total_active_power_w", "power_factor", "frequency_hz"]]
    st.dataframe(table.rename(columns=COLUMN_LABELS), width='stretch')

    meter_ids = sorted(df["meter_id"].unique())
    selected = st.selectbox("Drill into a meter", meter_ids, key="meter_select")
    meter_df = df[df["meter_id"] == selected].set_index("timestamp")

    c1, c2 = st.columns(2)
    with c1:
        st.caption("Total active power (W)")
        st.line_chart(meter_df["total_active_power_w"])
    with c2:
        st.caption("Average voltage (V)")
        st.line_chart(meter_df["voltage_avg_v"])

    c3, c4 = st.columns(2)
    with c3:
        st.caption("Power factor")
        st.line_chart(meter_df["power_factor"])
    with c4:
        st.caption("Frequency (Hz)")
        st.line_chart(meter_df["frequency_hz"])


def render_converter_tab(df, latest):
    st.subheader("Latest reading per converter (summed across its meters)")
    conv_latest = latest.reset_index().groupby("converter_id").agg(
        meters=("meter_id", "nunique"),
        total_active_power_w=("total_active_power_w", "sum"),
        voltage_avg_v=("voltage_avg_v", "mean"),
    )
    st.dataframe(conv_latest.rename(columns=COLUMN_LABELS), width='stretch')

    converter_ids = sorted(df["converter_id"].unique())
    selected = st.selectbox("Drill into a converter", converter_ids, key="converter_select")
    conv_df = df[df["converter_id"] == selected]
    meter_ids = sorted(conv_df["meter_id"].unique())
    st.caption(f"Meters on {selected}: {', '.join(meter_ids)}")

    pivot = conv_df.pivot_table(index="timestamp", columns="meter_id", values="total_active_power_w")
    pivot = pivot.resample("15min").mean().ffill(limit=4)

    st.caption("Combined power draw across meters on this converter (W)")
    st.line_chart(pivot.sum(axis=1))

    if len(meter_ids) > 1:
        st.caption("Per-meter power draw on this converter (W)")
        st.line_chart(pivot)


def main():
    st.title("⚡ AutoMeter Dashboard")

    df = load_readings()
    if df.empty:
        st.warning("No readings in the cloud database yet.")
        st.stop()

    if st.sidebar.button("Refresh data"):
        load_readings.clear()
        st.rerun()

    range_label = st.sidebar.selectbox("Time range", list(TIME_RANGES.keys()))
    hours = TIME_RANGES[range_label]
    if hours is not None:
        cutoff = df["timestamp"].max() - pd.Timedelta(hours=hours)
        df = df[df["timestamp"] >= cutoff]

    if df.empty:
        st.warning("No readings in the selected time range.")
        st.stop()

    latest = latest_per_meter(df)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Meters", df["meter_id"].nunique())
    col2.metric("Converters", df["converter_id"].nunique())
    col3.metric("Total power now", f"{latest['total_active_power_w'].sum():,.0f} W")
    col4.metric("Latest reading", df["timestamp"].max().strftime("%Y-%m-%d %H:%M"))

    tab_meter, tab_converter = st.tabs(["By Meter", "By Converter"])
    with tab_meter:
        render_meter_tab(df, latest)
    with tab_converter:
        render_converter_tab(df, latest)


if __name__ == "__main__":
    main()
