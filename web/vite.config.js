import { defineConfig } from 'vite';

// `npm run dev` proxies to a hub running on :8000; `npm run build` writes into the hub package so the
// Jetson serves the UI itself (works offline at the venue - no CDN).
const HUB = process.env.HUB_URL || 'http://localhost:8000';

export default defineConfig({
  build: {
    outDir: '../hub/physiobuddy_hub/api/static',
    emptyOutDir: true,
    chunkSizeWarningLimit: 800, // three.js is one ~575 kB chunk; fine for a LAN-served station UI
  },
  server: {
    host: true,
    proxy: {
      '/api': HUB,
      '/debug': HUB,
      '/ws': { target: HUB.replace(/^http/, 'ws'), ws: true },
    },
  },
});
