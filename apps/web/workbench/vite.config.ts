import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { previewApi } from './scripts/preview-api.mjs';

export default defineConfig({
  plugins: [react(), previewApi()],
  base: '/',
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    target: 'es2022',
  },
  server: {
    port: 5173,
    host: "0.0.0.0",
    allowedHosts: ["terminal.local"],
  },
});
