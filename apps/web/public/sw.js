const CACHE = 'learning-platform-shell-v1'

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((cache) => cache.addAll(['/app/'])))
})

self.addEventListener('fetch', (event) => {
  if (event.request.url.includes('/api/')) return
  event.respondWith(caches.match(event.request).then((cached) => cached || fetch(event.request)))
})
