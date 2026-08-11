# Electrical_Meter

Polls electrical meters (Schneider PM2230 over Modbus TCP, via Waveshare
converters), stores readings locally, syncs them to a cloud Postgres
database, and shows them on a website.

## Components

- [`src/poll_meter.py`](src/poll_meter.py) — polls each configured meter
  and stores readings in a local SQLite database. Runs on a schedule (e.g.
  cron) near the meters.
- [`src/cloud_sync.py`](src/cloud_sync.py) — pushes new local readings up
  to a cloud Postgres database (e.g. Supabase). Runs on a schedule shortly
  after `poll_meter.py`.
- [`src/dashboard.py`](src/dashboard.py) — a Streamlit website reading
  from the cloud database, with **By Meter** and **By Converter** views.

## Setup

1. Create `config/settings.yaml` (gitignored) and fill in your meters'
   IPs, a `meter_id`/`converter_id` per meter, and your cloud
   `database_url` — see the comments in that file for the format.
2. `pip install -r requirements.txt`
3. Schedule `poll_meter.py` and `cloud_sync.py` via cron near the meters.

## Running the dashboard

Locally (reads `config/settings.yaml`):

```
streamlit run src/dashboard.py
```

Deployed on [Streamlit Community Cloud](https://streamlit.io/cloud): push
this repo to GitHub, create an app pointing at `src/dashboard.py`, then
paste your `database_url` into the app's Settings -> Secrets (see
`.streamlit/secrets.toml.example`) — `config/settings.yaml` isn't
committed, so the dashboard won't find your DB URL there once deployed.
