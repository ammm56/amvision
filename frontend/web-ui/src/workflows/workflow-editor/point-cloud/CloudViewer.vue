<template>
  <section class="cloud-viewer">
    <div class="cloud-tools">
      <button :title="t('reset')" :aria-label="t('reset')" :disabled="!scene" @click="axis = 'iso'; scene?.fit()"><RotateCcw :size="18" /></button>
      <button :title="t('pan')" :aria-label="t('pan')" :aria-pressed="pan" :disabled="!scene" @click="pan = !pan; scene?.pan(pan)"><Hand :size="18" /></button>
      <label>{{ t('projection') }}<select v-model="orthographic" :disabled="!scene" @change="scene?.projection(orthographic)"><option :value="false">{{ t('perspective') }}</option><option :value="true">{{ t('orthographic') }}</option></select></label>
      <label>{{ t('axis') }}<select v-model="axis" :disabled="!scene" @change="scene?.fit(axis)"><option value="iso">3D</option><option value="x">X</option><option value="y">Y</option><option value="z">Z</option></select></label>
      <label>{{ t('size') }}<input v-model.number="size" :disabled="!scene" type="range" min="1" max="8" step="1" @input="scene?.pointSize(size)"></label>
    </div>
    <div class="cloud-stage">
      <div ref="host" class="cloud-canvas" />
      <p v-if="loading" role="status" class="cloud-message">{{ t('loading') }}</p>
      <div v-else-if="error" role="alert" class="cloud-message"><p>{{ t(error) }}</p><button :title="t('retry')" @click="load"><RefreshCw :size="18" /></button></div>
      <p v-else-if="body.state !== 'ready'" class="cloud-message">{{ body.state === 'empty' ? t('empty') : String(body.reason || t('unavailable')) }}</p>
    </div>
    <div class="cloud-status">
      <span>{{ unit }} · {{ frame }} · {{ body.display_point_count ?? '-' }} / {{ body.source_point_count ?? '-' }}</span>
      <span v-if="color.mode === 'scalar'">{{ color.field }}: {{ color.min ?? '-' }} .. {{ color.max ?? '-' }}</span>
      <span v-if="picked">#{{ picked.sourceIndex }} · XYZ {{ picked.xyz.join(', ') }}<template v-if="picked.scalar !== null"> · {{ picked.scalar }}</template></span>
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Hand, RefreshCw, RotateCcw } from '@lucide/vue'
import { readCloudCapabilities } from '../services/measurement-resource.service'
import { decodeCloudPreview, type CloudDisplayData } from './preview-data'
import { createCloudRenderer } from './renderer'

const props = defineProps<{ payload: Record<string, unknown>; projectId: string }>()
const { t } = useI18n({ useScope: 'local', messages: {
  'zh-CN': { reset: '复位视角', pan: '平移', projection: '投影', perspective: '透视', orthographic: '正交', axis: '视图', size: '点大小', loading: '正在读取显示数据', retry: '重新打开', empty: '无有效显示点', unavailable: '显示不可用', unknown: '单位未确认', cloud_renderer_unconfigured: '三维显示预算尚未配置', cloud_preview_invalid: '显示数据格式无效', cloud_preview_capacity: '显示数据超过点数或字节限额', cloud_preview_checksum: '显示数据摘要不一致', cloud_cpu_capacity: '浏览器内存预算不足', cloud_gpu_capacity: '渲染缓冲预算不足', cloud_canvas_capacity: '视口超过像素预算', cloud_position_precision: '局部坐标显示误差超过配置限额', cloud_context_lost: 'WebGL 上下文已丢失' },
  'en-US': { reset: 'Reset view', pan: 'Pan', projection: 'Projection', perspective: 'Perspective', orthographic: 'Orthographic', axis: 'View', size: 'Point size', loading: 'Loading display data', retry: 'Reopen', empty: 'No valid display points', unavailable: 'Display unavailable', unknown: 'Unit unconfirmed', cloud_renderer_unconfigured: '3D display budget is not configured', cloud_preview_invalid: 'Invalid display data', cloud_preview_capacity: 'Display point or byte limit exceeded', cloud_preview_checksum: 'Display checksum mismatch', cloud_cpu_capacity: 'Browser memory budget exceeded', cloud_gpu_capacity: 'Rendering buffer budget exceeded', cloud_canvas_capacity: 'Viewport pixel budget exceeded', cloud_position_precision: 'Local coordinate display error exceeds the configured limit', cloud_context_lost: 'WebGL context lost' },
} })
const host = ref<HTMLElement>(), scene = shallowRef<ReturnType<typeof createCloudRenderer> | null>(null)
function displayObject(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
const body = computed(() => props.payload), color = computed(() => displayObject(body.value.color))
const unit = computed(() => displayObject(body.value.spatial).length_unit || t('unknown'))
const frame = computed(() => displayObject(body.value.spatial).frame_id)
const loading = ref(false), error = ref(''), pan = ref(false), orthographic = ref(false), size = ref(2)
const axis = ref<'iso' | 'x' | 'y' | 'z'>('iso')
const picked = ref<ReturnType<CloudDisplayData['point']> | null>(null)
let generation = 0, controller: AbortController | null = null, data: CloudDisplayData | null = null
function release() { generation++; controller?.abort(); controller = null; scene.value?.dispose(); scene.value = null; data?.dispose(); data = null; picked.value = null }
async function load() {
  release(); const token = generation; controller = new AbortController(); const signal = controller.signal
  error.value = ''; loading.value = true; pan.value = false; orthographic.value = false; size.value = 2; axis.value = 'iso'
  try {
    if (body.value.state !== 'ready') return
    const policy = (await readCloudCapabilities(props.projectId, signal)).renderer
    if (signal.aborted || token !== generation) return
    if (!policy) throw new Error('cloud_renderer_unconfigured')
    const decoded = await decodeCloudPreview(body.value, policy, signal)
    if (signal.aborted || token !== generation || !host.value) { decoded.dispose(); return }
    data = decoded
    scene.value = createCloudRenderer(host.value, data, policy, index => { picked.value = decoded.point(index) }, failure => { release(); error.value = failure.message; loading.value = false })
  } catch (failure) {
    if (token === generation && !signal.aborted) { scene.value?.dispose(); scene.value = null; data?.dispose(); data = null; error.value = failure instanceof Error ? failure.message : 'unavailable' }
  } finally { if (token === generation) loading.value = false }
}
onMounted(load)
watch(() => [props.payload, props.projectId], load)
onBeforeUnmount(release)
</script>
<style scoped>
.cloud-viewer { display: grid; grid-template-rows: auto minmax(180px, 1fr) auto; width: 100%; height: min(72dvh, 720px); min-width: 0; }
.cloud-tools { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 8px 0; }
.cloud-tools label { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.cloud-tools button, .cloud-message button { display: inline-grid; place-items: center; width: 32px; height: 32px; border: 1px solid var(--am-border); border-radius: 4px; color: var(--am-text); background: var(--am-surface); }
.cloud-tools button[aria-pressed=true] { background: var(--am-success-surface); outline: 2px solid var(--am-brand-primary); }
.cloud-tools input { width: 80px; }
.cloud-stage { position: relative; min-width: 0; min-height: 0; background: var(--am-surface-soft); }
.cloud-canvas { position: absolute; inset: 0; overflow: hidden; touch-action: none; }
.cloud-message { position: absolute; inset: 0; margin: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 16px; text-align: center; overflow-wrap: anywhere; }
.cloud-status { display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 8px 0; font-size: 12px; overflow-wrap: anywhere; }
@media(max-width: 640px) { .cloud-viewer { height: 65dvh; } }
</style>
