import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

declare const process: { env: Record<string, string | undefined> }

export default defineConfig({
  plugins: [vue()],
  server: {
    // Адрес API для разработки интерфейса: по умолчанию локальный сервер, можно указать работающий Docker.
    proxy: { '/api': process.env.LEADS_API ?? 'http://127.0.0.1:8000' },
  },
  build: { outDir: 'dist', emptyOutDir: true },
})
