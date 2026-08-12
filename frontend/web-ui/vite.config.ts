import fs from 'node:fs'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import vue from '@vitejs/plugin-vue'
import { defineConfig } from 'vitest/config'

const projectDirectory = import.meta.dirname
const packageJson = JSON.parse(
  fs.readFileSync(path.resolve(projectDirectory, 'package.json'), 'utf-8'),
) as { version?: string }

const frontendVersion =
  typeof packageJson.version === 'string' && packageJson.version.trim()
    ? packageJson.version.trim()
    : '0.0.0'
const vitestSetupFile = pathToFileURL(
  path.resolve(projectDirectory, 'vitest.setup.ts'),
).href

export default defineConfig({
  plugins: [vue()],
  define: {
    __AMVISION_FRONTEND_VERSION__: JSON.stringify(frontendVersion),
  },
  resolve: {
    alias: {
      '@litegraph': path.resolve(projectDirectory, 'src/lib/litegraph/src'),
      '@': path.resolve(projectDirectory, 'src'),
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    rollupOptions: {
      output: {
        manualChunks(moduleId) {
          const normalizedId = moduleId.replaceAll('\\', '/')
          if (
            normalizedId.includes('/node_modules/vue/')
            || normalizedId.includes('/node_modules/vue-router/')
            || normalizedId.includes('/node_modules/pinia/')
            || normalizedId.includes('/node_modules/vue-i18n/')
          ) {
            return 'vendor-vue'
          }
          if (
            normalizedId.includes('/node_modules/@lucide/vue/')
            || normalizedId.includes('/node_modules/@vueuse/')
            || normalizedId.includes('/node_modules/reka-ui/')
          ) {
            return 'vendor-ui'
          }
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: [vitestSetupFile],
  },
})
