const cacheName = 'lake-dashboard-shell-v1';
const shell = [
  '/', '/static/styles.css', '/static/app.js', '/static/camera.js', '/static/icons.js',
  '/mobile/mobile.css', '/mobile/mobile.js', '/manifest.webmanifest',
  '/mobile/icon-192.png', '/mobile/icon-512.png', '/mobile/icon-maskable.png',
];

self.addEventListener('install', event => {
  event.waitUntil(caches.open(cacheName).then(cache => cache.addAll(shell)));
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
  if (request.method !== 'GET' || url.origin !== self.location.origin || !shell.includes(url.pathname)) return;
  if (url.search && request.mode !== 'navigate') return;

  // Live readings and the camera always use their existing network paths.
  event.respondWith((async () => {
    const cache = await caches.open(cacheName);
    let response;
    try {
      response = await fetch(request);
    } catch {
      return await cache.match(url.pathname) || Response.error();
    }
    if (response.ok && !response.redirected) {
      await cache.put(url.pathname, response.clone()).catch(() => {});
    }
    return response;
  })());
});
