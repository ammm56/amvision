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
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'vendor-echarts',
              test: /node_modules[\\/](?:echarts|zrender)[\\/]/,
              priority: 2,
              maxSize: 300 * 1024,
            },
            {
              name: 'vendor-vue',
              test: /node_modules[\\/](?:vue|vue-router|pinia|vue-i18n)[\\/]/,
              priority: 1,
            },
            {
              name: 'vendor-ui',
              test: /node_modules[\\/](?:@lucide[\\/]vue|@vueuse|reka-ui)[\\/]/,
              priority: 1,
            },
          ],
        },
      },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['src/**/*.test.ts'],
    setupFiles: [vitestSetupFile],
  },
})
