const cacheName = 'lake-dashboard-shell-v8';
const shell = [
  '/', '/static/styles.css', '/static/camera.js', '/static/icons.js',
  '/mobile/dashboard.js?v=6', '/mobile/live-camera.js?v=6',
  '/mobile/mobile.css?v=8', '/mobile/mobile.js?v=5', '/manifest.webmanifest',
  '/mobile/icon-192.png', '/mobile/icon-512.png', '/mobile/icon-maskable.png',
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(cacheName).then(cache => cache.addAll(shell)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', event => {
  event.waitUntil((async () => {
    const keys = await caches.keys();
    await Promise.all(keys.filter(key => key.startsWith('lake-dashboard-shell-') && key !== cacheName)
      .map(key => caches.delete(key)));
    await self.clients.claim();
  })());
});

self.addEventListener('fetch', event => {
  const {request} = event;
  const url = new URL(request.url);
  const key = request.mode === 'navigate' ? url.pathname : url.pathname + url.search;
  if (request.method !== 'GET' || url.origin !== self.location.origin || !shell.includes(key)) return;

  // Live readings and the camera always use their existing network paths.
  event.respondWith((async () => {
    const cache = await caches.open(cacheName);
    let response;
    try {
      response = await fetch(request);
    } catch {
      return await cache.match(key) || Response.error();
    }
    if (response.ok && !response.redirected) {
      await cache.put(key, response.clone()).catch(() => {});
    }
    return response;
  })());
});
