/** @type {import('next').NextConfig} */
const backendUrl = process.env.BACKEND_INTERNAL_URL || 'http://127.0.0.1:8000';

const nextConfig = {
  reactStrictMode: true,
  output: 'standalone',
  async rewrites() {
    return [
      {
        source: '/api/proxy/:path*',
        destination: `${backendUrl}/api/v1/:path*`,
      },
    ];
  },
};

module.exports = nextConfig;
