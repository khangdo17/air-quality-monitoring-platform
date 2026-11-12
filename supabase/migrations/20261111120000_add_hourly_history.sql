-- Hourly air quality and weather history for the 24-hour dashboard view.
--
-- Air quality rows may come from two sources:
--   'google_aq'        Google Air Quality API, history:lookup endpoint ONLY.
--   'open_meteo_cams'  Open-Meteo air quality (CAMS global) hourly values.
--
-- Google Maps Platform Service Specific Terms, Table 2.2.1
-- (Air Quality API Caching Permissions), last modified October 28, 2026:
--   * "Current conditions values / Hourly forecast values" may be cached for
--     "One hour, after which Customer must delete the cached Google Maps Content".
--   * "Historic values for a specific location and given time range" may be
--     cached "Until the Agreement is terminated".
-- Only values fetched from history:lookup are written here. The pipeline never
-- calls currentConditions:lookup, so nothing in this table is subject to the
-- one-hour deletion rule.

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

create index if not exists idx_air_quality_hourly_observed_at
  on air_quality_hourly (observed_at desc);

create index if not exists idx_weather_hourly_observed_at
  on weather_hourly (observed_at desc);

-- Records which source produced the air quality values currently on display, so
-- the dashboard can show the Google attribution only when it is showing Google
-- data.
alter table district_air_weather_latest
  add column if not exists air_quality_source text;

-- Per-source observability for the ingestion run.
alter table air_quality_pipeline_runs
  add column if not exists air_quality_source text,
  add column if not exists google_status text,
  add column if not exists google_api_calls int default 0,
  add column if not exists open_meteo_status text,
  add column if not exists open_meteo_api_calls int default 0,
  add column if not exists air_quality_rows int default 0,
  add column if not exists weather_rows int default 0;

-- RLS: same pattern as district_air_weather_latest.
-- Public dashboard clients read with the anon role. Ingestion writes with the
-- service role key.
alter table air_quality_hourly enable row level security;
alter table weather_hourly enable row level security;

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
