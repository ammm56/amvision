<template>
  <section class="cloud-viewer" :class="{'show-details':detailsVisible,'evidence-only':presentation==='evidence'}">
    <div v-show="viewportVisible" class="cloud-tools">
      <button :title="t('reset')" :aria-label="t('reset')" :disabled="!scene" @click="scene?.fit()"><RotateCcw :size="18" /></button>
      <button :title="zh?'放大':'Zoom in'" :aria-label="zh?'放大':'Zoom in'" :disabled="!scene" @click="scene?.zoom(true)"><ZoomIn :size="18" /></button>
      <button :title="zh?'缩小':'Zoom out'" :aria-label="zh?'缩小':'Zoom out'" :disabled="!scene" @click="scene?.zoom(false)"><ZoomOut :size="18" /></button>
      <label v-if="focusOptions.length">{{ zh?'定位对象':'Focus object' }}<select v-model="focusTarget"><option v-for="target in focusOptions" :key="target.id" :value="target.id">{{ target.label }}</option></select></label><button v-if="focusOptions.length" :title="zh?'聚焦所选对象':'Focus selected object'" :aria-label="zh?'聚焦所选对象':'Focus selected object'" :disabled="!scene" @click="scene?.focus(focusTarget)"><Focus :size="18" /></button>
      <button v-if="presentation==='full'&&(body.geometry||curves.length||measurements.length||debugItems.length||debugError)" :title="zh?'测量与质量详情':'Measurement and quality details'" :aria-label="zh?'测量与质量详情':'Measurement and quality details'" :aria-pressed="showDetails" @click="showDetails=!showDetails"><List :size="18" /></button>
      <div class="cloud-modes" role="group" :aria-label="zh?'视角操作':'View navigation'"><button :title="zh?'旋转视角':'Rotate view'" :aria-label="zh?'旋转视角':'Rotate view'" :aria-pressed="!pan" :disabled="!scene" @click="pan=false; scene?.pan(false)"><Orbit :size="18" /></button><button :title="t('pan')" :aria-label="t('pan')" :aria-pressed="pan" :disabled="!scene" @click="pan=true; scene?.pan(true)"><Hand :size="18" /></button></div>
      <button v-if="allowPick" :title="zh?'拾取候选位置':'Pick candidate position'" :aria-label="zh?'拾取候选位置':'Pick candidate position'" :aria-pressed="picking" :disabled="!scene" @click="picking=!picking"><Crosshair :size="18" /></button>
      <label>{{ t('projection') }}<select v-model="orthographic" :disabled="!scene" @change="scene?.projection(orthographic)"><option :value="false">{{ t('perspective') }}</option><option :value="true">{{ t('orthographic') }}</option></select></label>
      <label>{{ t('axis') }}<select :value="axis" :disabled="!scene" @change="selectView"><option value="free" disabled>{{ zh?'自由视图':'Free view' }}</option><option value="iso">3D</option><option value="z">{{ zh?'顶视 +Z':'Top +Z' }}</option><option value="-z">{{ zh?'底视 -Z':'Bottom -Z' }}</option><option value="y">{{ zh?'前视 -Y':'Front -Y' }}</option><option value="-y">{{ zh?'后视 +Y':'Back +Y' }}</option><option value="x">{{ zh?'右视 +X':'Right +X' }}</option><option value="-x">{{ zh?'左视 -X':'Left -X' }}</option></select></label>
      <label>{{ t('size') }}<input v-model.number="size" :disabled="!scene" type="range" min="1" max="8" step="1" @input="scene?.pointSize(size)"></label>
      <label>{{ zh?'着色':'Coloring' }}<select v-model="colorMode" :disabled="!scene"><option value="original">{{ zh?'原色':'Source colors' }}</option><option value="coordinate-z" :disabled="!sourceRange">{{ zh?'坐标 Z':'Coordinate Z' }}</option><option value="support" :disabled="!selectedPlane">{{ zh?'支持 / 剔除':'Support / rejected' }}</option><option value="residual" :disabled="!selectedPlane">{{ zh?'有符号残差':'Signed residual' }}</option></select></label>
      <template v-if="colorMode==='coordinate-z'"><label>{{ zh?'色标下限':'Scale minimum' }}<input v-model.number="rangeMin" class="color-bound" type="number" step="any" :aria-invalid="!validRange" @change="applyRange"></label><label>{{ zh?'色标上限':'Scale maximum' }}<input v-model.number="rangeMax" class="color-bound" type="number" step="any" :aria-invalid="!validRange" @change="applyRange"></label><button :title="zh?'重置色标范围':'Reset color range'" :aria-label="zh?'重置色标范围':'Reset color range'" @click="resetRange"><RefreshCw :size="16" /></button><span v-if="!validRange" role="alert">{{ zh?'色标需为有限数值，下限不大于上限':'Use finite bounds, minimum no greater than maximum' }}</span></template>
      <label v-if="planes.length">{{ zh?'平面':'Plane' }}<select v-model="selectedPlane"><option value="">{{ zh?'未选择':'None' }}</option><option v-for="plane in planes" :key="String(plane.feature_id)" :value="String(plane.feature_id)">{{ plane.feature_id }}</option></select></label>
      <label><input v-model="showEvidence" type="checkbox" :disabled="!scene" @change="scene?.evidenceVisibility(showEvidence)">{{ zh?'测量叠加':'Measurement overlays' }}</label>
      <label><input v-model="showAxes" type="checkbox" :disabled="!scene" @change="scene?.axesVisible(showAxes)">{{ zh?'坐标轴':'Axes' }}</label>
      <label v-if="activeCurve?.fit_weights">{{ zh?'拟圆证据颜色':'Circle evidence colors' }}<select v-model="curveColorMode"><option value="support">{{ zh?'支持分类':'Support classes' }}</option><option value="weight">{{ zh?'拟合权重':'Fit weights' }}</option><option value="residual">{{ zh?'径向残差':'Radial residuals' }}</option></select></label>
      <template v-if="editRois?.length"><button :title="zh?'移动 ROI':'Move ROI'" :aria-label="zh?'移动 ROI':'Move ROI'" :aria-pressed="editMode==='translate'" :disabled="!scene||!selectedRoiVisible" @click="editMode='translate'"><Move3D :size="18" /></button><button :title="zh?'旋转 ROI':'Rotate ROI'" :aria-label="zh?'旋转 ROI':'Rotate ROI'" :aria-pressed="editMode==='rotate'" :disabled="!scene||!selectedRoiVisible" @click="editMode='rotate'"><Rotate3D :size="18" /></button></template>
      <button v-if="scalableRoi" :title="zh?'调整 ROI 尺寸':'Resize ROI'" :aria-label="zh?'调整 ROI 尺寸':'Resize ROI'" :aria-pressed="editMode==='scale'" :disabled="!scene||!selectedRoiVisible" @click="editMode='scale'"><Scaling :size="18" /></button>
    </div>
    <div v-show="viewportVisible" class="cloud-stage">
      <div ref="host" class="cloud-canvas" />
      <div v-if="scene&&colorMode==='coordinate-z'&&appliedRange" class="cloud-color-scale" :aria-label="zh?'坐标 Z 色标':'Coordinate Z scale'"><strong>{{ zh?'坐标 Z':'Coordinate Z' }} · {{ unit }}</strong><div><i aria-hidden="true"/><ol><li v-for="tick in colorTicks" :key="tick.index">{{ displayNumber(tick.value) }}</li></ol></div></div>
      <div v-if="scene&&viewScale" class="cloud-scale-bar" :style="{width:`${viewScale.pixels}px`}" :aria-label="zh?'空间比例尺':'Spatial scale'"><span>{{ displayNumber(viewScale.value) }} {{ unit }}</span></div>
      <p v-if="loading" role="status" class="cloud-message">{{ t('loading') }}</p>
      <div v-else-if="error" role="alert" class="cloud-message"><p>{{ t(error) }}</p><button :title="t('retry')" @click="load"><RefreshCw :size="18" /></button></div>
      <p v-else-if="body.state !== 'ready'" class="cloud-message">{{ body.state === 'empty' ? t('empty') : String(body.reason || t('unavailable')) }}</p>
    </div>
    <div class="cloud-status">
      <span>{{ unit }} · {{ frame }} · {{ zh?'显示':'Displayed' }} {{ body.display_point_count ?? '-' }} / {{ zh?'输入':'Input' }} {{ body.point_count ?? '-' }}<template v-if="body.source_point_count!==body.point_count"> · {{ zh?'原始':'Source' }} {{ body.source_point_count ?? '-' }}</template></span>
      <span v-if="color.mode === 'scalar'">{{ color.field }}: {{ color.min ?? '-' }} .. {{ color.max ?? '-' }}</span>
      <span v-if="picked">{{ picked.sourceIndex === null ? (zh ? '生成顶点' : 'Generated vertex') : (zh ? '原始行' : 'Source row') }} #{{ picked.sourceIndex ?? picked.vertexIndex }} · XYZ {{ picked.xyz.join(', ') }}<template v-if="picked.scalar !== null"> · {{ picked.scalar }}</template></span>
      <span v-if="colorMode==='support'&&colorSummary">{{ zh?'显示点':'Display points' }} · {{ zh?'支持':'Support' }} {{ colorSummary.support }} · {{ zh?'剔除':'Rejected' }} {{ colorSummary.rejected }} · {{ zh?'无关':'Unrelated' }} {{ colorSummary.unrelated }}</span>
      <span v-if="colorMode==='residual'&&colorSummary">{{ zh?'残差色标':'Residual scale' }} <template v-if="colorSummary.extent!==null"><i class="residual-scale" aria-hidden="true"/> {{ -colorSummary.extent }} .. {{ colorSummary.extent }} {{ unit }}</template><template v-else>{{ zh?'无显示支持点':'No displayed support points' }}</template></span>
      <span v-if="curveScale">{{ zh?'拟圆证据色标':'Circle evidence scale' }} <i class="residual-scale" aria-hidden="true" /> {{ curveScale.min }} .. {{ curveScale.max }} {{ curveColorMode==='residual'?unit:'1' }}</span>
    </div>
    <div v-if="presentation==='evidence'&&(loading||error||!evidenceTabs.length)" class="evidence-message" :role="error?'alert':'status'"><p>{{ loading?t('loading'):error?t(error):zh?'本次显示没有测量证据':'No measurement evidence in this display' }}</p><button v-if="error" :title="t('retry')" :aria-label="t('retry')" @click="load"><RefreshCw :size="18" /></button></div>
    <div v-if="detailsVisible&&evidenceTabs.length" class="evidence-tabs" role="tablist" :aria-label="zh?'三维证据':'3D evidence'"><button v-for="tab in evidenceTabs" :id="`${viewerId}-${tab.id}`" :key="tab.id" role="tab" :aria-selected="detailTab===tab.id" :tabindex="detailTab===tab.id?0:-1" :aria-controls="`${viewerId}-panel`" @click="detailTab=tab.id" @keydown="navigateTab($event,evidenceTabs.map(t=>t.id),detailTab,value=>detailTab=value)">{{ tab.label }}</button></div>
    <div v-if="detailsVisible&&evidenceTabs.length" :id="`${viewerId}-panel`" class="evidence-panel" role="tabpanel" :aria-labelledby="`${viewerId}-${detailTab}`">
      <div v-if="detailTab==='rois'" class="roi-display-list"><div v-for="roi in displayRois" :key="String(roi.roi_id)"><span>{{ roi.roi_id }}</span><RoiVisibilityButton :roi-id="String(roi.roi_id)" :state="readOnlyVisibility.state(String(roi.roi_id))" :disabled="!scene" @toggle="readOnlyVisibility.toggle(String(roi.roi_id))" /></div></div>
      <GeometrySummary v-if="detailTab==='geometry'&&body.geometry" :geometry="displayObject(body.geometry)" :selected="selectedPlane" @select-plane="selectedPlane=$event" />
      <BoundarySummary v-if="detailTab==='features'&&curves.length" :items="curves" :selected="selectedCurve" :selected-segment="selectedSegment" :selected-index="selectedCurvePoint" @select="selectCurve" @select-point="selectedCurvePoint=$event" />
      <MeasurementSummary v-if="detailTab==='measurements'&&measurements.length" :items="measurements" :unit="String(unit)" :selected="selectedMeasurement" @select="selectMeasurement" />
      <BoundaryDebugSummary v-if="detailTab==='debug'" :items="debugItems" :selected-id="selectedDebug" :layers="debugLayers" :selection="debugSelection" :error="debugError" @select="selectDebug" @layers="debugLayers=$event" @pick="selectDebugPoint" />
    </div>
  </section>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, shallowRef, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Hand, RefreshCw, RotateCcw, Move3D, Rotate3D, Crosshair, ZoomIn, ZoomOut, Orbit, List, Focus, Scaling } from '@lucide/vue'
import { readCloudCapabilities } from '../services/measurement-resource.service'
import { decodeCloudPreview, type CloudDisplayData } from './preview-data'
import { createCloudRenderer, type CloudViewState } from './renderer'
import GeometrySummary from './GeometrySummary.vue'
import MeasurementSummary from './MeasurementSummary.vue'
import BoundarySummary from './BoundarySummary.vue'
import BoundaryDebugSummary from './BoundaryDebugSummary.vue'
import {decodeBoundaryDebug,type DebugEvidence,type DebugLayers,type DebugSelection} from './boundary-debug'
import {curveItems,type CurveDisplay} from './boundary-display'
import {measurementItems,type MeasurementDisplay} from './measurement-display'
import {curveColorScale,type CurveColorMode} from './curve-colors'
import {planeColorData,planeColorSummary} from './plane-colors'
import type {RoiValue,GeometryFocus} from './geometry-overlay'
import type {ArcEdit,ArcValues} from './arc-edit'
import {roiVisibility,useRoiVisibility} from './roi-visibility'
import RoiVisibilityButton from './RoiVisibilityButton.vue'
import {navigateTab} from './tab-navigation'
import {coordinateRange,displayNumber,type CloudColorMode,type CoordinateRange, type scaleBar} from './view-presentation'

const props = withDefaults(defineProps<{ payload: Record<string, unknown>; projectId: string; editRois?:RoiValue[]; selectedRoiId?:string; allowPick?:boolean; candidate?:number[];editArc?:ArcEdit;hiddenRoiIds?:ReadonlySet<string>;roiScope?:string;presentation?:'full'|'view'|'evidence'|'hidden' }>(),{presentation:'full'})
const viewerId=useId(),viewportVisible=computed(()=>props.presentation==='full'||props.presentation==='view')
const emit=defineEmits<{'roi-change':[value:RoiValue];candidate:[value:{payload:Record<string,unknown>;xyz:number[]}];'feature-selection':[value:{payload:Record<string,unknown>;featureId:string;segmentId:string}];'arc-change':[value:{payload:Record<string,unknown>;key:string;values:ArcValues}]}>()
const { t,locale } = useI18n({ useScope: 'local', messages: {
  'zh-CN': { reset: '复位视角', pan: '平移', projection: '投影', perspective: '透视', orthographic: '正交', axis: '视图', size: '点大小', loading: '正在读取显示数据', retry: '重新打开', empty: '无有效显示点', unavailable: '显示不可用', unknown: '单位未确认', cloud_renderer_unconfigured: '三维显示预算尚未配置', cloud_preview_invalid: '显示数据格式无效', cloud_preview_capacity: '显示数据超过点数或字节限额', cloud_preview_checksum: '显示数据摘要不一致', cloud_cpu_capacity: '浏览器内存预算不足', cloud_gpu_capacity: '渲染缓冲预算不足', cloud_canvas_capacity: '视口超过像素预算', cloud_position_precision: '局部坐标显示误差超过配置限额', cloud_context_lost: 'WebGL 上下文已丢失' },
  'en-US': { reset: 'Reset view', pan: 'Pan', projection: 'Projection', perspective: 'Perspective', orthographic: 'Orthographic', axis: 'View', size: 'Point size', loading: 'Loading display data', retry: 'Reopen', empty: 'No valid display points', unavailable: 'Display unavailable', unknown: 'Unit unconfirmed', cloud_renderer_unconfigured: '3D display budget is not configured', cloud_preview_invalid: 'Invalid display data', cloud_preview_capacity: 'Display point or byte limit exceeded', cloud_preview_checksum: 'Display checksum mismatch', cloud_cpu_capacity: 'Browser memory budget exceeded', cloud_gpu_capacity: 'Rendering buffer budget exceeded', cloud_canvas_capacity: 'Viewport pixel budget exceeded', cloud_position_precision: 'Local coordinate display error exceeds the configured limit', cloud_context_lost: 'WebGL context lost' },
} })
const host = ref<HTMLElement>(), scene = shallowRef<ReturnType<typeof createCloudRenderer> | null>(null)
const zh=computed(()=>locale.value==='zh-CN'),editMode=ref<'translate'|'rotate'|'scale'>('translate')
const displayRois=computed(()=>{const raw=displayObject(props.payload.geometry).rois;return props.editRois??(Array.isArray(raw)?raw.map(displayObject):[])})
const readOnlyVisibility=useRoiVisibility(displayRois,()=>[props.payload,props.projectId])
const hiddenRois=computed(()=>props.hiddenRoiIds??readOnlyVisibility.hidden.value)
const selectedRoiVisible=computed(()=>['visible','partial'].includes(roiVisibility(displayRois.value,props.selectedRoiId??'',hiddenRois.value)))
let editGeneration=0
watch(()=>[props.roiScope,props.selectedRoiId],()=>{editGeneration++},{flush:'sync'})
function updateGeometry(){
  const token=generation,editToken=editGeneration,payload=props.payload,live=()=>token===generation&&payload===props.payload
  scene.value?.geometry({
    payload,rois:props.editRois,selectedId:props.selectedRoiId,mode:editMode.value,arc:props.editArc,hiddenRoiIds:hiddenRois.value,roiScope:props.roiScope,
    arcChanged:(key,values)=>{if(live()&&key===props.editArc?.key)emit('arc-change',{payload,key,values})},
    changed:props.editRois?roi=>{if(live()&&editToken===editGeneration&&props.editRois?.some(r=>r.roi_id===roi.roi_id))emit('roi-change',roi)}:undefined,
    selectedMeasurement:selectedMeasurement.value,selectedPlane:selectedPlane.value,candidate:props.candidate,
    selectedCurve:selectedCurve.value,selectedSegment:selectedSegment.value,curveColorMode:curveColorMode.value,selectedCurvePoint:selectedCurvePoint.value,
    curveSelected:picking.value?undefined:(id,segment)=>{if(live())selectCurve(id,segment)},
    curvePointSelected:picking.value?undefined:(id,segment,index)=>{if(live()){selectCurve(id,segment);selectedCurvePoint.value=index}},
    measurementSelected:picking.value?undefined:id=>{if(live()){selectMeasurement(id);showDetails.value=true;detailTab.value='measurements'}},
    debug:activeDebug.value,debugLayers:debugLayers.value,debugSelection:debugSelection.value,
    debugSelected:picking.value?undefined:selection=>{if(live())selectDebugPoint(selection)},
    debugFailed:failure=>{if(live())debugError.value=failure.message},
  })
}
function selectDebug(id:string){selectedDebug.value=id;debugSelection.value=null;debugError.value='';focusTarget.value='debug'}
function selectDebugPoint(selection:DebugSelection){debugSelection.value=selection;showDetails.value=true;detailTab.value='debug';focusTarget.value='debug'}
function selectCurve(id:string,segment:string){selectedCurvePoint.value=null;selectedCurve.value=id;selectedSegment.value=segment;focusTarget.value='feature';showDetails.value=true;detailTab.value='features';emit('feature-selection',{payload:props.payload,featureId:id,segmentId:segment})}
function selectMeasurement(id:string){selectedMeasurement.value=id;focusTarget.value='measurement'}
function updateColors(){try{const samples=['support','residual'].includes(colorMode.value)?planeColorData(props.payload,selectedPlane.value):null;colorSummary.value=planeColorSummary(samples);scene.value?.colors(samples,colorMode.value,appliedRange.value)}catch(failure){release();error.value=failure instanceof Error?failure.message:'unavailable'}}
function displayObject(value: unknown): Record<string, unknown> { return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {} }
const body = computed(() => props.payload), color = computed(() => displayObject(body.value.color))
const unit = computed(() => displayObject(body.value.spatial).length_unit || t('unknown'))
const frame = computed(() => displayObject(body.value.spatial).frame_id)
const loading = ref(false), error = ref(''), pan = ref(false), orthographic = ref(true), size = ref(2)
const axis = ref<CloudViewState>('z')
const sourceRange=computed(()=>coordinateRange(body.value)),rangeMin=ref<number|string>(0),rangeMax=ref<number|string>(0),appliedRange=ref<CoordinateRange|null>(null)
const validRange=computed(()=>typeof rangeMin.value==='number'&&typeof rangeMax.value==='number'&&Number.isFinite(rangeMin.value)&&Number.isFinite(rangeMax.value)&&rangeMin.value<=rangeMax.value)
const colorTicks=computed(()=>appliedRange.value?Array.from({length:5},(_,index)=>({index,value:appliedRange.value!.max-(appliedRange.value!.max-appliedRange.value!.min)*index/4})):[])
const viewScale=ref<ReturnType<typeof scaleBar>>(null),showEvidence=ref(true),showAxes=ref(false)
function applyRange(){if(validRange.value){appliedRange.value={min:Number(rangeMin.value),max:Number(rangeMax.value)};updateColors()}}
function resetRange(){const range=sourceRange.value;if(range){rangeMin.value=range.min;rangeMax.value=range.max;appliedRange.value={...range};updateColors()}}
function selectView(event: Event) {
  const selected = (event.target as HTMLSelectElement).value as CloudViewState
  if (selected !== 'free') scene.value?.fit(selected)
}
const showDetails=ref(false)
const detailsVisible=computed(()=>props.presentation==='evidence'||props.presentation==='full'&&showDetails.value)
const detailTab=ref('measurements')
const evidenceTabs=computed(()=>[...(!props.editRois&&displayRois.value.length?[{id:'rois',label:zh.value?'ROI 显示':'ROI visibility'}]:[]),...(measurements.value.length?[{id:'measurements',label:zh.value?'测量':'Measurements'}]:[]),...(curves.value.length?[{id:'features',label:zh.value?'边界 / 拟合':'Boundary / fit'}]:[]),...(planes.value.length||displayObject(body.value.geometry).frame?[{id:'geometry',label:zh.value?'基准 / 质量':'Datum / quality'}]:[]),...(debugItems.value.length||debugError.value?[{id:'debug',label:zh.value?'提取调试':'Extraction debug'}]:[])])
const debugItems=shallowRef<DebugEvidence[]>([]),selectedDebug=ref(''),debugError=ref(''),debugSelection=ref<DebugSelection|null>(null)
const debugLayers=ref<DebugLayers>({grid:true,profiles:true,candidates:true,partition:false})
const activeDebug=computed(()=>debugItems.value.find(d=>d.id===selectedDebug.value))
const picked = ref<ReturnType<CloudDisplayData['point']> | null>(null)
const picking=ref(false),measurements=ref<MeasurementDisplay[]>([]),selectedMeasurement=ref('')
const selectedPlane=ref(''),colorMode=ref<CloudColorMode>('original')
const colorSummary=ref<ReturnType<typeof planeColorSummary>>(null)
const planes=computed(()=>{const raw=displayObject(body.value.geometry).planes;return Array.isArray(raw)?raw.map(displayObject):[]})
const curves=ref<CurveDisplay[]>([]),selectedCurve=ref(''),selectedSegment=ref('')
const selectedCurvePoint=ref<number|null>(null)
watch(()=>[selectedCurve.value,props.payload],()=>{selectedCurvePoint.value=null},{flush:'sync'})
const curveColorMode=ref<CurveColorMode>('support')
const activeCurve=computed(()=>curves.value.find(c=>c.feature_id===selectedCurve.value))
const curveScale=computed(()=>activeCurve.value?curveColorScale(activeCurve.value,curveColorMode.value):null)
const focusTarget=ref<GeometryFocus>('measurement')
const focusOptions=computed<{id:GeometryFocus;label:string}[]>(()=>[...(activeDebug.value?[{id:'debug' as const,label:zh.value?'提取调试':'Extraction debug'}]:[]),...(props.editArc?[{id:'arc' as const,label:zh.value?'当前角域':'Current angular region'}]:[]),...(props.selectedRoiId&&selectedRoiVisible.value?[{id:'roi' as const,label:`ROI · ${props.selectedRoiId}`}]:[]),...(selectedMeasurement.value?[{id:'measurement' as const,label:selectedMeasurement.value}]:[]),...(selectedCurve.value?[{id:'feature' as const,label:`${selectedCurve.value} ${selectedSegment.value}`}]:[]),...(selectedPlane.value?[{id:'plane' as const,label:selectedPlane.value}]:[])])
const scalableRoi=computed(()=>props.editRois?.some(r=>r.roi_id===props.selectedRoiId&&['box','cylinder'].includes(String(r.kind))))
watch(scalableRoi,canScale=>{if(!canScale&&editMode.value==='scale')editMode.value='translate'})
watch(focusOptions,targets=>{if(!targets.some(t=>t.id===focusTarget.value))focusTarget.value=targets[0]?.id??'measurement'})
watch(evidenceTabs,tabs=>{if(!tabs.some(tab=>tab.id===detailTab.value))detailTab.value=tabs[0]?.id??''})
let generation = 0, controller: AbortController | null = null, data: CloudDisplayData | null = null, scenePayload:Record<string,unknown>|null=null
function releaseDebug(){for(const record of debugItems.value)record.dispose();debugItems.value=[];selectedDebug.value='';debugSelection.value=null;debugError.value=''}
function release() { generation++; controller?.abort(); controller = null; scene.value?.dispose(); scene.value = null; data?.dispose(); data = null;releaseDebug(); picked.value = null;picking.value=false;measurements.value=[];selectedMeasurement.value='';selectedPlane.value='';colorMode.value='original';colorSummary.value=null;curves.value=[];selectedCurve.value='';selectedSegment.value='';curveColorMode.value='support' }
async function load() {
  release(); const token = generation; controller = new AbortController(); const signal = controller.signal
  error.value = ''; loading.value = true; pan.value = false; orthographic.value = true; size.value = 2; axis.value = 'z'; viewScale.value=null;showEvidence.value=true;showAxes.value=false
  appliedRange.value=sourceRange.value?{...sourceRange.value}:null;rangeMin.value=sourceRange.value?.min??0;rangeMax.value=sourceRange.value?.max??0
  colorMode.value=color.value.mode==='solid'&&sourceRange.value?'coordinate-z':'original'
  try {
    if(props.presentation==='hidden')return
    measurements.value=measurementItems(body.value)
    curves.value=curveItems(body.value)
    selectedMeasurement.value=measurements.value[0]?.item_id??''
    if (body.value.state !== 'ready') return
    const policy = (await readCloudCapabilities(props.projectId, signal)).renderer
    if (signal.aborted || token !== generation) return
    if (!policy) throw new Error('cloud_renderer_unconfigured')
    const decoded = await decodeCloudPreview(body.value, policy, signal)
    if (signal.aborted || token !== generation || !host.value) { decoded.dispose(); return }
    data = decoded
    try{
      const evidence=await decodeBoundaryDebug(body.value,policy,signal)
      if(signal.aborted||token!==generation||!host.value){for(const record of evidence)record.dispose();return}
      debugItems.value=evidence;selectedDebug.value=evidence[0]?.id??''
    }catch(failure){if(signal.aborted||token!==generation)return;debugError.value=failure instanceof Error?failure.message:'cloud_debug_invalid'}
    const payload=props.payload
    scene.value = createCloudRenderer(host.value, data, policy, index => {
      if(token!==generation||signal.aborted||props.payload!==payload)return
      picked.value = decoded.point(index)
      if(props.allowPick&&picking.value)emit('candidate',{payload,xyz:[...picked.value.xyz]})
    }, failure => {
      if(token!==generation||signal.aborted||props.payload!==payload)return
      release(); error.value = failure.message; loading.value = false
    }, view => {
      if(token!==generation||signal.aborted||props.payload!==payload)return
      axis.value = view
    },viewportVisible.value,{range:appliedRange.value,coordinateColor:colorMode.value==='coordinate-z',scaleChanged:scale=>{if(token===generation&&!signal.aborted&&props.payload===payload)viewScale.value=scale}})
    scenePayload=payload
    updateGeometry()
  } catch (failure) {
    if (token === generation && !signal.aborted) { scene.value?.dispose(); scene.value = null; data?.dispose(); data = null;releaseDebug(); error.value = failure instanceof Error ? failure.message : 'unavailable' }
  } finally { if (token === generation) loading.value = false }
}
onMounted(load)
watch(() => [props.payload, props.projectId], load)
watch(()=>[props.roiScope,props.editRois,props.selectedRoiId,props.editArc,editMode.value,selectedMeasurement.value,selectedPlane.value,props.candidate,selectedCurve.value,selectedSegment.value,curveColorMode.value,picking.value,selectedDebug.value,debugLayers.value,debugSelection.value,selectedCurvePoint.value],updateGeometry,{deep:true})
watch(()=>[selectedPlane.value,colorMode.value],updateColors)
watch(()=>props.allowPick,()=>{picking.value=false})
watch(hiddenRois,hidden=>{if(scenePayload===props.payload)scene.value?.roiVisibility(hidden)})
watch(viewportVisible,visible=>{if(!visible)scene.value?.activity(false)},{flush:'sync'})
watch(()=>props.presentation,async()=>{
  const token=generation
  await nextTick()
  if(token!==generation)return
  if(scene.value)scene.value.activity(viewportVisible.value)
  else if(!loading.value&&!error.value&&props.presentation!=='hidden')void load()
})
onBeforeUnmount(release)
</script>
<style scoped>
.cloud-viewer { display: grid; grid-template-rows: auto minmax(180px, 1fr) auto; grid-auto-rows:auto; width: 100%; height: min(72dvh, 720px); min-width: 0; }
.cloud-viewer.show-details { grid-template-rows:auto minmax(180px,1fr) auto auto minmax(100px,.65fr); }
.evidence-tabs{display:flex;flex-wrap:wrap;gap:4px;border-bottom:1px solid var(--am-border)}.evidence-tabs button{font:inherit;font-size:12px;padding:6px 10px;border:0;background:transparent;color:var(--am-text);cursor:pointer}.evidence-tabs button[aria-selected=true]{box-shadow:inset 0 -2px var(--am-brand-primary);font-weight:600}.evidence-tabs button:focus-visible{outline:2px solid var(--am-brand-primary);outline-offset:-2px}.evidence-panel{min-width:0;min-height:0;overflow:auto}.evidence-panel :deep(.measurement-summary),.evidence-panel :deep(.boundary-summary),.evidence-panel :deep(.geometry-summary){max-height:none;overflow:visible}
.cloud-viewer.evidence-only{grid-template-rows:auto auto minmax(0,1fr)}
.cloud-tools { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; padding: 8px 0; }
.cloud-tools label { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.cloud-modes { display:flex;gap:2px; }
.cloud-tools button, .cloud-message button, .evidence-message button { display: inline-grid; place-items: center; width: 32px; height: 32px; border: 1px solid var(--am-border); border-radius: 4px; color: var(--am-text); background: var(--am-surface); }
.evidence-message{display:flex;align-items:center;gap:8px;overflow-wrap:anywhere;min-width:0}.evidence-message p{margin:0}
.cloud-tools button[aria-pressed=true] { background: var(--am-surface-soft); outline: 2px solid var(--am-brand-primary); }
.cloud-tools select {max-width:min(100%,240px);min-width:0;min-height:28px;border:1px solid var(--am-border);border-radius:4px;padding:3px 6px;color:var(--am-text);background:var(--am-surface);font:inherit}
.cloud-tools label {min-width:0;max-width:100%}
.cloud-tools input { width: 80px; }
.cloud-tools input[type=checkbox]{appearance:auto;flex:0 0 16px;width:16px;height:16px;padding:0;margin:0;accent-color:var(--am-brand-primary)}
.cloud-tools .color-bound{width:94px;min-height:28px;font:inherit;font-variant-numeric:tabular-nums;border:1px solid var(--am-border);border-radius:4px;padding:3px 6px;color:var(--am-text);background:var(--am-surface)}
.cloud-tools input[aria-invalid=true]{outline:1px solid var(--am-danger,#d74444)}
.cloud-stage { position: relative; min-width: 0; min-height: 0; background: #202326; }
.cloud-color-scale{position:absolute;right:12px;top:16px;color:#fff;font-size:11px;pointer-events:none;font-variant-numeric:tabular-nums;text-shadow:0 1px 2px #000}
.cloud-color-scale strong{display:block;font-size:11px;font-weight:500;margin-bottom:8px}.cloud-color-scale>div{display:flex;gap:6px;height:150px}.cloud-color-scale i{width:12px;border:1px solid #d8d8d8;background:linear-gradient(to top,#00f,#0ff,#0f0,#ff0,#f00)}.cloud-color-scale ol{display:flex;flex-direction:column;justify-content:space-between;list-style:none;padding:0;margin:0}
.cloud-scale-bar{position:absolute;bottom:24px;left:18px;border:solid #fff;border-width:0 1px 1px;height:6px;pointer-events:none;color:#fff;text-shadow:0 1px 2px #000;text-align:center;font-size:11px;white-space:nowrap}.cloud-scale-bar span{position:absolute;top:8px;left:50%;transform:translateX(-50%)}
.cloud-canvas { position: absolute; inset: 0; overflow: hidden; touch-action: none; }
.cloud-message { position: absolute; inset: 0; margin: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; padding: 16px; text-align: center; overflow-wrap: anywhere; }
.cloud-status { display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 8px 0; font-size: 12px; overflow-wrap: anywhere; }
.residual-scale { display:inline-block; width:60px; height:8px; border:1px solid var(--am-border); background:linear-gradient(to right,blue,white,red); }
.roi-display-list{display:grid;gap:4px;padding:8px 0}.roi-display-list>div{display:flex;align-items:center;justify-content:space-between;gap:12px;min-width:0}.roi-display-list span{overflow-wrap:anywhere;min-width:0;font-size:12px}
@media(max-width: 640px) { .cloud-viewer { height: 65dvh; } }
@container(min-width:1200px){.cloud-viewer.show-details:not(.evidence-only){grid-template-columns:minmax(0,1fr) 480px;grid-template-rows:auto auto minmax(0,1fr) auto;column-gap:12px}.cloud-viewer.show-details:not(.evidence-only) .cloud-tools{grid-column:1/-1;grid-row:1}.cloud-viewer.show-details:not(.evidence-only) .cloud-stage{grid-column:1;grid-row:2/4}.cloud-viewer.show-details:not(.evidence-only) .cloud-status{grid-column:1/-1;grid-row:4}.cloud-viewer.show-details:not(.evidence-only) .evidence-tabs{grid-column:2;grid-row:2}.cloud-viewer.show-details:not(.evidence-only) .evidence-panel{grid-column:2;grid-row:3}}
</style>
