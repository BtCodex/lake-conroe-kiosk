import {CameraPlayer} from './camera.js';
import {condition, icon, solarIcon} from './icons.js';

const $ = id => document.getElementById(id);
let config = {timezone: 'America/Chicago', temperature_unit: 'fahrenheit'};
let lastSnapshot = null;
let connected = true;
let alertIndex = 0;
let wakeLock;

if (new URLSearchParams(location.search).get('kiosk') === '1') document.documentElement.classList.add('kiosk');
const camera = new CameraPlayer({container: $('camera-player'), status: $('camera-status'), message: $('camera-message'), retry: $('camera-retry')}, config);
new MutationObserver(() => {
  const state = $('camera-status').dataset.state;
  $('camera-stage').classList.toggle('is-playing', state === 'live' || state === 'image');
  $('camera-stage').classList.toggle('is-embedded', state === 'embedded');
}).observe($('camera-status'), {attributes: true, attributeFilter: ['data-state']});

function number(value, digits = 0) {
  return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('en-US', {minimumFractionDigits: digits, maximumFractionDigits: digits}) : '--';
}
function temp(value) {
  return typeof value === 'number' ? number(config.temperature_unit === 'celsius' ? (value - 32) * 5 / 9 : value) : '--';
}
function time(value, options = {}) {
  if (!value || Number.isNaN(new Date(value).getTime())) return '--';
  return new Date(value).toLocaleTimeString('en-US', {timeZone: config.timezone, hour: 'numeric', minute: '2-digit', hour12: true, ...options});
}
function observation(value) {
  return value ? time(value) : 'Time unavailable';
}
function localDate(offset = 0) {
  const parts = new Intl.DateTimeFormat('en-US',{timeZone:config.timezone,year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date());
  const part = type => Number(parts.find(p=>p.type===type).value);
  return new Date(Date.UTC(part('year'),part('month')-1,part('day')+offset)).toISOString().slice(0,10);
}
function forecastDays(source) {
  return [0,1,2].map(offset=>{
    const date=localDate(offset);
    return source?.data?.daily?.find(day=>day.date===date) || {date};
  });
}
function windDirection(degrees) {
  if (typeof degrees !== 'number') return '';
  return ['N','NNE','NE','ENE','E','ESE','SE','SSE','S','SSW','SW','WSW','W','WNW','NW','NNW'][Math.round(degrees / 22.5) % 16];
}
function badge(id, source, override) {
  const element = $(id);
  const status = source?.status || 'loading';
  element.dataset.status = override ? 'stale' : status;
  element.textContent = override || {live: 'UPDATED', stale: 'STALE DATA', unavailable: 'UNAVAILABLE', loading: 'CONNECTING'}[status];
  element.title = source?.error || (source?.last_success_at ? `Last successful refresh: ${new Date(source.last_success_at).toLocaleString('en-US', {timeZone: config.timezone})}` : 'No successful source refresh yet');
}
function sourceLine(id, source, label) {
  $(id).textContent = `${label} · ${source?.last_success_at ? `refreshed ${time(source.last_success_at)}` : 'no successful refresh'}${source?.status === 'stale' ? ' · STALE' : ''}`;
  $(id).title = source?.error || $(id).textContent;
}
function clock() {
  const now = new Date();
  const parts = new Intl.DateTimeFormat('en-US', {timeZone: config.timezone, hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true}).formatToParts(now);
  const period = parts.find(p => p.type === 'dayPeriod')?.value || '';
  // The clock is the only display area that updates once a second.
  const stamp = parts.filter(p => p.type !== 'dayPeriod').map(p => p.value).join('').trim();
  $('clock').replaceChildren(document.createTextNode(`${stamp} `));
  const suffix = document.createElement('span'); suffix.textContent = period; $('clock').append(suffix);
  $('date').textContent = now.toLocaleDateString('en-US', {timeZone: config.timezone, weekday: 'long', month: 'long', day: 'numeric', year: 'numeric'});
  $('date').title = config.timezone;
}

function renderWeather(source, forecast) {
  const current = source?.data?.current || {};
  const daily = forecastDays(forecast);
  const oldModel = current.valid_at && Date.now() - new Date(current.valid_at).getTime() > 3600000;
  badge('weather-badge', source, oldModel && source?.status === 'live' ? 'STALE MODEL' : null);
  $('temperature').textContent = temp(current.temperature_f);
  $('temperature-unit').textContent = config.temperature_unit === 'celsius' ? '°C' : '°F';
  $('condition').textContent = condition(current.weather_code, current.is_day).label;
  $('weather-icon').innerHTML = icon(current.weather_code, current.is_day);
  $('feels-like').textContent = `${temp(current.apparent_temperature_f)}°`;
  $('today-high').textContent = `${temp(daily[0]?.temperature_max_f)}°`;
  $('today-low').textContent = `${temp(daily[0]?.temperature_min_f)}°`;
  $('humidity').innerHTML = `${number(current.relative_humidity_pct)}<small>%</small>`;
  $('wind').innerHTML = `${number(current.wind_speed_mph)}<small> MPH ${windDirection(current.wind_direction_deg)}</small>`;
  $('pressure').innerHTML = `${number(typeof current.pressure_hpa === 'number' ? current.pressure_hpa * .0295299830714 : null, 2)}<small> inHg</small>`;
  $('pressure').title = 'Modeled surface pressure; not sea-level pressure';
  $('uv').textContent = number(current.uv_index, 1);
  $('uv').title = current.uv_valid_at ? `Modeled UV valid at ${time(current.uv_valid_at)}` : 'UV index unavailable';
  sourceLine('weather-source', source, `Open-Meteo · modeled${current.valid_at ? ` ${time(current.valid_at)}` : ''}`);
  const hours = (source?.data?.hourly || []).filter(hour=>new Date(hour.time).getTime()>Date.now()).slice(0,6);
  $('hourly').replaceChildren();
  for (let i = 0; i < 6; i++) {
    const hour = hours[i] || {};
    const item = document.createElement('div'); item.className = 'hour';
    const label = hour.time ? time(hour.time, {minute: undefined}).replace(' ', '') : '--';
    const previous = i ? hours[i-1]?.temperature_f : current.temperature_f;
    const trend = typeof previous === 'number' && typeof hour.temperature_f === 'number' ? hour.temperature_f > previous + .5 ? '↗' : hour.temperature_f < previous - .5 ? '↘' : '→' : '';
    item.innerHTML = `<span class="hour-time"></span><span class="hour-icon">${icon(hour.weather_code,hour.is_day)}</span><span class="hour-temp">${temp(hour.temperature_f)}°<small class="hour-trend">${trend}</small></span><span class="rain">${number(hour.precipitation_probability_pct)}%</span>`;
    item.querySelector('.hour-time').textContent = label;
    item.title = `${condition(hour.weather_code,hour.is_day).label}; precipitation probability ${number(hour.precipitation_probability_pct)}%`;
    $('hourly').append(item);
  }
}

function renderForecast(source) {
  badge('forecast-badge',source);
  const days = forecastDays(source);
  $('forecast').replaceChildren();
  for (let i = 0; i < 3; i++) {
    const day = days[i] || {};
    const tile = document.createElement('div'); tile.className = 'forecast-day';
    tile.innerHTML = `<span class="day-name"></span><span class="day-icon">${icon(day.weather_code)}</span><span class="day-temperatures">${temp(day.temperature_max_f)}°<span>${temp(day.temperature_min_f)}°</span></span><span class="rain">${number(day.precipitation_probability_pct)}%</span>`;
    // Calendar dates are provider-local dates; parse noon to avoid crossing a day boundary.
    const name = day.date ? new Date(`${day.date}T12:00:00Z`).toLocaleDateString('en-US',{timeZone:'UTC',weekday:'short'}) : 'Day 3';
    tile.querySelector('.day-name').textContent = i === 0 ? 'Today' : i === 1 ? 'Tomorrow' : name;
    $('forecast').append(tile);
  }
  sourceLine('forecast-source',source,'Open-Meteo · modeled forecast');
  $('sunrise').textContent = time(days[0]?.sunrise);
  $('sunset').textContent = time(days[0]?.sunset);
  $('sunrise').title = source?.status === 'stale' ? 'Cached forecast: stale' : 'Today’s modeled sunrise';
  $('sunset').title = source?.status === 'stale' ? 'Cached forecast: stale' : 'Today’s modeled sunset';
}

function renderLake(source) {
  const data = source?.data || {};
  const readings = data.measurements || {};
  const elevation = readings.elevation_ft, water = readings.water_temperature_f, rain = readings.rainfall_24h_in, outflow = readings.outflow_cfs;
  const stale = reading => reading?.stale || (reading?.observed_at && Date.now() - new Date(reading.observed_at).getTime() > 1800000);
  const oldReading = Object.values(readings).some(stale);
  badge('lake-badge',source,oldReading && source?.status === 'live' ? 'STALE OBS.' : null);
  const setMeasurement = (id, record, unit, digits, convert) => {
    $(id).innerHTML = `${convert ? convert(record?.value) : number(record?.value,digits)}<small> ${unit}</small>`;
    $(id).title = record ? `${record.source || 'Published observation'} · ${record.observed_at || 'observation time unavailable'}${record.stale ? ' · cached previous reading' : ''}` : 'Measurement unavailable';
    $(id).style.color = stale(record) ? '#ddbe8b' : '';
  };
  setMeasurement('lake-elevation',elevation,'ft',2);
  setMeasurement('lake-temperature',water,config.temperature_unit === 'celsius' ? '°C' : '°F',1, value => typeof value === 'number' ? number(config.temperature_unit === 'celsius' ? (value-32)*5/9 : value,1) : '--');
  setMeasurement('lake-rain',rain,'in',2);
  setMeasurement('lake-outflow',outflow,'CFS',0);
  const timestamp = record => record ? `${observation(record.observed_at)}${stale(record) ? ' · stale' : ''}` : 'No observation';
  $('lake-datum').textContent = elevation ? `${elevation.datum || 'unknown datum'} · ${timestamp(elevation)}` : 'Datum unavailable';
  $('lake-water-time').textContent = timestamp(water);
  $('lake-rain-time').textContent = rain ? timestamp(rain) : 'Observed rainfall only';
  $('lake-outflow-time').textContent = timestamp(outflow);
  const pool = data.conservation_pool;
  $('lake-pool').textContent = `Pool reference: ${number(pool?.value_ft ?? config.lake?.conservation_pool_ft ?? 201,2)} ft ${pool?.datum || config.lake?.conservation_pool_datum || 'NGVD29'}`;
  const speed = readings.wind_speed_mph, direction = readings.wind_direction_deg;
  $('lake-wind').textContent = speed ? `Wind: ${number(speed.value)} MPH ${windDirection(direction?.value)}${stale(speed) ? ' · stale' : ''}` : 'Local wind: unavailable';
  $('lake-wind').title = speed ? `${speed.source} · ${observation(speed.observed_at)}` : 'SJRA local wind measurement unavailable';
  sourceLine('lake-source',source,'SJRA / USGS · observed readings');
  $('lake-source').title = (data.limitations || []).join('\n') || source?.error || 'No confirmed lake readings yet';
}

function renderAlerts(source) {
  const alerts = (source?.data?.alerts || []).filter(a => !a.expires || new Date(a.expires).getTime() > Date.now());
  const bar = $('alert-bar');
  if (alerts.length) {
    const alert = alerts[alertIndex % alerts.length];
    bar.dataset.severity = (alert.severity || 'minor').toLowerCase();
    $('alert-symbol').textContent = '!';
    $('alert-title').textContent = `${source.status === 'stale' || !connected ? 'CACHED · ' : ''}${alert.event}`;
    $('alert-detail').textContent = alert.headline || alert.description || 'National Weather Service alert';
    bar.title = `${alert.description || ''}\n${alert.instruction || ''}`;
  } else if (source?.status === 'live' && connected) {
    bar.dataset.severity = 'clear';
    $('alert-symbol').textContent = '✓';
    $('alert-title').textContent = 'No active weather alerts';
    $('alert-detail').textContent = 'National Weather Service · your local area';
    bar.title = 'The latest successful NWS response contains no unexpired alerts for this location.';
  } else {
    bar.dataset.severity = 'unknown';
    $('alert-symbol').textContent = '○';
    $('alert-title').textContent = source?.status === 'loading' ? 'Checking local weather alerts' : 'Weather alert status unavailable';
    $('alert-detail').textContent = 'NWS cannot be reached · alert status is unknown';
    bar.title = source?.error || 'A fresh NWS response is required before reporting no active alerts.';
  }
  $('alerts-time').textContent = source?.last_success_at ? `NWS ${time(source.last_success_at)}${source.status === 'stale' ? ' · stale' : ''}` : 'NWS · NOT CONNECTED';
}

function render(snapshot) {
  config = snapshot.config;
  camera.config = config.camera ? {...config.camera, timezone:config.timezone} : config;
  document.title = `${config.title} Live`;
  $('dashboard-title').textContent = config.title;
  $('location').textContent = config.location.label;
  $('footer-location').textContent = config.location.label.toUpperCase();
  for (const name of ['weather','hourly','forecast','lake']) $('panel-'+name).hidden = config.panels?.[name] === false;
  const enabled = ['weather','hourly','forecast','lake'].filter(n=>config.panels?.[n] !== false);
  $('panel-weather').parentElement.style.gridTemplateRows = enabled.map(n=>({weather:'1.75fr',hourly:'1fr',forecast:'1.08fr',lake:'1.48fr'}[n])).join(' ');
  $('panel-weather').parentElement.hidden = !enabled.length;
  document.querySelector('.main-grid').style.gridTemplateColumns = enabled.length ? '' : '1fr';
  const sources = snapshot.sources;
  renderWeather(sources.weather,sources.forecast);
  renderForecast(sources.forecast);
  renderLake(sources.lake);
  renderAlerts(sources.alerts);
  if (sources.camera?.data) {
    camera.update(sources.camera.data);
    $('camera-attribution').textContent = sources.camera.data.attribution || config.camera.attribution;
    const provider = sources.camera.data.provider;
    const description = provider === 'image' ? 'Periodically refreshed camera image · not continuous video' : provider === 'iframe' ? 'Configured embedded camera · playback cannot be verified' : provider === 'disabled' ? 'Camera is disabled in configuration' : sources.camera.data.status === 'discovered' ? 'Official embedded camera · source checked '+time(sources.camera.last_success_at) : 'Configured YouTube camera · source verification unavailable';
    $('camera-note').textContent = description;
    $('camera-note').title = (sources.camera.data.limitations || []).join('\n');
  } else if (sources.camera?.status === 'unavailable') {
    camera.setState('UNAVAILABLE','unavailable','Camera unavailable. Camera configuration could not be loaded.');
    $('camera-note').textContent = 'Camera source unavailable · retrying configuration in the background';
  }
  const successes = Object.entries(sources).filter(([name,s])=>name !== 'camera' && s.last_success_at).map(([,s])=>s.last_success_at).sort();
  $('refresh-time').textContent = successes.length ? `Last data refresh ${time(successes.at(-1))}` : 'No successful data refresh yet';
  $('connection-dot').dataset.status = Object.values(sources).some(s=>s.status !== 'live') ? 'degraded' : 'online';
  clock();
}

let refreshing = false;
async function refresh() {
  if (refreshing) return;
  refreshing = true;
  try {
    const response = await fetch('/api/dashboard',{cache:'no-store',signal:AbortSignal.timeout(8000)});
    if (!response.ok) throw new Error(`Server returned ${response.status}`);
    const snapshot = await response.json();
    connected = true;
    lastSnapshot = snapshot;
    render(snapshot);
  } catch (error) {
    connected = false;
    $('connection-dot').dataset.status = 'offline';
    $('refresh-time').textContent = 'Dashboard connection lost · retrying';
    if (lastSnapshot) {
      for (const source of Object.values(lastSnapshot.sources)) if (source.data) source.status = 'stale';
      badge('weather-badge',lastSnapshot.sources.weather);
      badge('forecast-badge',lastSnapshot.sources.forecast);
      badge('lake-badge',lastSnapshot.sources.lake);
    }
    renderAlerts(lastSnapshot?.sources.alerts);
    console.warn('Dashboard refresh failed:',error.message);
  } finally {
    refreshing = false;
  }
}

async function keepAwake() {
  if ('wakeLock' in navigator && document.visibilityState === 'visible') {
    try {wakeLock = await navigator.wakeLock.request('screen');} catch { /* OS kiosk setup provides the primary wake policy. */ }
  }
}
$('fullscreen').addEventListener('click',async()=>{
  try { if (!document.fullscreenElement) await document.documentElement.requestFullscreen(); else await document.exitFullscreen(); } catch { /* Chromium kiosk already fills the monitor. */ }
  keepAwake();
});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState === 'visible'){keepAwake();refresh();}});
window.addEventListener('online',()=>{refresh();if(camera.source)camera.start();});
window.addEventListener('pagehide',()=>{camera.destroy();wakeLock?.release();},{once:true});
$('sunrise-icon').innerHTML = solarIcon();
$('sunset-icon').innerHTML = solarIcon(true);
renderWeather(null,null);renderForecast(null);renderLake(null);clock();
refresh();keepAwake();
setInterval(clock,1000);
setInterval(refresh,15000);
setInterval(()=>{alertIndex++;renderAlerts(lastSnapshot?.sources.alerts);},12000);
