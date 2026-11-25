import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import pkg from './package.json'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: { '@web': fileURLToPath(new URL('../knowledge_front/src', import.meta.url)) },
    dedupe: Object.keys(pkg.dependencies),
  },
  server: {
    host: '127.0.0.1', port: 5180, strictPort: true,
    fs: { allow: ['.', '../knowledge_front/src', '../knowledge_front/public/brand'] },
    proxy: { '/api': { target: 'http://127.0.0.1:5000', changeOrigin: true } },
  },
})
