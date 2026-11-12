-- Full current schema. Safe to run on an empty Supabase project.
-- For an existing project, apply the files in supabase/migrations/ instead.

create table if not exists district_air_weather_latest (
  id bigint generated always as identity primary key,
  district text not null,
  city text default 'Ho Chi Minh City',
  latitude numeric,
  longitude numeric,

  aqi int,
  pm25 numeric,
  pm10 numeric,
  no2 numeric,
  o3 numeric,
  so2 numeric,
  co numeric,
  uv_index numeric,

  temperature numeric,
  humidity numeric,
  precipitation_probability numeric,
  wind_speed numeric,
  wind_gust numeric,
  pressure numeric,
  cloud_cover numeric,
  weather_condition text,

  status text,
  risk_level text,
  recommendation text,

  -- 'google_aq' or 'open_meteo_cams'. Drives which attribution the dashboard
  -- must display for the values currently shown.
  air_quality_source text,

  measured_at timestamptz,
  updated_at timestamptz default now(),

  unique (district)
);

create table if not exists air_quality_pipeline_runs (
  id bigint generated always as identity primary key,
  run_id text,
  status text,
  rows_processed int default 0,
  rows_failed int default 0,
  error_message text,

  air_quality_source text,
  google_status text,
  google_api_calls int default 0,
  open_meteo_status text,
  open_meteo_api_calls int default 0,
  air_quality_rows int default 0,
  weather_rows int default 0,

  started_at timestamptz default now(),
  ended_at timestamptz
);

-- Hourly air quality history.
--
-- Google Maps Platform Service Specific Terms, Table 2.2.1 (Air Quality API
-- Caching Permissions), last modified October 28, 2026:
--   * "Current conditions values / Hourly forecast values" may be cached for
--     "One hour, after which Customer must delete the cached Google Maps Content".
--   * "Historic values for a specific location and given time range" may be
--     cached "Until the Agreement is terminated".
-- Only values from history:lookup are written here. The pipeline never calls
-- currentConditions:lookup.
create table if not exists air_quality_hourly (
  district text not null,
  observed_at timestamptz not null,
  source text not null check (source in ('google_aq', 'open_meteo_cams')),

  us_aqi int,
  pm2_5 numeric,
  pm10 numeric,
  no2 numeric,
  o3 numeric,

  ingested_at timestamptz default now(),

  primary key (district, observed_at, source)
);

comment on table air_quality_hourly is
  'Hourly district air quality history. google_aq rows originate from the Google Air Quality API history:lookup endpoint only (storable under Service Specific Terms Table 2.2.1). Concentrations are stored in ug/m3 for every source; Google returns no2 and o3 in ppb and the pipeline converts them at 25 C / 1013.25 hPa.';

comment on column air_quality_hourly.no2 is 'Nitrogen dioxide in ug/m3. Converted from ppb for google_aq rows.';
comment on column air_quality_hourly.o3 is 'Ozone in ug/m3. Converted from ppb for google_aq rows.';

-- Hourly weather history from the Open-Meteo Forecast API.
create table if not exists weather_hourly (
  district text not null,
  observed_at timestamptz not null,

  temperature_2m numeric,
  apparent_temperature numeric,
  relative_humidity_2m numeric,
  precipitation numeric,
  rain numeric,
  precipitation_probability numeric,
  wind_speed_10m numeric,
  wind_gusts_10m numeric,
  weather_code int,

  ingested_at timestamptz default now(),

  primary key (district, observed_at)
);

comment on table weather_hourly is
  'Hourly district weather history from the Open-Meteo Forecast API. The pipeline stores only rows at or before the current hour, so this table never contains forecast values.';

create index if not exists idx_district_air_weather_latest_aqi_desc
  on district_air_weather_latest (aqi desc);

create index if not exists idx_district_air_weather_latest_updated_at_desc
  on district_air_weather_latest (updated_at desc);

create index if not exists idx_air_quality_pipeline_runs_started_at_desc
  on air_quality_pipeline_runs (started_at desc);

create index if not exists idx_air_quality_hourly_observed_at
  on air_quality_hourly (observed_at desc);

create index if not exists idx_weather_hourly_observed_at
  on weather_hourly (observed_at desc);

-- RLS policies
-- Public dashboard clients use the anon role for SELECT only.
-- GitHub Actions ingestion uses the service_role key for full table access.
alter table district_air_weather_latest enable row level security;
alter table air_quality_pipeline_runs enable row level security;
alter table air_quality_hourly enable row level security;
alter table weather_hourly enable row level security;

drop policy if exists "Allow public read district latest"
  on district_air_weather_latest;
create policy "Allow public read district latest"
  on district_air_weather_latest
  for select
  to anon
  using (true);

drop policy if exists "Allow public read pipeline runs"
  on air_quality_pipeline_runs;
create policy "Allow public read pipeline runs"
  on air_quality_pipeline_runs
  for select
  to anon
  using (true);

drop policy if exists "Allow public read air quality hourly"
  on air_quality_hourly;
create policy "Allow public read air quality hourly"
  on air_quality_hourly
  for select
  to anon
  using (true);

drop policy if exists "Allow public read weather hourly"
  on weather_hourly;
create policy "Allow public read weather hourly"
  on weather_hourly
  for select
  to anon
  using (true);

drop policy if exists "Allow service role full access district latest"
  on district_air_weather_latest;
create policy "Allow service role full access district latest"
  on district_air_weather_latest
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists "Allow service role full access pipeline runs"
  on air_quality_pipeline_runs;
create policy "Allow service role full access pipeline runs"
  on air_quality_pipeline_runs
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists "Allow service role full access air quality hourly"
  on air_quality_hourly;
create policy "Allow service role full access air quality hourly"
  on air_quality_hourly
  for all
  to service_role
  using (true)
  with check (true);

drop policy if exists "Allow service role full access weather hourly"
  on weather_hourly;
create policy "Allow service role full access weather hourly"
  on weather_hourly
  for all
  to service_role
  using (true)
  with check (true);
