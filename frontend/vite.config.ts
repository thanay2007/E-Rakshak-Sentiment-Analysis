import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
import { defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import type { Plugin } from "vite";

/** Inject a Content-Security-Policy meta tag built from the configured API base.
 *
 *  Written here rather than hardcoded in index.html because `connect-src` has
 *  to name the API and the WebSocket, and those move between deployments. A
 *  hand-maintained policy would either be wrong in production or so loose it
 *  stops being a policy.
 *
 *  Two concessions, both forced and both worth naming:
 *    • 'unsafe-inline' in style-src — Tailwind, GSAP and framer-motion all set
 *      inline styles, and CSS injection is not the threat that matters here.
 *    • 'unsafe-inline' in script-src only in dev, where Vite's HMR client is
 *      inlined. Production builds ship external modules and do not get it, so
 *      the policy that reaches the officers is the strict one.
 */
function csp(apiBase: string, dev: boolean): Plugin {
  const api = apiBase.replace(/\/$/, "");
  const ws = api.replace(/^http/, "ws");
  const scriptSrc = dev ? "'self' 'unsafe-inline'" : "'self'";
  const policy = [
    "default-src 'self'",
    `script-src ${scriptSrc}`,
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com data:",
    // data: and blob: cover the mugshot thumbnails and the PDF/CSV downloads,
    // both of which the app builds client-side from authenticated fetches.
    // The API origin is listed because post images and videos are relayed by
    // /api/media rather than loaded from the platform CDNs directly — the
    // console never asks a browser to fetch from Telegram or Instagram, so no
    // CDN hostname belongs in this policy and none ever needs adding.
    `img-src 'self' data: blob: ${api}`,
    `media-src 'self' blob: ${api}`,
    `connect-src 'self' ${api} ${ws}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
  ].join("; ");

  return {
    name: "sentinel-csp",
    transformIndexHtml(html) {
      return html.replace(
        "</head>",
        `  <meta http-equiv="Content-Security-Policy" content="${policy}" />\n  </head>`
      );
    },
  };
}

export default defineConfig(({ mode }) => {
  // "." is this config's own directory, which is where .env files live. Using
  // it instead of process.cwd() keeps the config free of Node typings.
  const env = loadEnv(mode, ".", "");
  const apiBase = env.VITE_API_BASE_URL || "http://localhost:8000";

  return {
  plugins: [
    csp(apiBase, mode !== "production"),
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.ico', 'apple-touch-icon.png', 'masked-icon.svg'],
      manifest: {
        name: 'SENTINEL Command Center',
        short_name: 'SENTINEL',
        description: 'Sentinel Threat Analysis Dashboard',
        theme_color: '#04080F',
        background_color: '#04080F',
        icons: [
          {
            src: 'pwa-192x192.png',
            sizes: '192x192',
            type: 'image/png',
            purpose: 'any'
          },
          {
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'any'
          },
          {
            // the mark sits at 76% with a full-bleed background, so the same
            // art is safe inside the maskable safe zone
            src: 'pwa-512x512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable'
          }
        ]
      }
    })
  ],
  server: { port: 5173 },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/setupTests.ts'],
    globals: true,
  },
  };
});
