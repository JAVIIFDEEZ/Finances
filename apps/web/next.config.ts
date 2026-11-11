import type { NextConfig } from "next";

/**
 * The browser only talks to this origin: `/api/v1/*` and `/health/*` are proxied to the
 * InvestingLab API (FastAPI), so no CORS is involved and a single port can be shared.
 */
const API_URL = process.env.INVESTINGLAB_API_URL ?? "http://127.0.0.1:8000";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Some sources (the ECB portal) can take over 30 s on a cold cache: give the proxy room.
  experimental: { proxyTimeout: 120_000 },
  async rewrites() {
    return [
      { source: "/api/v1/:path*", destination: `${API_URL}/api/v1/:path*` },
      { source: "/health/:path*", destination: `${API_URL}/health/:path*` },
    ];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default config;
