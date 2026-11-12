# Google Cloud Setup

> ## Google is currently DISABLED — do not do this setup yet
>
> As of **November 12, 2026** the pipeline does not call the Google Air Quality
> API, and the steps below are **on hold**. Air quality comes from Open-Meteo
> CAMS; the dashboard works and nothing is pending.
>
> **Why.** Google Maps Platform Terms of Service **3.2.3(e) (No Use With
> Non-Google Maps)** says Customer "will not use the Google Maps Core Services
> with or near a non-Google Map in a Customer Application", and the Air Quality
> API is on the Core Services list. `/air-quality` renders districts on a
> custom Three.js map. Until that conflict is resolved — by changing the
> basemap, by keeping Google values off the map, or by a licensing
> conversation with Google — the API stays off. The full reading, the clause
> text and the options are in
> [attribution-and-terms.md](attribution-and-terms.md).
>
> **How it is enforced.** `GOOGLE_AQ_ENABLED` defaults to `false`. With it
> unset the script never calls Google *even if `GOOGLE_MAPS_API_KEY` is
> present*, and writes `google_status = 'disabled'` on the run row. There is a
> second guard inside `google_history_request()` that raises rather than send a
> request. Turning it on takes a deliberate `GOOGLE_AQ_ENABLED=true`.
>
> **Before turning it on**, the dashboard also needs the attribution (including
> the Google Maps logo) and the Terms of Use / Privacy Policy pages described
> in [attribution-and-terms.md](attribution-and-terms.md). The attribution is
> not built yet.

What follows is what to configure *if and when* that decision is made. Adding
`GOOGLE_MAPS_API_KEY` on its own changes nothing while the switch is off.

## 1. Project and billing

1. Open the [Google Cloud console](https://console.cloud.google.com/) and
   create a project, for example `khangdo-air-quality`.
2. Attach a billing account: **Billing > Link a billing account**.

Billing must be enabled even though the expected usage is inside the free
tier. The Air Quality API documentation states: "To use the Air Quality API,
you must enable billing on each of your projects and include an API key or
OAuth token with all API or SDK requests."

## 2. Enable the Air Quality API

**APIs & Services > Library**, search for *Air Quality API*, then **Enable**.

Enable nothing else. Every additional enabled API widens what a leaked key
could be used for.

## 3. Create a restricted API key

**APIs & Services > Credentials > Create credentials > API key**.

Then **Edit API key** and set:

| Setting | Value | Why |
| --- | --- | --- |
| Name | `air-quality-ingestion` | Identifies it in audit logs |
| Application restrictions | **None** | GitHub-hosted runners have no stable egress IP, so an IP allowlist is not workable. See the note below. |
| API restrictions | **Restrict key** > *Air Quality API* only | A leaked key can then call nothing else |

Copy the key once and store it directly in the GitHub repository secret
`GOOGLE_MAPS_API_KEY` (**Settings > Secrets and variables > Actions**). Do not
put it in `.env` in a tracked file, in the workflow YAML, or in any commit.

The key alone does nothing: the pipeline also needs `GOOGLE_AQ_ENABLED=true` in
the workflow environment. Keeping those two separate is deliberate — the key
can sit in secrets indefinitely without a single billable or non-compliant
call being made.

Because the key cannot be IP-restricted, the API restriction and the quota cap
in the next step are what bound the damage from a leak. The ingestion script
sends the key in the `X-Goog-Api-Key` header rather than a query string, so it
does not appear in request URLs or in error text, and it scrubs the value out
of anything written to logs or to `air_quality_pipeline_runs`.

If you would rather not rely on that, the alternative is a self-hosted runner
with a fixed IP, or a Workload Identity Federation service account instead of
an API key. Both are more setup than this project needs.

## 4. Cap the daily request quota

This is the control that keeps a bug or a retry loop from producing a bill.

**Google Maps Platform > Quotas**, select *Air Quality API*, find the requests-
per-day quota, click **Edit**, and set it to **300**.

Reasoning: planned usage is 18 districts x 12 runs/day = **216 calls/day**
(~6,480/month). A cap of 300/day allows roughly 84 spare calls per day for
manual `workflow_dispatch` runs and retries, and still caps the month at
300 x 31 = **9,300**, under the 10,000 free allowance. Raise it only if you add
districts.

Also set the per-minute quota to something small, e.g. **60**, if the console
offers one. A single run makes 18 calls, so 60/minute is ample and a runaway
loop is stopped quickly.

## 5. Budget alert

**Billing > Budgets & alerts > Create budget**:

- Scope: this project only.
- Amount: **$1**.
- Alert thresholds: 50%, 90%, 100% of actual spend.
- Email the billing admin.

Any spend at all means something exceeded the free tier, so a $1 budget is an
early warning rather than a real spending limit. A budget alert does *not* stop
requests; only the quota cap in step 4 does that.

## 6. Flip the switch

Only once the map question above is settled and the dashboard carries the
required attribution. In `.github/workflows/update-air-quality.yml`:

```yaml
env:
  GOOGLE_MAPS_API_KEY: ${{ secrets.GOOGLE_MAPS_API_KEY }}
  GOOGLE_AQ_ENABLED: "true"
```

To switch Google back off, set it to `"false"` or delete the line. The next run
reverts to CAMS on its own; no migration, no backfill, and the stored
`google_aq` rows stay valid (they are historic values, storable until the
Agreement is terminated).

## 7. Verify

Trigger the workflow manually (**Actions > Update Air Quality Data > Run
workflow**) and check the JSON summary in the step log:

```json
"google_status": "success",
"google_api_calls": 18,
"air_quality_source": "google_aq"
```

`google_api_calls` should be exactly 18 on a scheduled even hour. If it is
higher, something is retrying; investigate before leaving it on a schedule.

`"google_status": "disabled"` with `"google_api_calls": 0` means the switch is
off — that is the expected output today, not a failure.
`"google_status": "unconfigured"` means the switch is on but no key was found.

A `google_status` of `failed` is not an outage: the run falls back to
Open-Meteo CAMS and the dashboard keeps working, with
`district_air_weather_latest.air_quality_source` set to `open_meteo_cams` so
the frontend shows the matching attribution.

## Cost summary

Current spend is **$0.00** and current usage is **0 calls** — the switch is
off. The figures below are what the design would cost once it is on.

| Item | Value |
| --- | --- |
| Free allowance | 10,000 calls/month, shared across every Air Quality API method |
| Planned usage | 18 districts x 12 runs/day x 30 days = 6,480 calls/month |
| Headroom | ~3,520 calls/month |
| Price beyond the free tier | $5.00 per 1,000 calls (first paid band) |
| Daily quota cap | 300 |

The history endpoint is billed **per response page**, not per hour returned.
The script requests `hours: 4` with `pageSize: 4` and never follows
`nextPageToken`, so one district-run is always exactly one billable call. The
4-hour window therefore costs the same as a 1-hour window would, and exists so
that a cron run GitHub never fires leaves no gap in the history.
