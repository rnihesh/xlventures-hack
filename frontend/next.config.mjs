/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Minimal self-contained server bundle for a tiny production image: the Docker
  // runtime stage copies only .next/standalone + .next/static + public.
  output: "standalone",
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8200",
  },
};

export default nextConfig;
