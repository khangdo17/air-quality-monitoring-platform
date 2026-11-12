# Data Model

Four tables:

| Table | Grain | Purpose |
| --- | --- | --- |
| `district_air_weather_latest` | One row per district | Dashboard snapshot |
| `air_quality_hourly` | District x hour x source | 24-hour air quality chart |
| `weather_hourly` | District x hour | 24-hour weather chart |
| `air_quality_pipeline_runs` | One row per run | Ingestion observability |

## `air_quality_hourly`

Hourly air quality history. Primary key `(district, observed_at, source)`, so
the same hour can hold both a Google row and a CAMS row without either
overwriting the other.

| Column | Type | Description |
| --- | --- | --- |
| `district` | text | District display name |
| `observed_at` | timestamptz | Hour the values describe |
| `source` | text | `google_aq` or `open_meteo_cams` (check constraint) |
| `us_aqi` | int | US EPA AQI |
| `pm2_5` | numeric | Fine particulate matter, µg/m³ |
| `pm10` | numeric | Coarse particulate matter, µg/m³ |
| `no2` | numeric | Nitrogen dioxide, µg/m³ |
| `o3` | numeric | Ozone, µg/m³ |
| `ingested_at` | timestamptz | Pipeline write timestamp |

Indexed on `observed_at desc`.

### Units are normalised to µg/m³

Google returns **NO2 and O3 in ppb**; Open-Meteo CAMS returns them in µg/m³.
Storing both as-is would make the `no2` and `o3` columns mean different things
depending on `source`, and a chart crossing a source change would show a step
that is not real.

The pipeline reads `concentration.units` from the Google response and converts
`PARTS_PER_BILLION` values to µg/m³ before writing:

```text
µg/m³ = ppb × molecular_weight / 24.45
```

24.45 L/mol is the molar volume at 25 °C and 1013.25 hPa. Factors used: NO2
46.0055/24.45 ≈ 1.882, O3 48.00/24.45 ≈ 1.963. Values that arrive in an
unrecognised unit are dropped rather than guessed at.

This is an approximation: the true factor depends on the actual temperature and
pressure of the air being measured, not on standard conditions. For a dashboard
chart the error is small and constant, but the stored NO2 and O3 values are not
a bit-exact reproduction of what Google returned.

PM2.5 and PM10 arrive in µg/m³ from both sources and are stored unchanged.

### Which source wins

`district_air_weather_latest` is written from the newest stored hour, with
`google_aq` preferred over `open_meteo_cams` at the same hour. CAMS rows are
written only as a fallback: when no Google key is configured, or when a
Google call fails. On an hour when Google is simply not scheduled, nothing is
written to this table and the latest row is refreshed from the hours already
stored.

## `weather_hourly`

Hourly weather history from Open-Meteo. Primary key `(district, observed_at)`.

| Column | Type | Description |
| --- | --- | --- |
| `district` | text | District display name |
| `observed_at` | timestamptz | Hour the values describe |
| `temperature_2m` | numeric | Air temperature at 2 m, °C |
| `apparent_temperature` | numeric | Feels-like temperature, °C |
| `relative_humidity_2m` | numeric | Relative humidity, % |
| `precipitation` | numeric | Total precipitation, mm |
| `rain` | numeric | Rain only, mm |
| `precipitation_probability` | numeric | Probability of precipitation, % |
| `wind_speed_10m` | numeric | Wind speed at 10 m |
| `wind_gusts_10m` | numeric | Wind gust speed at 10 m |
| `weather_code` | int | WMO weather code |
| `ingested_at` | timestamptz | Pipeline write timestamp |

Indexed on `observed_at desc`.

Open-Meteo returns forecast hours alongside past ones. **Only hours at or
before the current hour are stored**, so this table never contains forecast
values and the 24-hour chart cannot silently plot a forecast as history.
`precipitation_probability` is itself a forecast quantity even for past hours;
it is kept because the dashboard already displays it.

## `district_air_weather_latest`

One row per district: the latest dashboard-ready estimate. Conflict key
`district`. Unchanged from before except for one new column.

| Column | Type | Description |
| --- | --- | --- |
| `district` | text | District display name |
| `city` | text | City label, defaults to Ho Chi Minh City |
| `latitude` | numeric | Coordinate used for API request |
| `longitude` | numeric | Coordinate used for API request |
| `aqi` | int | US AQI |
| `pm25` | numeric | Fine particulate matter |
| `pm10` | numeric | Coarse particulate matter |
| `no2` | numeric | Nitrogen dioxide, µg/m³ |
| `o3` | numeric | Ozone, µg/m³ |
| `so2` | numeric | Sulphur dioxide (Open-Meteo CAMS only) |
| `co` | numeric | Carbon monoxide (Open-Meteo CAMS only) |
| `uv_index` | numeric | UV index (Open-Meteo CAMS only) |
| `temperature` | numeric | Current temperature |
| `humidity` | numeric | Relative humidity |
| `precipitation_probability` | numeric | Forecast precipitation probability |
| `wind_speed` | numeric | Wind speed |
| `wind_gust` | numeric | Wind gust speed |
| `pressure` | numeric | Mean sea-level pressure |
| `cloud_cover` | numeric | Cloud cover percentage |
| `weather_condition` | text | Normalized weather condition label |
| `status` | text | AQI status label |
| `risk_level` | text | Internal risk bucket |
| `recommendation` | text | Dashboard recommendation copy |
| **`air_quality_source`** | text | **New.** `google_aq` or `open_meteo_cams` |
| `measured_at` | timestamptz | Source observation timestamp |
| `updated_at` | timestamptz | Pipeline write timestamp |

`air_quality_source` tells the frontend which attribution line to render. It is
not cosmetic: showing the Google attribution over CAMS values, or omitting it
over Google values, is wrong in opposite directions. See
[attribution-and-terms.md](attribution-and-terms.md).

`so2`, `co` and `uv_index` always come from Open-Meteo CAMS, even when AQI and
particulates come from Google. They are not requested from Google and are not
stored hourly.

## `air_quality_pipeline_runs`

One row per ingestion execution.

| Column | Type | Description |
| --- | --- | --- |
| `run_id` | text | UUID generated by the Python script |
| `status` | text | `running`, `success`, `partial_success`, or `failed` |
| `rows_processed` | int | District rows upserted into the latest table |
| `rows_failed` | int | Number of failed stages |
| `error_message` | text | Failure detail, or JSON list of per-stage failures |
| `air_quality_source` | text | `google_aq`, `open_meteo_cams`, `mixed`, or null |
| `google_status` | text | `success`, `partial_success`, `failed`, `skipped`, `disabled` |
| `google_api_calls` | int | Billable Air Quality API calls this run |
| `open_meteo_status` | text | `success`, `partial_success`, or `failed` |
| `open_meteo_api_calls` | int | Open-Meteo HTTP attempts this run |
| `air_quality_rows` | int | Rows written to `air_quality_hourly` |
| `weather_rows` | int | Rows written to `weather_hourly` |
| `started_at` | timestamptz | Run start time |
| `ended_at` | timestamptz | Run end time |

`google_status` distinguishes the states that look alike from the outside:

- `disabled` — no `GOOGLE_MAPS_API_KEY`, or mode `never`. CAMS is the source.
- `skipped` — key present, but this is an odd hour. Nothing was called.
- `failed` — calls were made and all failed. CAMS filled in.
- `partial_success` — some districts succeeded; the rest fell back to CAMS.

`google_api_calls` is the number to watch against the 10,000/month free tier.
Expect exactly 18 on a scheduled hour. Anything higher means retries.

Running total for the month:

```sql
select sum(google_api_calls) as calls_this_month
  from air_quality_pipeline_runs
 where started_at >= date_trunc('month', now());
```

## Error payload

`error_message` holds a JSON array when individual stages fail:

```json
[{ "district": "Quận 1", "stage": "google_air_quality", "error": "..." }]
```

`stage` is one of `open_meteo`, `google_air_quality`, `weather_hourly`,
`cams_hourly`, `latest`, or `pipeline`. API keys are scrubbed from these
strings before they are written.

## RLS Design

All four tables enable row-level security with public `select` policies for the
`anon` role and full access for `service_role`. The dashboard should only use
the anon key. Ingestion writes use the service role key from GitHub Actions
secrets.

## Retention

`prune_hourly_history(retention_days int default 30)` deletes rows older than
the cutoff from both hourly tables and returns the counts. It is
`security definer` and executable only by `service_role`. See
`supabase/migrations/20261111120100_hourly_history_retention.sql` for the
pg_cron scheduling snippet.
