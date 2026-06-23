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
Open-Meteo Air Quality API
Open-Meteo Weather API
          |
          v
GitHub Actions cron
          |
          v
Python ingestion script
          |
          v
Supabase REST API
          |
          v
PostgreSQL latest district table + pipeline runs
          |
          v
khangdo.dev /air-quality dashboard
```

## Components

### Open-Meteo APIs

The pipeline calls separate Weather and Air Quality endpoints for each
configured Ho Chi Minh City district coordinate.

### GitHub Actions

The workflow runs every 15 minutes and can also be triggered manually with
`workflow_dispatch`.

### Python Ingestion

The script:

1. Loads environment variables.
2. Creates a pipeline run row.
3. Iterates through the configured district list.
4. Fetches weather and air quality data per district coordinate.
5. Normalizes fields into the dashboard schema.
6. Upserts all successful district rows into Supabase.
7. Updates the pipeline run with success, partial success, or failure metadata.

### Supabase PostgreSQL

Supabase stores:

- `district_air_weather_latest`: latest district-level dashboard snapshot.
- `air_quality_pipeline_runs`: ingestion execution metadata.

RLS select policies allow the dashboard to read using the anon key. Writes are
performed only with the service role key in GitHub Actions.

### Dashboard

The live frontend is embedded in:

https://www.khangdo.dev/air-quality

It reads the latest district rows when Supabase is configured and falls back to
sample data if live data is unavailable.

## Security Boundary

The Supabase service role key must stay in GitHub Actions secrets or a local
uncommitted `.env`. It must never be exposed in frontend code.

## Failure Handling

- Per-district failures are captured and reported in `error_message`.
- Partial runs still upsert successful districts and mark the run as
  `partial_success`.
- If no district succeeds, the run is marked `failed`.
- The dashboard can continue rendering sample data if Supabase is unavailable.
