import fs from 'node:fs'
import path from 'node:path'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

const packageJson = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, 'package.json'), 'utf-8'),
) as { version?: string }

const frontendVersion =
  typeof packageJson.version === 'string' && packageJson.version.trim()
    ? packageJson.version.trim()
    : '0.0.0'

export default defineConfig({
  plugins: [vue()],
  define: {
    __AMVISION_FRONTEND_VERSION__: JSON.stringify(frontendVersion),
  },
  resolve: {
    alias: {
      '@litegraph': path.resolve(__dirname, 'src/lib/litegraph/src'),
      '@': path.resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./vitest.setup.ts'],
  },
})