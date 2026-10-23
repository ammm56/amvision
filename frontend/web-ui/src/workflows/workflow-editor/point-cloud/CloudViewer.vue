<template>
  <section class="cloud-viewer">
    <div class="cloud-tools">
      <button :title="t('reset')" :aria-label="t('reset')" :disabled="!scene" @click="axis = 'iso'; scene?.fit()"><RotateCcw :size="18" /></button>
      <button :title="t('pan')" :aria-label="t('pan')" :aria-pressed="pan" :disabled="!scene" @click="pan = !pan; scene?.pan(pan)"><Hand :size="18" /></button>
      <button v-if="allowPick" :title="zh?'拾取候选位置':'Pick candidate position'" :aria-label="zh?'拾取候选位置':'Pick candidate position'" :aria-pressed="picking" :disabled="!scene" @click="picking=!picking"><Crosshair :size="18" /></button>
      <label>{{ t('projection') }}<select v-model="orthographic" :disabled="!scene" @change="scene?.projection(orthographic)"><option :value="false">{{ t('perspective') }}</option><option :value="true">{{ t('orthographic') }}</option></select></label>
      <label>{{ t('axis') }}<select v-model="axis" :disabled="!scene" @change="scene?.fit(axis)"><option value="iso">3D</option><option value="x">X</option><option value="y">Y</option><option value="z">Z</option></select></label>
      <label>{{ t('size') }}<input v-model.number="size" :disabled="!scene" type="range" min="1" max="8" step="1" @input="scene?.pointSize(size)"></label>
      <template v-if="planes.length"><label>{{ zh?'平面':'Plane' }}<select v-model="selectedPlane"><option value="">{{ zh?'未选择':'None' }}</option><option v-for="plane in planes" :key="String(plane.feature_id)" :value="String(plane.feature_id)">{{ plane.feature_id }}</option></select></label><label>{{ zh?'颜色':'Color' }}<select v-model="colorMode" :disabled="!selectedPlane||!scene"><option value="original">{{ zh?'原始':'Original' }}</option><option value="support">{{ zh?'支持 / 剔除':'Support / rejected' }}</option><option value="residual">{{ zh?'有符号残差':'Signed residual' }}</option></select></label></template>
      <template v-if="editRois?.length"><button :title="zh?'移动 ROI':'Move ROI'" :aria-label="zh?'移动 ROI':'Move ROI'" :aria-pressed="editMode==='translate'" :disabled="!scene" @click="editMode='translate'"><Move3D :size="18" /></button><button :title="zh?'旋转 ROI':'Rotate ROI'" :aria-label="zh?'旋转 ROI':'Rotate ROI'" :aria-pressed="editMode==='rotate'" :disabled="!scene" @click="editMode='rotate'"><Rotate3D :size="18" /></button></template>
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
      <span v-if="colorMode==='support'&&colorSummary">{{ zh?'显示点':'Display points' }} · {{ zh?'支持':'Support' }} {{ colorSummary.support }} · {{ zh?'剔除':'Rejected' }} {{ colorSummary.rejected }} · {{ zh?'无关':'Unrelated' }} {{ colorSummary.unrelated }}</span>
      <span v-if="colorMode==='residual'&&colorSummary">{{ zh?'残差色标':'Residual scale' }} <template v-if="colorSummary.extent!==null"><i class="residual-scale" aria-hidden="true"/> {{ -colorSummary.extent }} .. {{ colorSummary.extent }} {{ unit }}</template><template v-else>{{ zh?'无显示支持点':'No displayed support points' }}</template></span>
    </div>
    <GeometrySummary v-if="body.geometry" :geometry="displayObject(body.geometry)" :selected="selectedPlane" @select-plane="selectedPlane=$event" />
    <MeasurementSummary v-if="measurements.length" :items="measurements" :unit="String(unit)" :selected="selectedMeasurement" @select="selectedMeasurement=$event" />
  </section>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, shallowRef, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Hand, RefreshCw, RotateCcw, Move3D, Rotate3D, Crosshair } from '@lucide/vue'
import { readCloudCapabilities } from '../services/measurement-resource.service'
import { decodeCloudPreview, type CloudDisplayData } from './preview-data'
import { createCloudRenderer } from './renderer'
import GeometrySummary from './GeometrySummary.vue'
import MeasurementSummary from './MeasurementSummary.vue'
import {measurementItems,type MeasurementDisplay} from './measurement-display'
import {planeColorData,planeColorSummary} from './plane-colors'
import type {RoiValue} from './geometry-overlay'

const props = defineProps<{ payload: Record<string, unknown>; projectId: string; editRois?:RoiValue[]; selectedRoiId?:string; allowPick?:boolean; candidate?:number[] }>()
const emit=defineEmits<{'roi-change':[value:RoiValue];candidate:[value:{payload:Record<string,unknown>;xyz:number[]}]}>()
const { t,locale } = useI18n({ useScope: 'local', messages: {
  'zh-CN': { reset: '复位视角', pan: '平移', projection: '投影', perspective: '透视', orthographic: '正交', axis: '视图', size: '点大小', loading: '正在读取显示数据', retry: '重新打开', empty: '无有效显示点', unavailable: '显示不可用', unknown: '单位未确认', cloud_renderer_unconfigured: '三维显示预算尚未配置', cloud_preview_invalid: '显示数据格式无效', cloud_preview_capacity: '显示数据超过点数或字节限额', cloud_preview_checksum: '显示数据摘要不一致', cloud_cpu_capacity: '浏览器内存预算不足', cloud_gpu_capacity: '渲染缓冲预算不足', cloud_canvas_capacity: '视口超过像素预算', cloud_position_precision: '局部坐标显示误差超过配置限额', cloud_context_lost: 'WebGL 上下文已丢失' },
  'en-US': { reset: 'Reset view', pan: 'Pan', projection: 'Projection', perspective: 'Perspective', orthographic: 'Orthographic', axis: 'View', size: 'Point size', loading: 'Loading display data', retry: 'Reopen', empty: 'No valid display points', unavailable: 'Display unavailable', unknown: 'Unit unconfirmed', cloud_renderer_unconfigured: '3D display budget is not configured', cloud_preview_invalid: 'Invalid display data', cloud_preview_capacity: 'Display point or byte limit exceeded', cloud_preview_checksum: 'Display checksum mismatch', cloud_cpu_capacity: 'Browser memory budget exceeded', cloud_gpu_capacity: 'Rendering buffer budget exceeded', cloud_canvas_capacity: 'Viewport pixel budget exceeded', cloud_position_precision: 'Local coordinate display error exceeds the configured limit', cloud_context_lost: 'WebGL context lost' },
} })
const host = ref<HTMLElement>(), scene = shallowRef<ReturnType<typeof createCloudRenderer> | null>(null)
const zh=computed(()=>locale.value==='zh-CN'),editMode=ref<'translate'|'rotate'>('translate')
function updateGeometry(){scene.value?.geometry({payload:props.payload,rois:props.editRois,selectedId:props.selectedRoiId,mode:editMode.value,changed:props.editRois?roi=>emit('roi-change',roi):undefined,selectedMeasurement: selectedMeasurement.value,selectedPlane:selectedPlane.value,candidate:props.candidate})}
function updateColors(){try{const samples=planeColorData(props.payload,selectedPlane.value);colorSummary.value=planeColorSummary(samples);scene.value?.colors(samples,colorMode.value)}catch(failure){release();error.value=failure instanceof Error?failure.message:'unavailable'}}
function displayObject(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
const body = computed(() => props.payload), color = computed(() => displayObject(body.value.color))
const unit = computed(() => displayObject(body.value.spatial).length_unit || t('unknown'))
const frame = computed(() => displayObject(body.value.spatial).frame_id)
const loading = ref(false), error = ref(''), pan = ref(false), orthographic = ref(false), size = ref(2)
const axis = ref<'iso' | 'x' | 'y' | 'z'>('iso')
const picked = ref<ReturnType<CloudDisplayData['point']> | null>(null)
const picking=ref(false),measurements=ref<MeasurementDisplay[]>([]),selectedMeasurement=ref('')
const selectedPlane=ref(''),colorMode=ref<'original'|'support'|'residual'>('original')
const colorSummary=ref<ReturnType<typeof planeColorSummary>>(null)
const planes=computed(()=>{const raw=displayObject(body.value.geometry).planes;return Array.isArray(raw)?raw.map(displayObject):[]})
let generation = 0, controller: AbortController | null = null, data: CloudDisplayData | null = null
function release() { generation++; controller?.abort(); controller = null; scene.value?.dispose(); scene.value = null; data?.dispose(); data = null; picked.value = null;picking.value=false;measurements.value=[];selectedMeasurement.value='';selectedPlane.value='';colorMode.value='original';colorSummary.value=null }
async function load() {
  release(); const token = generation; controller = new AbortController(); const signal = controller.signal
  error.value = ''; loading.value = true; pan.value = false; orthographic.value = false; size.value = 2; axis.value = 'iso'
  try {
    measurements.value=measurementItems(body.value)
    selectedMeasurement.value=measurements.value[0]?.item_id??''
    if (body.value.state !== 'ready') return
    const policy = (await readCloudCapabilities(props.projectId, signal)).renderer
    if (signal.aborted || token !== generation) return
    if (!policy) throw new Error('cloud_renderer_unconfigured')
    const decoded = await decodeCloudPreview(body.value, policy, signal)
    if (signal.aborted || token !== generation || !host.value) { decoded.dispose(); return }
    data = decoded
    const payload=props.payload
    scene.value = createCloudRenderer(host.value, data, policy, index => {
      if(token!==generation||signal.aborted||props.payload!==payload)return
      picked.value = decoded.point(index)
      if(props.allowPick&&picking.value)emit('candidate',{payload,xyz:[...picked.value.xyz]})
    }, failure => { release(); error.value = failure.message; loading.value = false })
    updateGeometry()
  } catch (failure) {
    if (token === generation && !signal.aborted) { scene.value?.dispose(); scene.value = null; data?.dispose(); data = null; error.value = failure instanceof Error ? failure.message : 'unavailable' }
  } finally { if (token === generation) loading.value = false }
}
onMounted(load)
watch(() => [props.payload, props.projectId], load)
watch(()=>[props.editRois,props.selectedRoiId,editMode.value,selectedMeasurement.value,selectedPlane.value,props.candidate],updateGeometry,{deep:true})
watch(()=>[selectedPlane.value,colorMode.value],updateColors)
watch(()=>props.allowPick,()=>{picking.value=false})
onBeforeUnmount(release)
</script>
<style scoped>
.cloud-viewer { display: grid; grid-template-rows: auto minmax(180px, 1fr) auto; grid-auto-rows:auto; width: 100%; height: min(72dvh, 720px); min-width: 0; }
.cloud-tools { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 8px 0; }
.cloud-tools label { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.cloud-tools button, .cloud-message button { display: inline-grid; place-items: center; width: 32px; height: 32px; border: 1px solid var(--am-border); border-radius: 4px; color: var(--am-text); background: var(--am-surface); }
.cloud-tools button[aria-pressed=true] { background: var(--am-success-surface); outline: 2px solid var(--am-brand-primary); }
.cloud-tools input { width: 80px; }
.cloud-stage { position: relative; min-width: 0; min-height: 0; background: var(--am-surface-soft); }
.cloud-canvas { position: absolute; inset: 0; overflow: hidden; touch-action: none; }
.cloud-message { position: absolute; inset: 0; margin: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 16px; text-align: center; overflow-wrap: anywhere; }
.cloud-status { display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 8px 0; font-size: 12px; overflow-wrap: anywhere; }
.residual-scale { display:inline-block; width:60px; height:8px; border:1px solid var(--am-border); background:linear-gradient(to right,blue,white,red); }
@media(max-width: 640px) { .cloud-viewer { height: 65dvh; } }
</style>
