import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 开发环境把 /api 转发到 FastAPI
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
