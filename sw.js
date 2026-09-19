// Replaced with the exported JavaScript bundle hash by scripts/inject-pwa.js.
const CACHE_NAME = "rehyn-shell-ea4a218972e8ecf6d92cf2688270b332";
const SHELL_FILES = [
  "/",
  "/manifest.json",
  "/icons/icon-192.png",
  "/icons/icon-512.png",
  "/icons/apple-touch-icon.png",
];
const MODEL_FILES = [
  "/vendor/mediapipe/vision_bundle.mjs",
  "/vendor/mediapipe/wasm/vision_wasm_internal.js",
  "/vendor/mediapipe/wasm/vision_wasm_internal.wasm",
  "/vendor/mediapipe/wasm/vision_wasm_nosimd_internal.js",
  "/vendor/mediapipe/wasm/vision_wasm_nosimd_internal.wasm",
  "/vendor/mediapipe/models/pose_landmarker_lite.task",
  "/vendor/mediapipe/models/hand_landmarker.task",
];
const PREPARED_VOICE_MANIFEST = "/audio/prepared/manifest.json";

async function cachePreparedVoice(cache) {
  const response = await fetch(new Request(PREPARED_VOICE_MANIFEST, { cache: "reload" }));
  if (!response.ok) return;
  await cache.put(PREPARED_VOICE_MANIFEST, response.clone());
  const manifest = await response.json();
  const files = (manifest.assets || []).map((asset) => asset.url).filter(Boolean);
  await Promise.allSettled(files.map((file) => cache.add(file)));
}

self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(async (cache) => {
      await Promise.all(
        SHELL_FILES.map(async (file) => {
          const response = await fetch(new Request(file, { cache: "reload" }));
          if (response.ok) await cache.put(file, response);
        }),
      );
      await Promise.allSettled(MODEL_FILES.map((file) => cache.add(file)));
      await cachePreparedVoice(cache);
    }),
  );
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key)));
      await self.clients.claim();
    })(),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  // Setup is a standalone camera document, never an offline app-shell fallback.
  if (url.origin !== self.location.origin || url.pathname.startsWith("/api/") || url.pathname.startsWith("/camera-setup/")) return;

  if (request.mode === "navigate") {
    event.respondWith(
      fetch(request, { cache: "no-store" })
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put("/", copy));
          return response;
        })
        .catch(() => caches.match("/")),
    );
    return;
  }

  event.respondWith(
    caches.match(request).then(
      (cached) =>
        cached ||
        fetch(request).then((response) => {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(request, copy));
          }
          return response;
        }),
    ),
  );
});
