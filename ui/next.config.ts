import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "export",
  // Static export — no Node.js runtime needed
  // Served by FastAPI StaticFiles in production
  images: {
    unoptimized: true, // required for static export
  },
};

export default nextConfig;
