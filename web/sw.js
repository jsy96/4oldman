/* 静态资源缓存：只缓存带 ?v= 版本号的 CSS/JS/图片。
   网关对响应强制 no-store，浏览器缓存头无效，故用 SW 做缓存优先。
   发版时 index.html 里的 ?v=NN 变了 → URL 变化 → 自动取新文件。 */
const CACHE = 'care-static-v1';

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil(self.clients.claim()));

self.addEventListener('fetch', e => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (!url.searchParams.get('v')) return;  // 只缓存版本化静态资源
  e.respondWith((async () => {
    const cache = await caches.open(CACHE);
    const hit = await cache.match(req);
    if (hit) return hit;
    const res = await fetch(req);
    if (res && res.ok) cache.put(req, res.clone());
    return res;
  })());
});
