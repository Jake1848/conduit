/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The project ships without an ESLint config; type-checking (tsc) still runs on build.
  eslint: { ignoreDuringBuilds: true },
};

module.exports = nextConfig;
