/**
 * Service Worker — Casa Leones POS (Fase 4 - Item 22)
 *
 * Estrategia: Network-first con cache fallback.
 * - Cachea assets estáticos (CSS, JS, imágenes)
 * - Para HTML/API: intenta red primero, cae a cache si offline
 * - Push notifications scaffolding
 */

const CACHE_NAME = 'casaleones-v3';
const STATIC_ASSETS = [
  '/static/css/styles.css',
  '/static/js/meseros.js',

  '/static/img/logoCasaLeones.svg',
  '/static/manifest.json',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css',
  'https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js',
];

// Install — pre-cache static assets
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      console.log('[SW] Pre-caching static assets');
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

// Activate — clean old caches
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys.filter(key => key !== CACHE_NAME).map(key => caches.delete(key))
      )
    )
  );
  self.clients.claim();
});

// Fetch — network-first for HTML/API, cache-first for static
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Skip non-GET requests
  if (event.request.method !== 'GET') return;

  // Static assets — cache-first
  if (url.pathname.startsWith('/static/') || STATIC_ASSETS.includes(url.href)) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        return cached || fetch(event.request).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // HTML/API — network-first
  event.respondWith(
    fetch(event.request)
      .then(response => {
        // Cache successful HTML responses
        if (response.ok && event.request.headers.get('accept')?.includes('text/html')) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request).then(cached => {
          if (cached) return cached;
          // Offline fallback page
          if (event.request.headers.get('accept')?.includes('text/html')) {
            return new Response(
              `<!DOCTYPE html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
              <title>Sin conexión — Casa Leones</title>
              <style>body{font-family:sans-serif;text-align:center;padding:60px 20px;background:#f8f9fa;}
              h1{color:#0d6efd;}p{color:#6c757d;}</style></head>
              <body><h1>Sin conexión</h1><p>Verifica tu conexión a internet e intenta de nuevo.</p>
              <button onclick="location.reload()" style="padding:10px 30px;font-size:16px;border:none;background:#0d6efd;color:white;border-radius:8px;cursor:pointer;">Reintentar</button>
              </body></html>`,
              { headers: { 'Content-Type': 'text/html' } }
            );
          }
          return new Response('Offline', { status: 503 });
        });
      })
  );
});

// Push notifications (scaffolding)
self.addEventListener('push', event => {
  const data = event.data?.json() || { title: 'Casa Leones', body: 'Nueva notificación' };
  event.waitUntil(
    self.registration.showNotification(data.title, {
      body: data.body,
      icon: '/static/img/icon-192.svg',
      badge: '/static/img/icon-192.svg',
      vibrate: [200, 100, 200],
      data: data.url || '/',
    })
  );
});

self.addEventListener('notificationclick', event => {
  event.notification.close();
  event.waitUntil(clients.openWindow(event.notification.data || '/'));
});
