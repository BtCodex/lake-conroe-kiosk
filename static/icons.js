// Small local SVGs keep the display crisp without a font or icon CDN.
export function condition(code, isDay = true) {
  if (code === null || code === undefined) return {label: 'Unavailable', type: 'unknown'};
  const n = Number(code);
  if (n === 0) return {label: isDay === false ? 'Clear night' : 'Clear skies', type: isDay === false ? 'moon' : 'sun'};
  if (n <= 2) return {label: 'Partly cloudy', type: isDay === false ? 'night-cloud' : 'partly'};
  if (n === 3) return {label: 'Overcast', type: 'cloud'};
  if (n === 45 || n === 48) return {label: 'Fog', type: 'fog'};
  if (n >= 51 && n <= 57) return {label: 'Drizzle', type: 'rain'};
  if (n >= 61 && n <= 67) return {label: n >= 66 ? 'Freezing rain' : 'Rain', type: 'rain'};
  if (n >= 71 && n <= 77 || n === 85 || n === 86) return {label: 'Snow', type: 'snow'};
  if (n >= 80 && n <= 82) return {label: 'Rain showers', type: 'rain'};
  if (n >= 95 && n <= 99) return {label: 'Thunderstorms', type: 'storm'};
  return {label: 'Unavailable', type: 'unknown'};
}

export function icon(code, isDay = true) {
  const {type,label} = condition(code, isDay);
  const sun = '<g class="sun"><circle cx="20" cy="18" r="7"/><path d="M20 5v-2m0 30v-2M7 18H5m30 0h-2M11 9l-2-2m22 22-2-2M11 27l-2 2M31 7l-2 2"/></g>';
  const moon = '<path class="moon" d="M24 6a12 12 0 1 0 13 17A13 13 0 0 1 24 6z"/>';
  const cloud = '<path class="cloud" d="M12 30a7 7 0 0 1-1-14 10 10 0 0 1 19-2 8 8 0 1 1 4 16z"/>';
  let shape = '';
  if (type === 'sun') shape = sun;
  else if (type === 'moon') shape = moon;
  else if (type === 'partly') shape = `<g transform="translate(0 -3)">${sun}</g>${cloud}`;
  else if (type === 'night-cloud') shape = moon + cloud;
  else if (type === 'unknown') shape = '<g class="muted"><circle cx="24" cy="20" r="12"/><path d="M19 20h10"/></g>';
  else {
    shape = cloud;
    if (type === 'rain') shape += '<path class="rain-stroke" d="M16 34l-2 4m10-4-2 4m10-4-2 4"/>';
    if (type === 'snow') shape += '<path class="rain-stroke" d="M15 35v5m-2-3h4m10-2v5m-2-3h4"/>';
    if (type === 'storm') shape += '<path stroke="#efd37b" fill="#efd37b" d="M25 29l-6 7h5l-2 6 9-10h-6l2-3"/>';
    if (type === 'fog') shape += '<path class="rain-stroke" d="M9 35h28M14 39h18"/>';
  }
  return `<svg class="weather-icon" viewBox="0 0 48 44" role="img" aria-label="${label}">${shape}</svg>`;
}

export function solarIcon(setting = false) {
  const arrow = setting ? 'M12 2v7m-3-3 3 3 3-3' : 'M12 9V2m-3 3 3-3 3 3';
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M2 17h20M5 21h14M7 17a5 5 0 0 1 10 0${arrow}M3 10l2 2m14 0 2-2"/></svg>`;
}
