# Ho Chi Minh Air Quality & Weather Monitoring Platform

Near-real-time district-level air quality and weather intelligence for Ho Chi
Minh City.

Live demo: https://www.khangdo.dev/air-quality

Public GitHub repository:
https://github.com/dokhang1703/air-quality-monitoring-platform

This repository is safe to publish as a standalone public project. The
production dashboard frontend is embedded in the private `khangdo.dev`
portfolio; this repo contains the public pipeline code, Supabase schema,
workflow, and documentation.

## Project Overview

The platform collects air quality and weather estimates for 18 Ho Chi Minh City
districts, stores the latest normalized record for each district in Supabase
PostgreSQL, and powers the live `/air-quality` dashboard on `khangdo.dev`.

It demonstrates:

- Scheduled data ingestion with GitHub Actions
- API integration with Open-Meteo Weather and Air Quality APIs
- PostgreSQL schema design for dashboard-ready district data
- Supabase REST upserts with service-role writes
- Public read access through Supabase row-level security
- Clear communication of model-based data limitations

## Architecture

```text
Open-Meteo Weather API + Open-Meteo Air Quality API
        |
        v
GitHub Actions scheduled Python ingestion
        |
        v
Supabase PostgreSQL
        |
        v
khangdo.dev /air-quality dashboard
```

## Data Pipeline

`scripts/fetch_air_quality_weather.py` runs on a schedule and:

1. Loads Supabase credentials from GitHub Actions secrets or local `.env`.
2. Iterates through 18 configured Ho Chi Minh City districts.
3. Fetches Open-Meteo air quality data for each district coordinate.
4. Fetches Open-Meteo weather data for each district coordinate.
5. Normalizes AQI, pollutants, weather, risk level, and recommendation fields.
6. Upserts rows into `district_air_weather_latest` using `district` as the conflict key.
7. Writes run metadata into `air_quality_pipeline_runs`.

## Supabase Schema Setup

1. Create a Supabase project.
2. Open the SQL editor.
3. Paste and run `supabase/schema.sql`.

The schema creates:

- `district_air_weather_latest`
- `air_quality_pipeline_runs`
- Indexes for dashboard reads
- RLS policies that allow anon `SELECT` only
- RLS policies that allow `service_role` full access for ingestion

The private portfolio frontend should use the Supabase publishable/anon key
through `NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_ANON_KEY`.

The service role key is only for ingestion. Store it in GitHub Actions secrets
or a local shell environment. Never expose it in frontend code or commit it to
this public repository.

## GitHub Actions Secrets Setup

Add these repository secrets:

```text
SUPABASE_URL
SUPABASE_SERVICE_ROLE_KEY
```

The workflow uses `CITY_TIMEZONE=Asia/Bangkok` for Ho Chi Minh City UTC+7
timestamps.

Never commit a real Supabase service role key, `.env`, or deployment secret.

## Run Ingestion Locally

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Export credentials in your local shell. Do not commit them:

```bash
export SUPABASE_URL="..."
export SUPABASE_SERVICE_ROLE_KEY="..."
```

Run the pipeline:

```bash
python scripts/fetch_air_quality_weather.py
```

## Map Visualization

The live dashboard includes an interactive Ho Chi Minh City map:

- Marker mode shows one marker per configured district.
- Marker color follows US AQI status buckets.
- District map mode is prepared for a private portfolio GeoJSON file at
  `src/data/hcm-districts.geojson`.
- If boundary data is missing, the dashboard falls back to coordinate markers.

District-level values are estimated using coordinate-based forecast grid data,
not physical sensors in every district.

See `docs/map-visualization.md` for more detail.

## Data Limitations

- Open-Meteo data is model-based and may differ from official sensor networks.
- District values are coordinate estimates, not physical monitors in every district.
- Air quality and weather endpoints can update at different times.
- GitHub Actions schedules are best-effort and may not run exactly every 15 minutes.
- The `district_air_weather_latest` table stores the latest dashboard snapshot,
  not a full time-series history.

## Tech Stack

- Python
- GitHub Actions
- Supabase
- PostgreSQL
- Open-Meteo API
- React/Next.js frontend embedded in `khangdo.dev`

## Screenshots

Add production screenshots to `screenshots/` after deployment.

Suggested screenshots:

- Dashboard map overview
- District detail card
- Metric cards
- Pipeline architecture section
- Mobile layout

## Interview Talking Points

- Why the public project repo is separated from the private portfolio source
- How the ingestion script handles district-level coordinate estimates
- Why `district_air_weather_latest` uses an upsert by district
- How pipeline run metadata supports operational debugging
- How Supabase RLS separates public reads from service-role writes
- How the dashboard degrades gracefully when live data is unavailable
- Tradeoffs of latest-snapshot storage versus full historical time-series
- Data quality limits of forecast-grid data compared with physical sensors

## Repository Separation

Do not include:

- Private portfolio source code
- Real environment variables
- Supabase service role key
- Personal deployment credentials
- Unrelated portfolio files

The only production frontend reference is:

https://www.khangdo.dev/air-quality
