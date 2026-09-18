import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  poweredByHeader: false,
  // Player portraits use direct allowlisted URLs; no public optimizer is needed.
  images: {unoptimized: true},
  async headers() {
    return [{source: '/:path*', headers: [
      {key: 'X-Content-Type-Options', value: 'nosniff'},
      {key: 'X-Frame-Options', value: 'DENY'},
      {key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin'},
      {key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains'},
      {key: 'Cross-Origin-Opener-Policy', value: 'same-origin'},
      {key: 'Cross-Origin-Resource-Policy', value: 'same-origin'},
      {key: 'X-DNS-Prefetch-Control', value: 'off'},
      {key: 'Permissions-Policy', value: 'accelerometer=(), autoplay=(), camera=(), display-capture=(), encrypted-media=(), fullscreen=(self), geolocation=(), gyroscope=(), magnetometer=(), microphone=(), midi=(), payment=(), picture-in-picture=(), publickey-credentials-get=(), screen-wake-lock=(), usb=()'},
    ]}];
  },
};

export default nextConfig;
