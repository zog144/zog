import {releasePlugin} from './scripts/release-plugin.mjs'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react(), releasePlugin()],
  build: {emptyOutDir: true, sourcemap: false},
  server: {
    proxy: {
      '/licenses': 'http://127.0.0.1:8000',
      '/frontend-build.json': 'http://127.0.0.1:8000',
      '/api': 'http://127.0.0.1:8000',
      '/novnc': 'http://127.0.0.1:8000',
      '/websockify': { target: 'ws://127.0.0.1:6080', ws: true },
    },
  },
})
