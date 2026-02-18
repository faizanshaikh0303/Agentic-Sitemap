/** @type {import('next').NextConfig} */
const nextConfig = {
  // Allow the frontend to call the Python backend on localhost:8000
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: "http://localhost:8000/:path*",
      },
    ];
  },
};

module.exports = nextConfig;
