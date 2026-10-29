import { PHASE_DEVELOPMENT_SERVER } from 'next/constants.js';

/** @returns {import('next').NextConfig} */
export default function config(phase) {
  const development = phase === PHASE_DEVELOPMENT_SERVER;
  return {
    ...(development ? {} : { output: 'export' }),
    reactStrictMode: false,
    experimental: { useTypeScriptCli: false },
    trailingSlash: true,
    ...(development ? {
      async rewrites() {
        return [{ source: '/api/:path*', destination: `${process.env.BACKEND_URL || 'http://127.0.0.1:8000'}/api/:path*` }];
      },
    } : {}),
  };
}
