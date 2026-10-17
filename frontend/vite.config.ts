import { fileURLToPath, URL } from 'node:url';
import { defineConfig, loadEnv } from 'vite';
import react from '@vitejs/plugin-react';

const projectRoot = fileURLToPath(new URL('..', import.meta.url));
const frontendRoot = fileURLToPath(new URL('.', import.meta.url));

export default defineConfig(({ mode }) => {
  const values = loadEnv(mode, projectRoot, ['APP_PORT', 'FRONTEND_PORT']);
  const apiPort = Number(process.env.APP_PORT ?? values.APP_PORT ?? 8000);
  const frontendPort = Number(process.env.FRONTEND_PORT ?? values.FRONTEND_PORT ?? 5173);
  if (
    ![apiPort, frontendPort].every((p) => Number.isInteger(p) && p >= 1024 && p <= 65535) ||
    apiPort === frontendPort
  ) {
    throw new Error(
      'APP_PORT and FRONTEND_PORT must be distinct local ports between 1024 and 65535',
    );
  }
  return {
    plugins: [react()],
    server: {
      host: '127.0.0.1',
      port: frontendPort,
      strictPort: true,
      allowedHosts: ['127.0.0.1', 'localhost'],
      cors: false,
      fs: {
        strict: true,
        allow: [frontendRoot, fileURLToPath(new URL('../contracts/generated', import.meta.url))],
        deny: ['.env', '.env.*', '*.pem', '*.key', '**/.git/**', '**/private/**'],
      },
      proxy: { '/api': { target: `http://127.0.0.1:${apiPort}`, changeOrigin: false } },
    },
    preview: { host: '127.0.0.1', strictPort: true, allowedHosts: ['127.0.0.1', 'localhost'] },
    build: { outDir: 'dist', emptyOutDir: true },
  };
});
