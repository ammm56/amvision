// 仅由隔离 published_ui 显式启用；使用真实发布回执、API 和生产查看器。
import { computed, createApp, h, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { createPinia, setActivePinia } from 'pinia'
import CloudViewer from '../../../frontend/web-ui/src/workflows/workflow-editor/point-cloud/CloudViewer.vue'
import { rendererUsage } from '../../../frontend/web-ui/src/workflows/workflow-editor/point-cloud/preview-data'
import { loadRuntimeConfig } from '../../../frontend/web-ui/src/platform/runtime/runtime-config'
import { useSessionStore } from '../../../frontend/web-ui/src/app/stores/session.store'
import { configureHttpClient } from '../../../frontend/web-ui/src/shared/api/http-client'
import '../../../frontend/web-ui/src/shared/styles/tokens/brand.css'
import '../../../frontend/web-ui/src/shared/styles/tokens/semantic.css'
import '../../../frontend/web-ui/src/shared/styles/tokens/light.css'
import '../../../frontend/web-ui/src/shared/styles/base.css'

await loadRuntimeConfig()
const pinia = createPinia()
setActivePinia(pinia)
const session = useSessionStore(pinia)
configureHttpClient({
  getAccessToken: () => session.accessToken,
  refreshAccessToken: () => session.refreshAccessToken(),
  onUnauthorized: () => session.clearForAuthFailure(),
})
await session.initializeSession()
if (!session.isAuthenticated) throw new Error('Log in through the isolated application before opening this probe')
const run = await (await fetch('/__metrology_probe/response.json')).json()
if (run.state !== 'succeeded') throw new Error('A successful real published run is required')
const payload = run.results.http_response.body
if (!payload.asset_details || payload.state !== 'ready') throw new Error('Asset detail preview required')

createApp({ setup() {
  const visible = ref(true), revision = ref(0), resource = ref(''), loss = ref('')
  const current = computed(() => ({ ...payload, observation_id: `${payload.observation_id}:probe:${revision.value}` }))
  function loseContext() {
    const canvas = document.querySelector('canvas[aria-label="3D point cloud"]') as HTMLCanvasElement | null
    const gl = canvas?.getContext('webgl2')
    const extension = gl?.getExtension('WEBGL_lose_context')
    loss.value = extension ? 'WebGL_lose_context invoked' : 'WebGL_lose_context unavailable'
    extension?.loseContext()
  }
  function observe() {
    const memory = (performance as Performance & { memory?: { usedJSHeapSize: number } }).memory
    const requests = performance.getEntriesByType('resource').filter(entry => entry.name.includes('/details/'))
    resource.value = JSON.stringify({ ...rendererUsage(), canvases: document.querySelectorAll('canvas').length,
      jsHeapBytes: memory?.usedJSHeapSize ?? null, gpuMemoryBytes: null,
      detailRequestsRetained: requests.length, lastDetailRequestStartMs: requests.at(-1)?.startTime ?? null })
  }
  return () => h('main', { style: 'padding:16px;color:var(--am-text);background:var(--am-surface)' }, [
    h('header', { style: 'display:flex;gap:8px;align-items:center;flex-wrap:wrap' }, [
      h('strong', '完整工件显示故障验收'),
      h('button', { onClick: () => visible.value = !visible.value }, visible.value ? '关闭显示' : '重新打开'),
      h('button', { onClick: () => revision.value++, disabled: !visible.value }, '切换显示身份'),
      h('button', { onClick: loseContext, disabled: !visible.value }, '触发上下文丢失'),
      h('button', { onClick: observe }, '读取资源'),
      h('output', { 'aria-label': '测试资源观测', style: 'min-width:0;max-width:100%;overflow-wrap:anywhere' }, resource.value),
      h('output', { 'aria-label': '故障注入状态' }, loss.value),
    ]),
    visible.value ? h(CloudViewer, { payload: current.value,
      projectId: payload.source_asset.project_id, allowPick: true }) : null,
  ])
} }).use(pinia).use(createI18n({ legacy: false, locale: 'zh-CN', messages: { 'zh-CN': {} } })).mount('#app')
