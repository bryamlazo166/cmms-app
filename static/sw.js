// CMMS PWA Service Worker
// Estrategia: network-first para HTML/API, cache-first para assets estaticos.
// El nombre del cache cambia con cada deploy para forzar refresh limpio.
const CACHE_NAME = 'cmms-v1';
const ASSET_PATHS = [
  '/static/css/style.css',
  '/static/css/sidebar.css',
  '/static/js/sidebar.js',
  '/static/favicon.svg',
  '/static/icon-192.png',
  '/static/icon-512.png',
  '/static/manifest.webmanifest',
];

self.addEventListener('install', (event) => {
  // Pre-cachea el shell minimo (no falla si algun asset no responde 200)
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) =>
      Promise.allSettled(ASSET_PATHS.map((p) => cache.add(p)))
    )
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  // Limpia caches viejos
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  // Solo GET; otros pasan al network sin tocar
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Nunca cachear endpoints de auth ni acciones del bot
  if (url.pathname.startsWith('/login') ||
      url.pathname.startsWith('/logout') ||
      url.pathname.startsWith('/telegram-webhook')) {
    return;
  }

  // API: network-first, fallback a cache si offline
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          // Cachea respuestas OK para fallback futuro
          if (res.ok && res.type === 'basic') {
            const copy = res.clone();
            caches.open(CACHE_NAME).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Assets estaticos: cache-first
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(req).then((hit) => hit || fetch(req).then((res) => {
        if (res.ok) {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy));
        }
        return res;
      }))
    );
    return;
  }

  // Paginas HTML: network-first, fallback a cache
  event.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok && res.type === 'basic') {
          const copy = res.clone();
          caches.open(CACHE_NAME).then((c) => c.put(req, copy));
        }
        return res;
      })
      .catch(() => caches.match(req))
  );
});
