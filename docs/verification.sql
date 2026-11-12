-- verification.sql
--
-- Read-only queries to sanity-check a production ingestion run. Every
-- statement is a SELECT: nothing here writes, deletes, or alters anything,
-- so it is safe to paste into the Supabase SQL editor against production.
--
-- Baseline numbers below reflect the first production run: Google Air Quality
-- is disabled (GOOGLE_AQ_ENABLED="false"), so all air-quality rows come from
-- Open-Meteo CAMS, and the run observed 18 districts x 39 hourly rows = 702
-- rows per hourly table. The 39 is not fixed: past_days=1 returns from
-- midnight local yesterday, so a run holds 24 hours just after midnight and up
-- to 47 just before midnight. See docs/data-model.md and docs/api-sources.md.


-- 1. Rows per source
-- Healthy: one row per source present in air_quality_hourly. While Google is
-- off, expect only 'open_meteo_cams' (~702 on a first run). A 'google_aq' row
-- appears only once the API is enabled. An unexpected source value would
-- violate the table's check constraint, so anything else here is a red flag.
select source, count(*) as rows
  from air_quality_hourly
 group by source
 order by source;


-- 2. Rows per district
-- Healthy: exactly 18 districts, each with the SAME count (24-47 depending on
-- run time; 39 on the first run). Uneven counts mean a district dropped hours;
-- fewer or more than 18 districts means the coordinate list drifted.
select district, count(*) as rows
  from air_quality_hourly
 group by district
 order by district;

-- Same check for the weather feed. Healthy: 18 districts, counts matching the
-- air-quality table for the same run window.
select district, count(*) as rows
  from weather_hourly
 group by district
 order by district;


-- 3. Null counts per column
-- Healthy: 0 nulls in key/identity columns (district, observed_at, source,
-- ingested_at). Pollutant columns (aqi, pm25, pm10, no2, o3) should be 0 or
-- very low; a nonzero count means a source omitted that pollutant for some
-- hours, which is worth noting but not necessarily broken.
select
    count(*)                             as total_rows,
    count(*) - count(district)           as null_district,
    count(*) - count(observed_at)        as null_observed_at,
    count(*) - count(source)             as null_source,
    count(*) - count(aqi)                as null_aqi,
    count(*) - count(pm25)               as null_pm25,
    count(*) - count(pm10)               as null_pm10,
    count(*) - count(no2)                as null_no2,
    count(*) - count(o3)                 as null_o3,
    count(*) - count(ingested_at)        as null_ingested_at
  from air_quality_hourly;

-- Weather feed null counts. Healthy: 0 nulls in district/observed_at/
-- ingested_at. precipitation_probability is a forecast quantity and may be
-- null for some past hours; that is expected, not a fault.
select
    count(*)                                      as total_rows,
    count(*) - count(district)                    as null_district,
    count(*) - count(observed_at)                 as null_observed_at,
    count(*) - count(temperature)                 as null_temperature,
    count(*) - count(apparent_temperature)        as null_apparent_temperature,
    count(*) - count(humidity)                    as null_humidity,
    count(*) - count(precipitation)               as null_precipitation,
    count(*) - count(rain)                        as null_rain,
    count(*) - count(precipitation_probability)   as null_precip_probability,
    count(*) - count(wind_speed)                  as null_wind_speed,
    count(*) - count(wind_gust)                   as null_wind_gust,
    count(*) - count(weather_code)                as null_weather_code,
    count(*) - count(ingested_at)                 as null_ingested_at
  from weather_hourly;


-- 4. Latest pipeline run, with the new observability columns
-- Healthy: status 'success'; rows_processed = 18; rows_failed = 0;
-- open_meteo_status 'success'. While Google is off: air_quality_source
-- 'open_meteo_cams', google_status 'disabled', google_api_calls 0,
-- air_quality_rows and weather_rows ~702 each. A nonzero google_api_calls
-- while disabled would mean the switch is not being honored.
select
    run_id,
    status,
    rows_processed,
    rows_failed,
    air_quality_source,
    google_status,
    google_api_calls,
    open_meteo_status,
    open_meteo_api_calls,
    air_quality_rows,
    weather_rows,
    started_at,
    ended_at
  from air_quality_pipeline_runs
 order by started_at desc
 limit 1;


-- 5. Distinct AQI values at the latest hour
-- Healthy (CAMS only): 18 districts but only ~2 distinct AQI values, because
-- all districts fall into one or two cells of the ~25 km CAMS grid. This is a
-- model-cell effect, NOT real district-to-district variation. Once Google
-- (~500 m) is enabled, expect distinct_aqi to climb well above 2.
select
    count(*)              as rows_at_latest_hour,
    count(distinct aqi)   as distinct_aqi_values
  from air_quality_hourly
 where observed_at = (select max(observed_at) from air_quality_hourly);

-- The actual values, one row per district, to eyeball the clustering.
select district, source, aqi
  from air_quality_hourly
 where observed_at = (select max(observed_at) from air_quality_hourly)
 order by aqi, district;


-- 6. Column list of the two hourly tables
-- Healthy: air_quality_hourly has 9 columns and weather_hourly has 11,
-- matching docs/data-model.md. Use this to confirm a migration landed the
-- expected shape (e.g. the hourly column names mirror
-- district_air_weather_latest).
select
    table_name,
    ordinal_position,
    column_name,
    data_type,
    is_nullable
  from information_schema.columns
 where table_schema = 'public'
   and table_name in ('air_quality_hourly', 'weather_hourly')
 order by table_name, ordinal_position;
