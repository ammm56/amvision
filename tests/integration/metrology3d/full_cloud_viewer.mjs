// 读取完整样本回归生成的真实显示证据；只提供显式测试容量，不代替发布验收。
import {createServer} from '../../../frontend/web-ui/node_modules/vite/dist/node/index.js'
import {createReadStream,statSync} from 'node:fs'
import {resolve} from 'node:path'
import {fileURLToPath} from 'node:url'

const [file,portText]=process.argv.slice(2),port=Number(portText)
if(!file||!Number.isInteger(port)||port<1024||port>65535||[5600,5601].includes(port))throw new Error('Provide a real preview JSON and isolated port')
const path=resolve(file);if(!statSync(path).isFile())throw new Error('Preview file required')
const server=await createServer({
  configFile:fileURLToPath(new URL('../../../frontend/web-ui/vite.config.ts',import.meta.url)),
  server:{host:'127.0.0.1',port,strictPort:true,fs:{allow:[fileURLToPath(new URL('.',import.meta.url))]}},
  plugins:[{name:'full-cloud-verification',configureServer(server){server.middlewares.use((request,response,next)=>{
    const url=request.url?.split('?')[0]
    if(url==='/real-preview.json'){response.setHeader('Content-Type','application/json');createReadStream(path).pipe(response);return}
    if(url?.startsWith('/runtime-config')){response.setHeader('Content-Type','application/json');response.end(JSON.stringify({apiBaseUrl:`http://127.0.0.1:${port}/api/v1`,auth:{autoLoginEnabled:false}}));return}
    if(url==='/api/v1/workflows/projects/test/measurement-resources/cloud/capabilities'){
      response.setHeader('Content-Type','application/json');response.end(JSON.stringify({max_archive_bytes:null,renderer:{max_points:1000000,max_data_bytes:32000000,max_cpu_bytes:400000000,max_gpu_bytes:100000000,max_canvas_pixels:4000000,max_position_error:.001}}));return
    }
    if(url==='/verify'){
      response.setHeader('Content-Type','text/html');response.end('<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Real Cloud Viewer Acceptance</title><div id="app"></div><script type="module" src="/@fs/'+fileURLToPath(new URL('./full_cloud_viewer.ts',import.meta.url)).replaceAll('\\','/')+'"></script></html>');return
    }
    if(url==='/mobile'){
      response.setHeader('Content-Type','text/html');response.end('<!doctype html><html><meta charset="utf-8"><title>390px Cloud Viewport</title><iframe title="390px cloud viewport" src="/verify" width="390" height="720" style="border:0"></iframe></html>');return
    }
    next()
  })}}],
})
await server.listen();server.printUrls()
for(const signal of ['SIGINT','SIGTERM'])process.once(signal,async()=>{await server.close();process.exit(0)})
