-- Optional 30-day retention for the hourly history tables.
--
-- This retention window is a storage choice, not a licensing requirement.
-- Google Maps Platform Service Specific Terms Table 2.2.1 permits caching
-- "Historic values for a specific location and given time range" until the
-- Agreement is terminated, so air_quality_hourly rows sourced from
-- history:lookup could be kept indefinitely. The dashboard only renders the
-- last 24 hours, so 30 days is kept as a comfortable margin.
--
-- Terminating the Google Maps Platform agreement, or ceasing use of the Air
-- Quality API, is the point at which google_aq rows must be deleted:
--   delete from air_quality_hourly where source = 'google_aq';

create or replace function prune_hourly_history(retention_days int default 30)
returns table (table_name text, deleted_rows bigint)
language plpgsql
security definer
set search_path = public
as $$
declare
  cutoff timestamptz := now() - make_interval(days => retention_days);
  air_quality_deleted bigint;
  weather_deleted bigint;
begin
  delete from air_quality_hourly where observed_at < cutoff;
  get diagnostics air_quality_deleted = row_count;

  delete from weather_hourly where observed_at < cutoff;
  get diagnostics weather_deleted = row_count;

  return query
    values ('air_quality_hourly', air_quality_deleted),
           ('weather_hourly', weather_deleted);
end;
$$;

revoke all on function prune_hourly_history(int) from public, anon, authenticated;
grant execute on function prune_hourly_history(int) to service_role;

-- Run it manually:
--   select * from prune_hourly_history();
--
-- Or schedule it daily with pg_cron. Enable the extension first:
--   create extension if not exists pg_cron;
--   select cron.schedule(
--     'prune-hourly-history',
--     '20 18 * * *',            -- 01:20 Asia/Ho_Chi_Minh
--     $cron$ select prune_hourly_history(30); $cron$
--   );
--
-- Plain statements, if you would rather not install pg_cron:
--   delete from air_quality_hourly where observed_at < now() - interval '30 days';
--   delete from weather_hourly where observed_at < now() - interval '30 days';
