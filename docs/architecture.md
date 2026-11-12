# Architecture

## Repository Boundary

The project is intentionally split:

- Private portfolio repo: hosts the production `/air-quality` dashboard on
  `khangdo.dev`.
- Public project repo: contains the publish-safe ingestion pipeline, Supabase
  schema, GitHub Actions workflow, and documentation.

Recruiters can review this public repository without seeing the private
portfolio source.

## Data Flow

```text
Google Air Quality API            Open-Meteo Air Quality      Open-Meteo
  history:lookup only               (CAMS global)              Forecast API
  ~500 m, hourly                    ~25-45 km, 2x daily        hourly
  even hours only                   every hour                 every hour
        |                                 |                         |
        |  primary air quality            |  fallback + SO2/CO/UV   |  weather
        +---------------+-----------------+-------------------------+
                        |
                        v
             GitHub Actions cron (hourly)
                        |
                        v
                Python ingestion script
                        |
                        v
                  Supabase REST API
                        |
        +---------------+---------------+---------------+
        v               v               v               v
 air_quality_hourly  weather_hourly  district_air    air_quality
 (24h AQ chart)      (24h weather)   _weather_latest _pipeline_runs
                                     (dashboard)     (observability)
                        |
                        v
          khangdo.dev /air-quality dashboard
```

## Components

### Google Air Quality API

The primary air quality source, at roughly 500 m resolution. Only
`history:lookup` is called, for the licensing reason in
[attribution-and-terms.md](attribution-and-terms.md): historic values may be
stored, current and forecast values may not be held beyond an hour.

Called on even hours, once per district, asking for the last 2 hours. With a
2-hour cadence and a 2-hour window, every hour of the day is covered with no
gap, at 18 calls per run and ~6,480 calls per month.

The key is sent in the `X-Goog-Api-Key` header and scrubbed from any error text
the script logs or stores.

### Open-Meteo APIs

The weather source, and the air quality fallback. Called on every run, batched
six districts per request. CAMS global is a ~25-45 km grid on 3-hourly steps
updated about twice a day, which is why the 18 districts previously showed
nearly identical values.

Open-Meteo also supplies `so2`, `co` and `uv_index`, which are not requested
from Google.

### GitHub Actions

The workflow runs hourly at minute 7 and can be triggered manually with
`workflow_dispatch`. It previously ran every 15 minutes, which mostly re-fetched
an unchanged CAMS forecast.

`GOOGLE_MAPS_API_KEY` is optional. Without it the pipeline runs on Open-Meteo
alone and the dashboard keeps working at CAMS resolution.

### Python Ingestion

Each run:

1. Loads environment variables and opens a pipeline run row.
2. Fetches Open-Meteo air quality and weather for all 18 districts, batched.
3. On even hours with a key present, calls Google `history:lookup` once per
   district for the last 2 hours.
4. Writes every weather hour at or before the current hour to `weather_hourly`.
5. Writes Google hours to `air_quality_hourly` as `google_aq`; writes CAMS
   hours as `open_meteo_cams` only where Google did not supply the district.
6. Reads back the most recent stored hours and writes
   `district_air_weather_latest` from the newest one, preferring `google_aq`.
7. Updates the run row with per-source status and call counts.

Step 6 is a read-back rather than a reuse of step 5's rows on purpose. On an
hour when Google is not scheduled, nothing new is written, and building the
latest row from the current run's data alone would fall back to the coarse CAMS
payload and overwrite the Google values — flipping the dashboard's source and
its attribution every other hour.

### Supabase PostgreSQL

Four tables, described in [data-model.md](data-model.md). RLS select policies
allow the dashboard to read using the anon key. Writes are performed only with
the service role key in GitHub Actions.

Hourly history is retained for 30 days via an optional
`prune_hourly_history()` job. That window is a storage choice: Google's terms
permit storing historic values until the agreement is terminated.

### Dashboard

The live frontend is embedded in:

https://www.khangdo.dev/air-quality

It reads the latest district rows when Supabase is configured and falls back to
sample data if live data is unavailable. The 24-hour view reads
`air_quality_hourly` and `weather_hourly`.

The dashboard must render its attribution line from
`district_air_weather_latest.air_quality_source`, not hard-coded. See
[attribution-and-terms.md](attribution-and-terms.md) for the exact strings.

## Security Boundary

The Supabase service role key must stay in GitHub Actions secrets or a local
uncommitted `.env`. It must never be exposed in frontend code.

The Google API key cannot be IP-restricted, because GitHub-hosted runners have
no stable egress IP. It is instead restricted to the Air Quality API alone and
capped by a daily quota, so a leak is bounded in both scope and cost. See
[google-cloud-setup.md](google-cloud-setup.md).

Both keys are registered with the script's scrubber at startup and replaced
with `***` in anything written to stderr or to `air_quality_pipeline_runs`.

## Failure Handling

- Per-district, per-stage failures are captured in `error_message` with a
  `stage` label, and the run is marked `partial_success`.
- A Google failure is not an outage: the district falls back to Open-Meteo
  CAMS for that hour, and `air_quality_source` records what was actually used.
- Non-retryable Google responses (4xx other than 429) fail immediately rather
  than retrying, so a quota or key problem cannot multiply into a call storm.
- Open-Meteo batch failures fall back to per-district requests.
- If no district succeeds at all, the run is marked `failed`.
- The dashboard can continue rendering sample data if Supabase is unavailable.
