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
  started_at timestamptz default now(),
  ended_at timestamptz
);

create index if not exists idx_district_air_weather_latest_aqi_desc
  on district_air_weather_latest (aqi desc);

create index if not exists idx_district_air_weather_latest_updated_at_desc
  on district_air_weather_latest (updated_at desc);

create index if not exists idx_air_quality_pipeline_runs_started_at_desc
  on air_quality_pipeline_runs (started_at desc);

-- RLS policies
-- Public dashboard clients use the anon role for SELECT only.
-- GitHub Actions ingestion uses the service_role key for full table access.
alter table district_air_weather_latest enable row level security;
alter table air_quality_pipeline_runs enable row level security;

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
