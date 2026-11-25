import { defineConfig } from '@playwright/test'

export default defineConfig({
  testDir: './tests', workers: 1,
  use: { baseURL: 'http://127.0.0.1:4182', channel: 'chrome', viewport: { width:390,height:844 }, hasTouch:true },
  webServer: { command:'npm run build && npx vite preview --host 127.0.0.1 --port 4182 --strictPort', url:'http://127.0.0.1:4182' },
})
