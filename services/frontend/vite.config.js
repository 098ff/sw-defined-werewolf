import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// In dev, API + health calls go to the gateway so traces are real. No WebSocket proxying.
const GATEWAY_URL = process.env.VITE_GATEWAY_URL || 'http://localhost:8080';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    host: '0.0.0.0',
    proxy: {
      '/api': { target: GATEWAY_URL, changeOrigin: true },
      '/health': { target: GATEWAY_URL, changeOrigin: true }
    }
  }
});
