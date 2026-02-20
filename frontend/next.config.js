/** @type {import('next').NextConfig} */
const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";

const nextConfig = {
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${BACKEND}/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
