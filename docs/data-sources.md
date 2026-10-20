# Data sources and freshness

The production dashboard never substitutes sample measurements, stock camera images, forecast rainfall, or a successful network connection for live observations. The default location is approximately **30.402° N, 95.608° W**, near Walden on Lake Conroe. Change coordinates and the location label together in `config/settings.local.json` when deploying elsewhere.

## Providers and default refresh intervals

| Source | Backend integration | Default interval | What it supplies |
| --- | --- | --- | --- |
| Open-Meteo current/hourly | `https://api.open-meteo.com/v1/forecast` | 300 seconds | Modeled current conditions and the next six forecast hours |
| Open-Meteo daily | Same forecast API, separate request/cache | 1,800 seconds | Three daily forecasts, sunrise, and sunset |
| SJRA / USGS | Published SJRA reading pages, structured NWIS fallback | 180 seconds | Confirmed lake measurements, independently when available |
| National Weather Service | `https://api.weather.gov/alerts/active?point=latitude,longitude` | 120 seconds | Active alerts affecting the configured point |
| Official camera discovery | The configured LakeConroe.com source page | 1,800 seconds | Discovery of the currently published supported YouTube embed |

Intervals are independently configurable under `polling`. Camera playback retries and image-fallback refreshes have their own `camera.retry_seconds` and `camera.image_refresh_seconds` settings. Browser requests read the local cache; adding a display does not multiply upstream requests.

The backend uses normal TLS verification, a descriptive User-Agent, bounded connection/request timeouts, and at most one short retry for eligible transient failures. Failed source refreshes use independent capped exponential backoff. HTTP errors and malformed data do not become successful empty readings. The public services have their own usage terms and availability; Open-Meteo's public endpoint is intended for eligible noncommercial use. Check provider terms before commercial deployment.

## Weather is modeled, not a Walden observation station

The implemented weather provider is **Open-Meteo**. `weather.provider` currently accepts `open-meteo`; the NWS integration supplies alerts, not station weather or the forecast tiles. The provider requests Fahrenheit, MPH, Unix timestamps, and the configured timezone. The display explicitly labels this weather as modeled.

Current fields are air temperature, apparent temperature, relative humidity, 10-meter wind speed/direction, weather code, day/night status, and **surface** pressure. Surface pressure is not reduced to sea level; the display converts hPa to inHg and preserves that distinction in its tooltip. UV comes from the model's latest hourly valid time at or before the current instant and has its own `uv_valid_at` timestamp. Today's high/low, precipitation probabilities, and sunrise/sunset come from the independent daily forecast.

Hourly and daily rain percentages are **forecast precipitation probabilities**, not observed rainfall amounts. Missing values stay unavailable. The hourly adapter validates array lengths and time ordering; malformed responses preserve the previous successful cached response rather than fabricating replacement values.

## SJRA published readings

`app/providers/sjra.py` requests these pages through the backend, with at most three SJRA requests in flight:

| Page beneath `https://levels.sjra.info/` | Measurement | Accepted output unit |
| --- | --- | --- |
| `lake-level-index.php` | Lake surface elevation | feet |
| `lake-watertemp-index.php` | Water temperature | °F |
| `lake-release-index.php` | Published lake release/outflow | CFS |
| `lake-airtemp-index.php` | Local air temperature | °F |
| `lake-wind-index.php` | Wind direction | degrees; explicit compass points are normalized |
| `lake-windspeed-index.php` | Wind speed | MPH |

These are separate pages; one failure does not discard successful readings from the others. Each returned measurement retains its source URL and its own observation timestamp when explicitly published.

The parser requires an unambiguous metric label immediately followed by a reading and the expected unit, optionally separated by a short current-reading qualifier. It ignores scripts/styles and rejects access-denied pages, ambiguous values, unsupported units, and missing numeric readings. It does not mistake a conservation-pool reference or a historical chart value for the current measured level. If a page exposes only an embedded chart/image without a readable labeled measurement, the reading remains unavailable. This deliberately favors missing data over an incorrect reading.

**Verification limitation:** direct probes of the official SJRA pages and `https://www.sjraconditions.com/` were blocked by the cloud network proxy with `403 Forbidden` during development. The parser is covered by clearly identified synthetic unit-test fixtures; its compatibility with the current live HTML is unverified. No documentation claim that these readings were successfully fetched should be inferred from passing fixture tests. Use the health endpoint and logs on a network that permits these domains to verify the live page formats.

## USGS fallback: station 08067600

`app/providers/usgs.py` requests the public NWIS instantaneous-values JSON endpoint:

```text
https://waterservices.usgs.gov/nwis/iv/?format=json&sites=08067600&siteStatus=all&parameterCd=62614,62615,00010,00060
```

It is used when SJRA elevation or water temperature is unavailable. A response need not contain every requested parameter. An absent series remains unavailable rather than being inferred from another measurement.

| Parameter | Accepted meaning | Handling |
| --- | --- | --- |
| `62614` | Lake/reservoir water surface elevation above NGVD 1929 | Preserve `NGVD29`; normalize explicitly declared meters to feet if applicable |
| `62615` | Lake/reservoir water surface elevation above NAVD 1988 | Preserve `NAVD88`; no conversion between vertical datums |
| `00010` | Water temperature | Convert explicitly declared °C to °F; accept explicitly declared °F |
| `00060` | Discharge | **Not treated as dam outflow by default**; optional `lake.usgs_discharge_is_outflow: true` requires the deployer to confirm that the configured station's discharge measures the desired outflow |

Gage height (`00065`) is not substituted for lake elevation. The parser selects the latest valid finite reading, rejects no-data sentinels and future or offset-free timestamps, and retains NWIS observation timestamps and qualifiers such as provisional (`P`). Units must match the explicitly supported unit names. Flow conversion, when the opt-in applies, uses 1 cubic foot = 0.028316846592 cubic meter.

**Verification limitation:** the NWIS request was also blocked by the cloud proxy during development. The response adapter and unit conversions passed fixture tests, but the current station's available live parameters were not verified.

## Elevation datum and conservation pool

The configured approximately **201-foot NGVD29 conservation pool is a reference**, not a sensor measurement. SJRA elevation records are labeled `NGVD29` or `NAVD88` only when the page explicitly identifies a unique datum; otherwise they are labeled `unknown`. USGS records retain the datum implied by their exact parameter code.

The dashboard displays the measured elevation and its datum separately from the pool reference. It does not calculate a difference or silently compare values across different or unknown datums. Do not change a datum label to make two numbers appear comparable. A valid conversion would require authoritative local vertical-datum information and is not implemented.

## OneRain and 24-hour observed rainfall

The official monitoring dashboard provided in the brief is:

```text
https://sanjacinto.onerain.com/dashboard/?dashboard=c03aab24-7518-419b-9dfa-b151879a06c8&refresh=60&scroll=4772
```

The cloud proxy blocked access during investigation. **No publicly accessible structured feed was confirmed.** The application does not invent an API URL, access a protected feed, or scrape an unverified cumulative rainfall number from that dashboard.

The 24-hour lake rainfall field currently remains `Unavailable`. It is not filled from Open-Meteo forecast precipitation or an arbitrary difference between cumulative sensor readings. A future measured-rainfall integration must establish the sensor, unit, interval semantics, timestamps, reset behavior, and complete compatible observations spanning the required rolling 24 hours before calculating a total. Generic USGS `00045` samples are not assumed to satisfy those requirements.

## Alert behavior

NWS responses must be a valid GeoJSON `FeatureCollection`. Alerts are deduplicated and ordered by severity. The UI uses severity colors, rotates between multiple active alerts, and excludes expired entries from presentation. A successful, fresh response with no remaining unexpired alerts is required for a no-active-alerts status. A network failure is an unavailable or stale alert service, never an all-clear. Cached alerts are labeled as cached; consult official warning channels for urgent decisions.

## Camera behavior

See [camera.md](camera.md) for official embed discovery, playback-state verification, reconnection, and configurable alternatives. Backend source-page discovery does not verify video playback. The red LIVE indicator depends on the supported embedded player's actual playback state. A refreshed image is explicitly labeled as an image and is never presented as live video.

## Three different timestamps

1. **Last successful refresh** (`last_success_at`) is when this backend successfully retrieved and normalized a source response. It is not the observation time or the model's validity time. `last_attempt_at` may be newer after a failed attempt.
2. **Observation time** (`observed_at`) is the published time of an SJRA or USGS measurement. If SJRA publishes no usable timestamp, this remains null. Offset-free SJRA times are interpreted in the configured timezone; ambiguous or nonexistent daylight-saving hours remain unknown rather than guessed. USGS timestamps must have an explicit offset.
3. **Model valid time** (`valid_at`, forecast `time`, and `uv_valid_at`) identifies when a modeled weather value applies. Open-Meteo's legacy normalized `observed_at` field is retained for schema compatibility, but `measurement_type: modeled` and `valid_at` explicitly identify it as model data, not a station observation. Daily `date` is a provider-local calendar date; sunrise/sunset are timezone-aware instants.

All normalized instants include UTC/offset information. The display converts times with `America/Chicago` by default, including daylight-saving transitions; its clock uses the display device's clock. Keep the operating system clock synchronized.

## Cache, partial failures, and health

Successful normalized JSON responses are saved atomically in the configured local cache directory and loaded after a server restart. No database is required. A failed refresh preserves the last successful response, its original success timestamp, and an explicit error. If there is no previous successful response, the UI shows unavailable/loading rather than fixture data.

When only part of a new lake refresh succeeds, previous individual readings can be retained with `stale: true`, preserving their observation timestamps and sources. The UI also marks lake observations older than 30 minutes as stale. Read the timestamp beside a measurement: a recent successful source request cannot make an old published observation new.

`GET /api/health` reports each source's loading/live/stale/unavailable state, last attempt/success, refresh interval, error, and age of the last successful fetch. A source is stale on a failed refresh or when its last success exceeds twice its configured interval. `live` in this JSON means the **source cache refreshed successfully**, not verified camera playback or proof that every sensor observation is recent. `GET /api/dashboard` and `GET /api/{weather,forecast,lake,alerts,camera}` provide normalized data and per-measurement timestamps for diagnosis. The local HTTP service can run correctly while health reports degraded external sources.

No API keys are required by the default providers. Required outbound hosts are `api.open-meteo.com`, `api.weather.gov`, `levels.sjra.info`, `waterservices.usgs.gov`, and `lakeconroe.com`, plus the provider's supported YouTube player/media domains for actual camera playback. `www.sjraconditions.com` and `sanjacinto.onerain.com` are investigation/reference hosts rather than confirmed production JSON integrations. Cloud draft network changes do not prove those hosts are reachable until applied and retried.
