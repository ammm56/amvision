<template>
  <button type="button" class="pin-edit" :disabled="disabled" @click="show">{{ count ? `${count} PIN` : t('unconfigured') }} <span>{{ t('edit') }}</span></button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="pin-layout-dialog" :title="t('title')" :confirm-label="t('apply')" :cancel-label="t('cancel')" confirm-variant="primary" size="wide" scroll-body
      :confirm-disabled="!valid || disabled" @confirm="apply" @cancel="close">
      <div class="pin-workspace">
        <p v-if="error" role="alert" class="pin-error">{{ error }}</p>
        <p v-if="referenceIssues.length" role="status" class="pin-error">{{ referenceIssues.join('; ') }}</p>
        <div class="pin-tabs" role="group" :aria-label="t('title')"><Button v-for="entry in views" :key="entry.value" :variant="view===entry.value?'primary':'secondary'" :aria-pressed="view===entry.value" @click="view=entry.value">{{ entry.label }}</Button></div>
        <label>{{ t('reference') }}<WorkflowMeasurementResourcePicker :model-value="reference" :schema="{ 'x-resource-kind': 'localization-template' }" @update:model-value="chooseReference" /></label>
        <p v-if="referenceChanged" role="status">{{ viewText.referenceChanged }}</p>
        <div class="pin-main">
          <div class="pin-image-panel">
            <div v-if="imageUrl" class="pin-map">
              <img :src="imageUrl" :alt="t('reference')">
              <svg :viewBox="`0 0 ${resource?.content.template?.image_width || 1} ${resource?.content.template?.image_height || 1}`" role="group" :aria-label="t('title')">
                <polygon v-for="zone in scanOverlays" :key="zone.id" class="pin-scan-zone" :points="zone.pointsXy.map(point=>point.join(',')).join(' ')" />
                <g v-for="(pin,index) in draft.pins" :key="index" role="button" tabindex="0" :aria-label="pin.pin_id" :aria-pressed="selectedPin===index" :class="{active:selectedPin===index,empty:!pin.expected_present}" @click="selectedPin=index" @keydown.enter.prevent="selectedPin=index" @keydown.space.prevent="selectedPin=index">
                  <circle :cx="pin.center[0]" :cy="pin.center[1]" r="16"/><text :x="pin.center[0]" :y="pin.center[1]-24" text-anchor="middle">{{ pin.pin_id }}</text>
                </g>
              </svg>
            </div>
            <Button v-if="imageUrl" variant="secondary" @click="viewerOpen=true">{{ t('mark') }} {{ active?.pin_id }}</Button>
            <p v-else role="status">{{ referenceLoading ? viewText.loading : t('selectImage') }}</p>
            <p>{{ t('hint') }}</p>
            <details><summary>{{ viewText.details }}</summary><label>Reference ID<input v-model="draft.reference_id"></label><output>{{ draft.pins.length }} PIN</output></details>
          </div>
          <div class="pin-controls">
          <template v-if="view==='layout'">
          <div ref="pinTable" class="pin-table-wrap">
            <table class="pin-table"><thead><tr><th>PIN ID</th><th>Row</th><th>Type</th><th>X</th><th>Y</th><th>{{ t('present') }}</th><th></th></tr></thead>
              <tbody><tr v-for="{pin,index} in pagePins" :key="index" :class="{ selected: selectedPin === index }" @click="selectedPin = index" @focusin="selectedPin=index">
                <td><input v-model="pin.pin_id" :aria-label="`PIN ID ${index + 1}`"></td><td><input v-model="pin.row_id" :aria-label="`Row ${index + 1}`"></td>
                <td><SelectField v-model="pin.pin_type" :options="typeOptions" :aria-label="`Type ${index + 1}`" /></td>
                <td><input v-model.number="pin.center[0]" type="number" step=".1" :aria-label="`X ${index + 1}`"></td><td><input v-model.number="pin.center[1]" type="number" step=".1" :aria-label="`Y ${index + 1}`"></td>
                <td><input v-model="pin.expected_present" type="checkbox" :aria-label="`${t('present')} ${index + 1}`"></td>
                <td><button type="button" :aria-label="`${t('remove')} ${index + 1}`" @click.stop="draft.pins.splice(index, 1)">×</button></td>
              </tr></tbody></table>
          </div>
          <PaginationControls v-if="draft.pins.length>100" :offset="offset" :limit="100" :item-count="pagePins.length" :total-count="draft.pins.length" @previous="offset-=100" @next="offset+=100" />
        <div class="pin-grid">
          <label v-for="field in arrayFields" :key="field.key">{{ field.label }}<input v-model.number="array[field.key]" :aria-label="field.label" type="number" :step="field.integer ? 1 : 'any'"></label>
        </div>
        <Button variant="secondary" :disabled="!draft.types.length" @click="generate">{{ t('generate') }}</Button>
        <p v-if="irregular" role="status">{{ arrayText.irregular }}</p>
        <div v-if="pendingPins" class="pin-sampling" role="status">
          <p>{{ arrayText.preview }}: {{ draft.pins.length }} → {{ pendingPins.length }} PIN · {{ arrayText.empty }} {{ pendingPins.filter(p=>!p.expected_present).length }} · {{ arrayText.endpoints }} {{ pendingPins.reduce((n,p)=>n+(p.endpoint_pairs?.length ?? 0),0) }}</p>
          <p>{{ arrayText.preserve }}</p>
          <p v-if="removedPins.length" class="pin-error">{{ arrayText.removed }}: {{ removedPins.join(', ') }}</p>
          <Button variant="secondary" @click="acceptArray">{{ arrayText.replace }}</Button>
          <Button variant="secondary" @click="pendingPins=null">{{ t('cancel') }}</Button>
        </div>
        <Button v-if="previousArray" variant="secondary" @click="restoreArray">{{ arrayText.restore }}</Button>
        </template>
        <template v-if="view==='diagnostic'">
        <label>{{ diagnosticText.select }}<SelectField :model-value="draft.diagnostic_pin_id ?? null" :options="[{label:diagnosticText.none,value:null}, ...draft.pins.map(p=>({label:p.pin_id,value:p.pin_id}))]" @update:model-value="draft.diagnostic_pin_id = $event === null ? null : String($event)" /></label>
        <p>{{ diagnosticText.help }}</p>
        <template v-if="diagnosticDisplay">
          <WorkflowSamplingDiagnostic v-if="diagnosticCurrent" :diagnostic="diagnosticDisplay.payload.sampling_diagnostic as Record<string,unknown>" />
          <p v-else role="status">{{ diagnosticText.stale }}</p>
        </template>
        </template>
        <template v-if="view==='sampling'">
        <label>{{ viewText.samplingType }}<SelectField v-model="selectedType" :options="typeOptions" /></label>
        <section v-for="{type,index} in samplingEntries" :key="index" class="pin-sampling">
          <div class="pin-grid"><label>Type ID<input v-model="type.type_id"></label><label>Polarity<SelectField v-model="type.polarity" :options="[{label: 'Bright', value: 'bright'}, {label: 'Dark', value: 'dark'}]" /></label><Button variant="secondary" :disabled="draft.types.length === 1" @click="draft.types.splice(index, 1)">{{ t('remove') }}</Button></div>
          <div class="pin-grid"><label v-for="field in samplingFields" :key="field.key">{{ field.label }}<input v-model.number="type[field.key]" type="number" :step="field.integer ? 1 : .01"></label></div>
          <p>{{ gradientHelp }}</p>
        </section>
        <Button variant="secondary" :disabled="draft.types.length >= 64" @click="addType">{{ t('addType') }}</Button>
        <section v-if="active" class="pin-sampling">
          <strong>{{ active.pin_id }} · {{ extrasText.endpoints }}</strong>
          <div v-for="(pair, index) in active.endpoint_pairs" :key="index" class="pin-grid">
            <label>First ID<input v-model="pair.first_id"></label><label>Second ID<input v-model="pair.second_id"></label>
            <label>Type<SelectField v-model="pair.sampling_type" :options="typeOptions" /></label>
            <label>Offset X<input v-model.number="pair.center_offset[0]" type="number" step=".1"></label><label>Offset Y<input v-model.number="pair.center_offset[1]" type="number" step=".1"></label>
            <Button variant="secondary" @click="active.endpoint_pairs?.splice(index,1)">{{ t('remove') }}</Button>
          </div>
          <Button variant="secondary" :disabled="!draft.types.length || (active.endpoint_pairs?.length ?? 0) >= 2" @click="addEndpoints">{{ extrasText.addEndpoints }}</Button>
        </section>
        <section class="pin-sampling">
          <strong>{{ extrasText.bands }}</strong><p>{{ extrasText.hint }}</p>
          <div v-for="(band,index) in draft.candidate_bands" :key="index" class="pin-grid">
            <label>ID<input v-model="band.band_id"></label><label>X<input v-model.number="band.center[0]" type="number" step=".1"></label><label>Y<input v-model.number="band.center[1]" type="number" step=".1"></label>
            <label>Length<input v-model.number="band.length" type="number" min="4" max="8190"></label><label>Type<SelectField v-model="band.sampling_type" :options="typeOptions" /></label>
            <Button variant="secondary" @click="draft.candidate_bands?.splice(index,1)">{{ t('remove') }}</Button>
          </div>
          <Button variant="secondary" :disabled="!draft.types.length || (draft.candidate_bands?.length ?? 0) >= 64" @click="addBand">{{ extrasText.addBand }}</Button>
        </section>
        </template>
        </div>
        </div>
        <p v-if="!valid" class="pin-error">{{ t('invalid') }}</p>
      </div>
    </ConfirmDialog>
  </Teleport>
  <ImageViewer :open="viewerOpen" :image="viewerImage" :preview-disabled="true" dialog-layer @close="viewerOpen = false" @apply-interaction="applyPoint" />
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch,nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { useProjectStore } from '@/app/stores/project.store'
import Button from '@/shared/ui/components/Button.vue'
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'
import WorkflowSamplingDiagnostic from '@/workflows/workflow-editor/components/WorkflowSamplingDiagnostic.vue'
import type { PreviewNodeDisplay } from '@/workflows/workflow-editor/preview/useWorkflowPreviewDisplays'
import WorkflowMeasurementResourcePicker from '@/workflows/workflow-editor/components/WorkflowMeasurementResourcePicker.vue'
import { apiRequest } from '@/shared/api/http-client'
import { listMeasurementResources, readMeasurementResourceImage, resourceVersionPath, type MeasurementResourceDocument, type MeasurementResourceReference } from '@/workflows/workflow-editor/services/measurement-resource.service'
import { createPinLayout, hydratePinLayout, generatePins, inferPinArray, replacePinArray, isPinLayoutValid, samePinLayout, type PinDefinition, type PinLayout, type SamplingType } from './pin-layout'
defineOptions({ inheritAttrs: false })

const props = defineProps<{ modelValue: unknown; disabled?: boolean; previewDisplay?: PreviewNodeDisplay | null; draftIssues?:(value:unknown)=>string[] }>()
const emit = defineEmits<{ 'update:modelValue': [value: PinLayout] }>()
const { t, locale } = useI18n({ useScope: 'local', fallbackLocale: 'en-US', messages: {
  'zh-CN': { unconfigured: '未配置', edit: '编辑', title: 'PIN 布局', apply: '应用', cancel: '取消', reference: '参考模板', count: '名义数量', generate: '生成排列（替换当前草稿）', mark: '在图中标记', selectImage: '选择参考模板后可在原图中调整选中的 PIN。', hint: '身份固定；取消“应存在”表示设计留空，不是删除该位置。X/Y 和采样长度采用参考原图像素。', present: '应存在', remove: '移除', addType: '添加采样类型', invalid: '请检查 ID 唯一性、类型引用、扫描范围和采样预算。' },
  'en-US': { unconfigured: 'Not configured', edit: 'Edit', title: 'PIN Layout', apply: 'Apply', cancel: 'Cancel', reference: 'Reference template', count: 'Nominal count', generate: 'Generate array (replace draft)', mark: 'Mark on image', selectImage: 'Select a reference template to adjust the selected PIN on its original image.', hint: 'IDs remain fixed. Unchecking Expected present defines an empty position. Coordinates and sampling lengths use reference image pixels.', present: 'Expected present', remove: 'Remove', addType: 'Add sampling type', invalid: 'Check unique IDs, type references, scan ranges and sampling budget.' },
} })
const project = useProjectStore()
const gradientHelp = computed(() => locale.value === 'zh-CN'
  ? 'Min Gradient 是最小梯度门限；Relative Gradient 是各扫描线峰值的比例（0–1，0 表示关闭）。实际门限取两者较大值。'
  : 'Min Gradient is the absolute floor. Relative Gradient is a fraction of each scan line peak (0–1; 0 disables it). The higher threshold applies.')
const extrasText = computed(() => locale.value === 'zh-CN' ? {endpoints:'端点扫描',addEndpoints:'添加端点扫描',bands:'候选搜索带',hint:'只检查这些扫描带内的同类型多余候选；未配置不代表已排除多余物体。',addBand:'添加搜索带'} : {endpoints:'Endpoint scans',addEndpoints:'Add endpoint scan',bands:'Candidate search bands',hint:'Only matching candidates inside these bands are checked. No bands means extras are not checked.',addBand:'Add search band'})
const open = ref(false), viewerOpen = ref(false), error = ref(''), imageUrl = ref(''), selectedPin = ref(0)
const reference = ref<MeasurementResourceReference>(), resource = ref<MeasurementResourceDocument>()
const draft = ref<PinLayout>(createPinLayout())
const view=ref('layout'),selectedType=ref<string|number|boolean|null>('normal'),referenceLoading=ref(false)
const viewText=computed(()=>locale.value==='zh-CN'?{layout:'排列',sampling:'采样',diagnostic:'诊断',loading:'正在读取参考图…',details:'坐标详情',samplingType:'采样类型',referenceChanged:'参考模板已改变；PIN 坐标未自动转换，请核对位置、采样带及下游尺寸。'}:{layout:'Layout',sampling:'Sampling',diagnostic:'Diagnostics',loading:'Loading reference image…',details:'Coordinate details',samplingType:'Sampling type',referenceChanged:'Reference changed. PIN coordinates were not transformed; review positions, sampling bands and downstream measurements.'})
const views=computed(()=>['layout','sampling','diagnostic'].map(value=>({value,label:viewText.value[value as 'layout'|'sampling'|'diagnostic']})))
const samplingEntries=computed(()=>draft.value.types.flatMap((type,index)=>type.type_id===selectedType.value?[{type,index}]:[]))
const referenceChanged=computed(()=>!!(props.modelValue as PinLayout|undefined)?.reference_sha256&&draft.value.reference_sha256!==(props.modelValue as PinLayout).reference_sha256)
const referenceIssues=computed(()=>open.value ? props.draftIssues?.(draft.value)??[] : [])
const diagnosticText=computed(()=>locale.value==='zh-CN'?{select:'诊断 PIN',none:'关闭',help:'启用节点的 Debug Preview 并重新预览后，显示所选 PIN 的剖面。Runtime 不生成诊断数据。',stale:'参数已修改或结果已过期；应用后重新预览，不能使用旧剖面判断新配置。'}:{select:'Diagnostic PIN',none:'Off',help:'Enable Debug Preview and run the workflow to inspect the selected PIN. Runtime does not produce diagnostics.',stale:'Parameters changed or preview is stale. Apply and run again before evaluating this configuration.'})
const diagnosticDisplay=computed(()=>[props.previewDisplay,...(props.previewDisplay?.variants??[])].find(p=>p&&p.payload.sampling_diagnostic&&typeof p.payload.sampling_diagnostic==='object'))
const diagnosticCurrent=computed(()=>diagnosticDisplay.value&&!diagnosticDisplay.value.stale&&samePinLayout(diagnosticDisplay.value.payload.layout_snapshot,draft.value))
let abort: AbortController | null = null, generation = 0
const count = computed(() => (props.modelValue as PinLayout | undefined)?.pins?.length ?? 0)
const valid = computed(() => isPinLayoutValid(draft.value))
const active = computed(() => draft.value.pins[selectedPin.value])
const offset=ref(0),pinTable=ref<HTMLElement>()
const pagePins=computed(()=>draft.value.pins.slice(offset.value,offset.value+100).map((pin,i)=>({pin,index:offset.value+i})))
watch(selectedPin,async()=>{offset.value=Math.floor(Math.max(0,selectedPin.value)/100)*100;await nextTick();pinTable.value?.querySelector('tr.selected')?.scrollIntoView?.({block:'nearest'})})
watch(()=>draft.value.pins.length,()=>{if(offset.value>=draft.value.pins.length)offset.value=Math.max(0,Math.floor((draft.value.pins.length-1)/100)*100)})
watch(()=>active.value?.pin_type,value=>{if(value)selectedType.value=value})
watch(()=>draft.value.types.map(type=>type.type_id),ids=>{if(!ids.includes(String(selectedType.value)))selectedType.value=ids[0]??null})
const typeOptions = computed(() => draft.value.types.map(t => ({ value: t.type_id, label: t.type_id })))
const array = ref({ rows: 1, columns: 10, x: 100, y: 100, pitch: 50, rowPitch: 50, stagger: 0 })
const pendingPins=ref<PinDefinition[]|null>(null), previousArray=ref<{pins:PinDefinition[];diagnostic:string|null}|null>(null), irregular=ref(false)
const arrayText=computed(()=>locale.value==='zh-CN'?{preview:'待替换排列',empty:'设计留空',endpoints:'端点扫描',preserve:'保留同名 PIN 的类型、留空及端点。尺寸和公差不自动修改。',removed:'以下 ID 将移除，关联尺寸/公差必须重新检查',replace:'替换草稿排列',restore:'恢复替换前排列',irregular:'当前布局不是标准等距阵列；下方参数仅用于新排列，不代表当前位置。'}:{preview:'Candidate array',empty:'Empty positions',endpoints:'Endpoint scans',preserve:'Existing PIN types, empty positions and endpoints are retained by ID. Measurements and limits are not changed.',removed:'Removed IDs; review measurement and limit references',replace:'Replace draft array',restore:'Restore previous array',irregular:'Current layout is not a standard regular array. Generator parameters describe a new array, not current positions.'})
const removedPins=computed(()=>draft.value.pins.filter(p=>!pendingPins.value?.some(candidate=>candidate.pin_id===p.pin_id)).map(p=>p.pin_id))
const arrayFields: Array<{key: keyof typeof array.value; label: string; integer?: boolean}> = [ {key:'rows',label:'Rows',integer:true}, {key:'columns',label:'Columns',integer:true}, {key:'x',label:'Origin X'}, {key:'y',label:'Origin Y'}, {key:'pitch',label:'Pitch'}, {key:'rowPitch',label:'Row Pitch'}, {key:'stagger',label:'Stagger'} ]
const samplingFields: Array<{ key: Exclude<keyof SamplingType, 'type_id' | 'polarity'>; label: string; integer?: boolean }> = [
  {key:'search_length',label:'Search Length'}, {key:'band_width',label:'Band Width'}, {key:'scan_lines',label:'Scan Lines',integer:true}, {key:'sample_step',label:'Sample Step'}, {key:'angle_degrees',label:'Angle'}, {key:'gradient_threshold',label:'Min Gradient'}, {key:'relative_gradient_threshold',label:'Relative Gradient'}, {key:'min_width',label:'Min Width'}, {key:'max_width',label:'Max Width'}, {key:'min_coverage',label:'Min Coverage'}, {key:'max_residual',label:'Max Residual'},
]
const viewerImage = computed(() => imageUrl.value ? { title: active.value?.pin_id ?? t('title'), nodeId: 'pin-layout', src: imageUrl.value, mediaType: 'image/png', width: resource.value?.content.template?.image_width, height: resource.value?.content.template?.image_height,
  overlays: [...draft.value.pins.map(pin => ({ kind:'point', id:pin.pin_id, label:pin.pin_id, pointsXy:[pin.center], bboxXyxy:null, lineXyxy:null, circle:null, targetParameters:[], parameters:{} })), ...scanOverlays.value],
  interaction: active.value ? {mode:'edit', coordinateSpace:'image',tools:[{tool:'point',targetParameters:['center'],maxPoints:1,initialPointsXy:[active.value.center]}]} : null } : null)
const scanOverlays = computed(() => {
  const types = new Map(draft.value.types.map(type => [type.type_id,type]))
  const zones: Array<{id:string;center:[number,number];type:SamplingType;length:number}> = []
  if (active.value) {
    const pin=active.value,type=types.get(pin.pin_type)
    if(type) zones.push({id:pin.pin_id,center:pin.center,type,length:type.search_length})
    for(const pair of pin.endpoint_pairs ?? []) { const type=types.get(pair.sampling_type);if(type)zones.push({id:`${pair.first_id}/${pair.second_id}`,center:[pin.center[0]+pair.center_offset[0],pin.center[1]+pair.center_offset[1]],type,length:type.search_length}) }
  }
  for(const band of draft.value.candidate_bands ?? []) {const type=types.get(band.sampling_type);if(type)zones.push({id:band.band_id,center:band.center,type,length:band.length})}
  return zones.map(({id,center,type,length}) => {
    const a=type.angle_degrees*Math.PI/180,c=Math.cos(a),s=Math.sin(a)
    const pointsXy=([[-1,-1],[1,-1],[1,1],[-1,1]] as const).map(([u,v]):[number,number]=>[center[0]+u*length*c/2-v*type.band_width*s/2,center[1]+u*length*s/2+v*type.band_width*c/2])
    return {kind:'polygon',id:`scan-${id}`,label:id,pointsXy,bboxXyxy:null,lineXyxy:null,circle:null,targetParameters:[],parameters:{}}
  })
})
function releaseImage() { if (imageUrl.value) URL.revokeObjectURL(imageUrl.value); imageUrl.value = '' }
function close() { generation++; abort?.abort(); abort = null; open.value = false; viewerOpen.value = false; referenceLoading.value=false; releaseImage() }
function show() {
  close(); error.value = ''; const original = props.modelValue as PinLayout | undefined
    if (original && (!Array.isArray(original.pins) || !Array.isArray(original.types) || original.pins.some(p => !p || !Array.isArray(p.center) || p.center.length !== 2 || (p.endpoint_pairs !== undefined && (!Array.isArray(p.endpoint_pairs) || p.endpoint_pairs.some(e => !e || e.center_offset !== undefined && (!Array.isArray(e.center_offset) || e.center_offset.length !== 2))))) || original.types.some(t => !t) || (original.candidate_bands !== undefined && (!Array.isArray(original.candidate_bands) || original.candidate_bands.some(b => !b || !Array.isArray(b.center) || b.center.length !== 2))))) { error.value = t('invalid'); draft.value = createPinLayout() }
  else { draft.value = original ? hydratePinLayout(JSON.parse(JSON.stringify(original))) : createPinLayout() }
  selectedPin.value = 0;offset.value=0; view.value='layout';selectedType.value=draft.value.pins[0]?.pin_type??draft.value.types[0]?.type_id??null;open.value = true; reference.value = undefined; resource.value = undefined
  const inferred=inferPinArray(draft.value.pins)
  array.value=inferred ?? {rows:1,columns:10,x:100,y:100,pitch:50,rowPitch:50,stagger:0}
  irregular.value=!!draft.value.pins.length&&!inferred;pendingPins.value=null;previousArray.value=null
  void restoreReference()
}
async function restoreReference() {
  if (!project.selectedProjectId || !draft.value.reference_sha256) return
  abort = new AbortController(); const token = generation
  referenceLoading.value=true
  try {
    const items = await listMeasurementResources(project.selectedProjectId, abort.signal)
    if (token !== generation) return
    const match = items.find(item => item.reference.sha256 === draft.value.reference_sha256 && item.content.template?.reference_id === draft.value.reference_id)
    if (match) await chooseReference(match.reference)
  } catch (e) { if (token === generation) error.value = e instanceof Error ? e.message : t('invalid') }
  finally { if(token===generation)referenceLoading.value=false }
}
function apply() { if (valid.value && !props.disabled) { emit('update:modelValue', JSON.parse(JSON.stringify(draft.value))); close() } }
function generate() { if (!draft.value.types.length) return; try { const a = array.value; pendingPins.value = replacePinArray(draft.value.pins,generatePins(a.rows,a.columns,[a.x,a.y],a.pitch,a.rowPitch,a.stagger,draft.value.types[0].type_id)); error.value = '' } catch (e) { pendingPins.value=null;error.value = e instanceof Error ? e.message : t('invalid') } }
function acceptArray() {
  if(!pendingPins.value)return
  previousArray.value={pins:JSON.parse(JSON.stringify(draft.value.pins)),diagnostic:draft.value.diagnostic_pin_id??null}
  draft.value.pins=pendingPins.value;pendingPins.value=null;selectedPin.value=0
  if(!draft.value.pins.some(p=>p.pin_id===draft.value.diagnostic_pin_id))draft.value.diagnostic_pin_id=null
}
function restoreArray(){if(previousArray.value){draft.value.pins=previousArray.value.pins;draft.value.diagnostic_pin_id=previousArray.value.diagnostic;previousArray.value=null;pendingPins.value=null;selectedPin.value=0}}
watch(array,()=>{pendingPins.value=null},{deep:true})
watch(draft,()=>{pendingPins.value=null},{deep:true,flush:'sync'})
function addType() { const type = createPinLayout().types[0]; let n = 1; while (draft.value.types.some(t => t.type_id === `type-${n}`)) n++; draft.value.types.push({...type,type_id:`type-${n}`});selectedType.value=`type-${n}` }
function addEndpoints() { if (!draft.value.types.length || !active.value || (active.value.endpoint_pairs?.length ?? 0) >= 2) return; (active.value.endpoint_pairs ??= []).push({first_id:'tip',second_id:'root',sampling_type:draft.value.types[0].type_id,center_offset:[0,0]}) }
function addBand() { if (!draft.value.types.length) return; const bands = draft.value.candidate_bands ??= []; let n = 1; while (bands.some(b => b.band_id === `band-${n}`)) n++; bands.push({band_id:`band-${n}`,center:[...(active.value?.center ?? [100,100])] as [number,number],length:Math.max(200,draft.value.types[0].search_length),sampling_type:draft.value.types[0].type_id}) }
async function chooseReference(value: MeasurementResourceReference | undefined) {
  abort?.abort(); abort = new AbortController(); const token = ++generation; error.value = ''
  referenceLoading.value=!!value
  if (!value) { reference.value = undefined; resource.value = undefined; draft.value.reference_sha256 = null; releaseImage(); return }
  try {
    const [item, blob] = await Promise.all([apiRequest<MeasurementResourceDocument>(resourceVersionPath(value), {signal:abort.signal}), readMeasurementResourceImage(value,abort.signal)])
    if (token !== generation || !item.content.template) return
    reference.value = value; resource.value = item; draft.value.reference_id = item.content.template.reference_id; draft.value.reference_sha256 = value.sha256; releaseImage(); imageUrl.value = URL.createObjectURL(blob)
  } catch (e) { if (token === generation) error.value = e instanceof Error ? e.message : t('invalid') }
  finally { if(token===generation)referenceLoading.value=false }
}
function applyPoint(event: {pointsXy?: Array<[number,number]>; onApplied?: (ok:boolean) => void}) { if (active.value && event.pointsXy?.length) { active.value.center = [...event.pointsXy[0]]; event.onApplied?.(true) } else event.onApplied?.(false) }
watch(() => project.selectedProjectId, close)
onBeforeUnmount(close)
</script>
<style scoped>
.pin-scan-zone { fill:color-mix(in srgb,var(--am-brand-primary) 12%,transparent);stroke:var(--am-brand-primary);stroke-width:2;stroke-dasharray:8 5;pointer-events:none; }
.pin-layout-dialog :deep(.confirm-dialog) { width:min(1240px,calc(100vw - 36px)); }
.pin-edit { display:flex; justify-content:space-between; width:100%; padding:5px 8px; border:1px solid var(--am-border); border-radius:var(--am-radius-sm); color:var(--am-text); background:var(--am-input); font:inherit; cursor:pointer; }
.pin-workspace { display:grid; gap:16px; }
.pin-workspace p { margin:0;font-size:12px;color:var(--am-text-muted); }
.pin-tabs { display:flex;gap:8px; }
.pin-controls { display:grid;gap:12px;min-width:0;align-content:start; }
.pin-image-panel { position:sticky;top:0;align-self:start;display:grid;gap:12px;min-width:0; }
.pin-image-panel summary { cursor:pointer;color:var(--am-text-muted);font-size:12px; }
.pin-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(110px,1fr)); gap:12px; align-items:end; }
.pin-workspace label { display:grid; gap:6px; font-size:12px; color:var(--am-text-muted); flex:1 1 100px; min-width:0; }
.pin-workspace input { padding:6px; min-width:0; width:100%; border:1px solid var(--am-border); background:var(--am-input); color:var(--am-text); border-radius:var(--am-radius-sm); font:inherit; }
.pin-workspace input[type=checkbox] { width:16px; height:16px; min-width:16px; min-height:16px; padding:0; flex:none; }
.pin-workspace input:focus-visible { outline:2px solid var(--am-input-focus-ring); }
.pin-main { display:grid; grid-template-columns:minmax(320px,2fr) minmax(530px,3fr); gap:16px;align-items:start; }
.pin-image { padding:8px; background:var(--am-surface); color:var(--am-text); border:1px solid var(--am-border); cursor:pointer; }
.pin-image img { max-width:100%; max-height:280px; object-fit:contain; }
.pin-map { position:relative; }
.pin-map img { display:block;width:100%; }
.pin-map svg { position:absolute;inset:0;width:100%;height:100%; }
.pin-map g { cursor:pointer;outline:none; }
.pin-map circle { fill:transparent;stroke:white;stroke-width:2;vector-effect:non-scaling-stroke; }
.pin-map text { fill:white;stroke:#161616;stroke-width:3;paint-order:stroke;font-size:20px; }
.pin-map .active circle,.pin-map g:focus-visible circle { stroke:var(--am-brand-primary);fill:rgb(0 200 150 / .25); }
.pin-map .empty circle { stroke-dasharray:4 4; }
.pin-table-wrap { overflow:auto; max-height:290px; border:1px solid var(--am-border); }
.pin-table { border-collapse:collapse; width:100%; min-width:560px; font-size:12px; }
.pin-table :is(th,td) { padding:5px; text-align:left; border-bottom:1px solid var(--am-border); }
.pin-table th { position:sticky; top:0; background:var(--am-surface); z-index:1; }
.pin-table input { width:90px; }
.pin-table input:focus { min-width:120px; }
.pin-table input[type=checkbox]:focus { min-width:16px; }
.pin-table td:first-child input { width:90px; }
.pin-table tr.selected { background:color-mix(in srgb,var(--am-brand-primary) 12%,transparent); }
.pin-sampling { padding:12px; border:1px solid var(--am-border); border-radius:var(--am-radius-sm); display:grid; gap:12px; }
.pin-workspace .pin-error { color:var(--am-danger-text); }
@media(max-width:1000px) { .pin-main { grid-template-columns:1fr; }.pin-image-panel {position:static;}.pin-map {max-width:560px;margin:auto;} }
</style>
