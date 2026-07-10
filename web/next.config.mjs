/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Windows: spawn EPERM in jest-worker during getStaticPaths.
  // Use worker_threads instead of child_process.fork to avoid spawn.
  experimental: {
    workerThreads: true,
  },
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.NEXT_PUBLIC_API_BASE || 'http://localhost:8000'}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
