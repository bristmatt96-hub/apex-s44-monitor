/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // API proxy to FastAPI backend on VPS
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://143.198.56.117:8000/api/:path*',
      },
    ]
  },
}

module.exports = nextConfig
