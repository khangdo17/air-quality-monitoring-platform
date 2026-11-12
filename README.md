# Ho Chi Minh Air Quality & Weather Monitoring Platform

Near-real-time district-level air quality and weather intelligence for Ho Chi
Minh City, with 24 hours of hourly history.

Live demo: https://www.khangdo.dev/air-quality

Public GitHub repository:
https://github.com/khangdo17/air-quality-monitoring-platform

This repository is safe to publish as a standalone public project. The
production dashboard frontend is embedded in the private `khangdo.dev`
portfolio; this repo contains the public pipeline code, Supabase schema,
workflow, and documentation.

## Project Overview

The platform collects air quality and weather estimates for 18 Ho Chi Minh City
districts, stores hourly history plus the latest normalized record for each
district in Supabase PostgreSQL, and powers the live `/air-quality` dashboard
on `khangdo.dev`.

It demonstrates:

- Scheduled data ingestion with GitHub Actions
- A primary/fallback source strategy with per-source observability
- API integration with Open-Meteo, and with the Google Air Quality API
  (implemented, currently disabled — see Data Sources)
- Working inside a commercial API's caching terms and free tier
- PostgreSQL schema design for both a dashboard snapshot and hourly history
- Supabase REST upserts with service-role writes
- Public read access through Supabase row-level security
- Clear communication of model-based data limitations

## Data Sources

| Source | Used for | Resolution | Update frequency | Key required |
| --- | --- | --- | --- | --- |
| Google Air Quality API (`history:lookup`) | Primary air quality — **currently disabled** | ~500 m | Hourly | Yes |
| Open-Meteo Air Quality (CAMS global) | Air quality fallback, SO2/CO/UV | ~25-45 km, 3-hourly steps | ~2x daily | No |
| Open-Meteo Forecast | Weather | ~1-11 km | Hourly | No |

> **Google is switched off.** `GOOGLE_AQ_ENABLED` defaults to `false`, so the
> pipeline currently runs on Open-Meteo CAMS alone. Google Maps Platform Terms
> of Service 3.2.3(e) forbids using a Core Service "with or near a non-Google
> Map", and `/air-quality` uses a custom Three.js map. See
> [docs/attribution-and-terms.md](docs/attribution-and-terms.md) for the clause,
> the options and what the dashboard would need first.

The Google integration is built and tested; it is off by policy, not by
omission. The rest of this section describes it as designed.

Air quality moved to Google because CAMS global resolves Ho Chi Minh City into
roughly one or two grid cells. All 18 districts therefore reported nearly
identical values, and a district-level map had little district-level signal to
show. At ~500 m the districts genuinely differ.

Open-Meteo remains the weather source and the air quality fallback. **Without
`GOOGLE_AQ_ENABLED=true` the pipeline still runs end to end** on Open-Meteo
alone — which is the current configuration.

## Architecture

```text
Google Air Quality API (history:lookup, even hours)
Open-Meteo Air Quality API (CAMS, fallback)
Open-Meteo Forecast API (weather)
        |
        v
GitHub Actions hourly Python ingestion
        |
        v
Supabase PostgreSQL
  air_quality_hourly · weather_hourly
  district_air_weather_latest · air_quality_pipeline_runs
        |
        v
khangdo.dev /air-quality dashboard
```

See [docs/architecture.md](docs/architecture.md).

## Data Pipeline

`scripts/fetch_air_quality_weather.py` runs hourly and:

1. Loads credentials from GitHub Actions secrets or a local `.env`.
2. Fetches Open-Meteo air quality and weather for 18 districts, batched six
   per request.
3. On **even hours**, calls Google `history:lookup` once per district for the
   last 4 hours.
4. Upserts every weather hour at or before the current hour into
   `weather_hourly`.
5. Upserts Google hours into `air_quality_hourly` as `google_aq`, falling back
   to CAMS hours as `open_meteo_cams` where Google did not supply a district.
6. Rebuilds `district_air_weather_latest` from the newest stored hour,
   preferring Google, so the existing dashboard keeps working unchanged.
7. Records per-source status and API call counts in
   `air_quality_pipeline_runs`.

The 4-hour window is double the 2-hour cadence on purpose: GitHub Actions cron
is best-effort, and a doubled window means a run that never fires loses no
hours, since the runs either side already cover them. It costs nothing extra —
one district-run is a single response page, and therefore a single billable
call, at any of these window sizes.

## Terms, Attribution and Cost

Read [docs/attribution-and-terms.md](docs/attribution-and-terms.md) before
changing how Google data is fetched or displayed. The short version:

**Storage.** Google Maps Platform Service Specific Terms, Table 2.2.1, permit
caching current conditions and hourly forecast values for "One hour, after
which Customer must delete the cached Google Maps Content", but permit caching
"Historic values for a specific location and given time range" "Until the
Agreement is terminated". The pipeline therefore calls `history:lookup`
**only** and never `currentConditions` or `forecast`.

**Attribution.** The dashboard must display, on or next to the data:

```text
Source: Includes air quality data from Google
```

Because the dashboard also shows a risk bucket and recommendation it computes
itself, `Includes data from Google Maps` applies to those. The attribution must
follow the live source: read
`district_air_weather_latest.air_quality_source` and show the Open-Meteo/CAMS
credit when it is `open_meteo_cams`.

**Cost.** The Air Quality API free tier is 10,000 calls/month shared across all
its methods. Planned usage is 18 districts x 12 runs/day x 30 days = **6,480
calls/month**. History is billed per response page; the script requests one
page and never follows `nextPageToken`, so a district-run is always exactly one
call. Set a daily quota cap of 300 and a $1 budget alert — see
[docs/google-cloud-setup.md](docs/google-cloud-setup.md).

**Permitted use.** Section 2.1 limits Air Quality API data to "(a) air quality
based routing solutions" and "(b) Customer environmental risk indices and
correlational research". A district risk dashboard is plausibly (b), but the
clause is narrower than it first appears and is worth reading yourself.

## Supabase Schema Setup

New project:

1. Create a Supabase project.
2. Open the SQL editor.
3. Paste and run `supabase/schema.sql`.

Existing project: run the files in `supabase/migrations/` in filename order
instead. They are additive and safe to re-run.

```text
supabase/migrations/20261111120000_add_hourly_history.sql
supabase/migrations/20261111120100_hourly_history_retention.sql
```

The schema creates:

- `district_air_weather_latest` — dashboard snapshot, one row per district
- `air_quality_hourly` — hourly air quality history, keyed by source
- `weather_hourly` — hourly weather history
- `air_quality_pipeline_runs` — ingestion metadata
- Indexes for dashboard reads
- RLS policies that allow anon `SELECT` only
- RLS policies that allow `service_role` full access for ingestion
- An optional `prune_hourly_history()` function for 30-day retention

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
GOOGLE_MAPS_API_KEY   # optional; without it, Open-Meteo CAMS is used
```

The workflow uses `CITY_TIMEZONE=Asia/Bangkok` for Ho Chi Minh City UTC+7
timestamps and runs hourly at minute 7.

Never commit a real Supabase service role key, Google API key, `.env`, or
deployment secret.

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
export GOOGLE_MAPS_API_KEY="..."      # optional
```

Run the pipeline:

```bash
python scripts/fetch_air_quality_weather.py
```

`GOOGLE_AIR_QUALITY_MODE` controls the Google call:

| Value | Behaviour |
| --- | --- |
| `auto` (default) | Call Google on even hours only |
| `always` | Call Google every run — doubles call volume, use sparingly |
| `never` | Ignore the key and use Open-Meteo CAMS only |

The run prints a JSON summary including `google_api_calls`, which should be
exactly 18 on a scheduled hour.

## Map Visualization

The live dashboard includes an interactive Ho Chi Minh City map:

- Marker mode shows one marker per configured district.
- Marker color follows US AQI status buckets.
- District map mode is prepared for a private portfolio GeoJSON file at
  `src/data/hcm-districts.geojson`.
- If boundary data is missing, the dashboard falls back to coordinate markers.

District-level values are estimated from modelled grid data, not physical
sensors in every district.

See [docs/map-visualization.md](docs/map-visualization.md) for more detail.

## Data Limitations

- Both Google and Open-Meteo values are model-based and may differ from
  official sensor networks.
- District values are coordinate estimates. ~500 m resolution is a far better
  estimate than a 25-45 km grid, but it is still not a monitor per district.
- Air quality and weather endpoints update at different times.
- NO2 and O3 arrive from Google in ppb and from CAMS in µg/m³. The pipeline
  converts to µg/m³ at 25 °C and 1013.25 hPa so one column means one thing;
  that conversion is an approximation. See
  [docs/data-model.md](docs/data-model.md).
- A 24-hour window can mix sources if Google was unavailable for part of it.
  `air_quality_hourly.source` records which was used for every hour.
- GitHub Actions schedules are best-effort and may not run exactly on the hour.
  A missed even hour leaves a gap no later run backfills.
- `weather_hourly` stores only hours at or before the current hour, so it never
  contains forecast values — but `precipitation_probability` is a forecast
  quantity even for past hours.

## Tech Stack

- Python
- GitHub Actions
- Supabase
- PostgreSQL
- Google Air Quality API
- Open-Meteo API
- React/Next.js frontend embedded in `khangdo.dev`

## Screenshots

Add production screenshots to `screenshots/` after deployment.

Suggested screenshots:

- Dashboard map overview
- District detail card
- 24-hour history chart
- Metric cards
- Pipeline architecture section
- Mobile layout

## Interview Talking Points

- Why the public project repo is separated from the private portfolio source
- Why a commercial API's caching terms drove the endpoint choice: history is
  storable, current conditions are not
- How a 10,000 call/month free tier shaped the schedule, the page size, and the
  decision never to follow `nextPageToken`
- Why the fallback source is a first-class design element, not an error path
- Why `air_quality_hourly` is keyed by source instead of overwriting
- Why the latest table is rebuilt from stored history rather than from the
  current run's payloads
- How unit normalization between ppb and µg/m³ protects a cross-source chart
- How Supabase RLS separates public reads from service-role writes
- How the dashboard degrades gracefully when live data is unavailable
- Tradeoffs of grid-model data compared with physical sensors

## Repository Separation

Do not include:

- Private portfolio source code
- Real environment variables
- Supabase service role key
- Google API key
- Personal deployment credentials
- Unrelated portfolio files

The only production frontend reference is:

https://www.khangdo.dev/air-quality
