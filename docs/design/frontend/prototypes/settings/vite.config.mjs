import vue from '../../../../../frontend/web-ui/node_modules/@vitejs/plugin-vue/dist/index.mjs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
const requireFrontend = createRequire(new URL('../../../../../frontend/web-ui/package.json', import.meta.url))
export default {plugins:[vue()],resolve:{alias:{vue:requireFrontend.resolve('vue/dist/vue.esm-bundler.js'),'@lucide/vue':requireFrontend.resolve('@lucide/vue')}},server:{fs:{allow:[fileURLToPath(new URL('../../../../../',import.meta.url))]}}}
