// 隔离验收必须覆盖运行配置文件，不能只设置低优先级的 Vite 环境变量。
import { createServer } from '../../../frontend/web-ui/node_modules/vite/dist/node/index.js'
import { fileURLToPath } from 'node:url'
import { readFileSync } from 'node:fs'

const [portText, apiPortText, probeFile] = process.argv.slice(2)
const port = Number(portText), apiPort = Number(apiPortText)
if (![port, apiPort].every(value => Number.isInteger(value) && value >= 1024 && value <= 65535)
  || port === apiPort || [port, apiPort].some(value => [5600, 5601].includes(value))) {
  throw new Error('Specify separate, non-business UI and API ports')
}
const server = await createServer({
  configFile: fileURLToPath(new URL('../../../frontend/web-ui/vite.config.ts', import.meta.url)),
  server: { host: '127.0.0.1', port, strictPort: true,
    ...(probeFile ? { fs: { allow: [fileURLToPath(new URL('.', import.meta.url)), fileURLToPath(new URL('../../../frontend/web-ui', import.meta.url))] } } : {}),
  },
  plugins: [{
    name: 'isolated-metrology-runtime-config',
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        if (probeFile && request.url === '/__metrology_probe/response.json') {
          response.setHeader('Content-Type', 'application/json')
          response.setHeader('Cache-Control', 'no-store')
          response.end(readFileSync(probeFile)); return
        }
        if (probeFile && request.url === '/__metrology_probe') {
          response.setHeader('Content-Type', 'text/html')
          response.end('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Metrology fault acceptance</title><div id="app"></div><script type="module" src="/@fs/' + fileURLToPath(new URL('./viewer_fault_probe.ts', import.meta.url)).replaceAll('\\', '/') + '"></script></html>'); return
        }
        if (!['/runtime-config.local.json', '/runtime-config.json', '/runtime-config.template.json'].includes(request.url?.split('?')[0])) return next()
        response.setHeader('Content-Type', 'application/json')
        response.setHeader('Cache-Control', 'no-store')
        response.end(JSON.stringify({
          apiBaseUrl: `http://127.0.0.1:${apiPort}/api/v1`,
          wsBaseUrl: `ws://127.0.0.1:${apiPort}/ws/v1`,
          defaultProjectId: 'project-1',
          auth: { autoLoginEnabled: false },
        }))
      })
    },
  }],
})
await server.listen()
server.printUrls()
for (const signal of ['SIGINT', 'SIGTERM']) {
  process.once(signal, async () => { await server.close(); process.exit(0) })
}
