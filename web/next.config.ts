import type { NextConfig } from "next";

const config: NextConfig = {
  output: "export",
  reactStrictMode: true,
  poweredByHeader: false,
  images: { unoptimized: true },
  trailingSlash: false,
  // One round trip less before first paint on slow connections.
  experimental: { inlineCss: true },
};

export default config;
