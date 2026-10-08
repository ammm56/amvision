<template>
  <button type="button" class="measurement-edit" :disabled="disabled" @click="show">{{ count }} · {{ text.title }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" :title="text.title" :confirm-label="text.apply" :cancel-label="text.cancel" size="wide" scroll-body confirm-variant="primary" :confirm-disabled="!valid || disabled" @confirm="apply" @cancel="close">
      <div class="measurement-workspace">
        <p>{{ text.help }}</p>
        <p v-if="error" role="alert" class="measurement-error">{{ error }}</p>
        <div class="measurement-table"><table><thead><tr><th>ID</th><th>Kind</th><th>PIN A</th><th>PIN B</th><th>{{ text.enabled }}</th><th></th></tr></thead>
          <tbody><tr v-for="(item,index) in draft" :key="index" :class="{selected:index === selected}" @click="selected = index">
            <td><input v-model="item.item_id" :aria-label="`ID ${index+1}`"></td><td><SelectField :model-value="item.kind" :options="kinds" @update:model-value="setKind(item, String($event))" /></td>
            <td><input v-model="item.pin_a" :aria-label="`PIN A ${index+1}`"></td><td><input v-model="item.pin_b" :disabled="!paired(item)" :aria-label="`PIN B ${index+1}`"></td>
            <td><input v-model="item.enabled" type="checkbox" :aria-label="`${text.enabled} ${index+1}`"></td><td><button type="button" :aria-label="`${text.remove} ${index+1}`" @click.stop="draft.splice(index,1); selected = Math.min(selected,draft.length-1)">×</button></td>
          </tr></tbody></table></div>
        <Button variant="secondary" :disabled="draft.length >= 8192" @click="add">{{ text.add }}</Button>
        <div v-if="active" class="measurement-detail">
          <strong>{{ active.item_id }}</strong>
          <Button variant="secondary" :disabled="!referenceUrl" @click="viewerOpen=true">{{ text.mark }}</Button>
          <p>{{ referenceError || text.visualHelp }}</p>
          <div class="measurement-grid">
            <label>Direction X<input v-model.number="active.direction[0]" type="number" step=".01"></label>
            <label>Direction Y<input v-model.number="active.direction[1]" type="number" step=".01"></label>
            <Button variant="secondary" @click="normalize">{{ text.normalize }}</Button>
            <label v-if="['width','gap'].includes(active.kind)">Section<input v-model.number="active.section" type="number" step=".1"></label>
            <label v-if="active.kind !== 'angle'">Distance<SelectField v-model="active.distance_mode" :options="[{value:'projected',label:'Projected'}, {value:'euclidean',label:'Euclidean'}]" /></label>
          </div>
          <div v-if="active.kind === 'length'" class="measurement-grid">
            <label>Start Feature<input v-model="active.feature_a" placeholder="R1P01:tip"></label><label>End Feature<input v-model="active.feature_b" placeholder="R1P01:root"></label>
          </div>
          <p>{{ active.kind === 'length' ? text.length : text.reference }}</p>
        </div>
        <p v-if="!valid" class="measurement-error">{{ text.invalid }}</p>
      </div>
    </ConfirmDialog>
  </Teleport>
  <ImageViewer :open="viewerOpen" :image="viewerImage" preview-disabled dialog-layer @close="viewerOpen=false" @apply-interaction="applyDirection" />
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import ImageViewer from '@/shared/ui/components/ImageViewer.vue'
import {useProjectStore} from '@/app/stores/project.store'
import {listMeasurementResources,readMeasurementResourceImage} from '@/workflows/workflow-editor/services/measurement-resource.service'
import type {ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import type {PreviewImageOverlay} from '@/workflows/workflow-editor/preview/useWorkflowPreviewDisplays'
import {hydratePinLayout,isPinLayoutValid,type PinLayout} from './pin-layout'
defineOptions({ inheritAttrs: false })

interface Item { item_id:string;kind:string;enabled:boolean;pin_a:string;pin_b:string|null;direction:[number,number];section:number|null;distance_mode:string;feature_a:string|null;feature_b:string|null }
const props = defineProps<{ modelValue:unknown; disabled?:boolean; inputSources?:ParameterEditorSources }>()
const emit = defineEmits<{ 'update:modelValue':[value:Item[]] }>()
const { locale } = useI18n()
const text = computed(() => locale.value === 'zh-CN' ? {title:'尺寸项',mark:'在参考图设置方向 / 截面',configuration:'配置示意',visualHelp:'图上只显示参考配置，不代表测量结果。Pins 和 Features 须来自同一个 Pin Array Locate，并选择了参考模板。',apply:'应用',cancel:'取消',enabled:'启用',remove:'移除',add:'添加尺寸',normalize:'归一化方向',help:'按稳定 PIN ID 配置尺寸。公差在 Check Limits 中定义；未观测到的特征不会补名义值。',reference:'方向和截面采用参考原图坐标。截面为点在方向法线上的投影；Angle 输出 0–90° 无向夹角。',length:'长度端点必须是 Pin Array Locate 实际提取的具名点。不可见针根不能用检测框代替。',invalid:'请检查唯一 ID、PIN 配对、单位方向和必要的截面/端点。'} : {title:'Measurements',mark:'Set direction / section on reference',configuration:'Configuration guide',visualHelp:'Reference configuration only, not measured geometry. Pins and Features must come from the same Pin Array Locate with a reference template.',apply:'Apply',cancel:'Cancel',enabled:'Enabled',remove:'Remove',add:'Add measurement',normalize:'Normalize direction',help:'Use stable PIN IDs. Configure tolerances in Check Limits. Missing observations are never replaced by nominal values.',reference:'Direction and section use reference-image coordinates. Section is the projection onto the direction normal. Angle is an unsigned 0–90° angle.',length:'Length requires named points observed by Pin Array Locate. An invisible root is not inferred from a bounding box.',invalid:'Check unique IDs, PIN pairs, unit directions and required section/endpoints.'})
const kinds = ['width','pitch','total_pitch','gap','offset','length','angle'].map(value => ({value,label:value.replace('_',' ').replace(/^./,c=>c.toUpperCase())}))
const open = ref(false), selected = ref(0), error = ref(''), draft = ref<Item[]>([])
const project=useProjectStore(), referenceUrl=ref(''), referenceError=ref(''), viewerOpen=ref(false), referenceLayout=ref<PinLayout>(), referenceSize=ref<[number,number]>()
let referenceAbort:AbortController|undefined,referenceGeneration=0
const count = computed(() => Array.isArray(props.modelValue) ? props.modelValue.length : 0)
const active = computed(() => draft.value[selected.value])
const paired = (item:Item) => !['width','offset'].includes(item.kind)
const valid = computed(() => {
  const id = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/
  return draft.value.length > 0 && draft.value.length <= 8192 && new Set(draft.value.map(i => i.item_id)).size === draft.value.length && draft.value.every(i =>
    id.test(i.item_id) && id.test(i.pin_a) && kinds.some(k => k.value === i.kind) && (paired(i) ? !!i.pin_b && id.test(i.pin_b) && (i.pin_a !== i.pin_b || i.kind === 'length') : i.pin_b === null) &&
    i.direction.every(Number.isFinite) && Math.abs(i.direction[0]**2+i.direction[1]**2-1) <= 1e-6 && ['projected','euclidean'].includes(i.distance_mode) &&
    (!['width','gap'].includes(i.kind) || (i.section !== null && Number.isFinite(i.section))) &&
    (i.kind === 'length' ? !!i.feature_a && !!i.feature_b && i.feature_a !== i.feature_b && id.test(i.feature_a) && id.test(i.feature_b) : i.feature_a === null && i.feature_b === null))
})
function blank():Item { return {item_id:'width',kind:'width',enabled:true,pin_a:'R1P01',pin_b:null,direction:[1,0],section:0,distance_mode:'projected',feature_a:null,feature_b:null} }
function show() {
  close()
  error.value = ''; selected.value = 0
  const original = Array.isArray(props.modelValue) ? props.modelValue : []
  try { draft.value = original.map(i => { if (!i || typeof i !== 'object' || ('direction' in i && (!Array.isArray(i.direction) || i.direction.length !== 2))) throw new Error(text.value.invalid); return {...blank(),...JSON.parse(JSON.stringify(i))} }); open.value = true }
  catch { draft.value = []; error.value = text.value.invalid; open.value = true }
  void loadReference()
}
function add() { let n = 1; while (draft.value.some(i=>i.item_id===`measure-${n}`)) n++; draft.value.push({...blank(),item_id:`measure-${n}`}); selected.value = draft.value.length-1 }
function setKind(item:Item, kind:string) { item.kind=kind; item.pin_b=paired(item) ? item.pin_b || (kind==='length'?item.pin_a:'R1P02') : null; item.section=['width','gap'].includes(kind)?item.section??0:null; item.feature_a=kind==='length'?`${item.pin_a}:tip`:null; item.feature_b=kind==='length'?`${item.pin_b}:root`:null }
function normalize() { if (!active.value) return; const d=active.value.direction, norm=Math.hypot(...d); if (Number.isFinite(norm)&&norm>0) active.value.direction=[d[0]/norm,d[1]/norm] }
function apply() { if (valid.value && !props.disabled) { emit('update:modelValue',JSON.parse(JSON.stringify(draft.value))); close() } }
function close(){open.value=false;viewerOpen.value=false;referenceGeneration++;referenceAbort?.abort();referenceAbort=undefined;if(referenceUrl.value)URL.revokeObjectURL(referenceUrl.value);referenceUrl.value='';referenceError.value='';referenceLayout.value=undefined;referenceSize.value=undefined}
async function loadReference(){
  const pins=props.inputSources?.pins,features=props.inputSources?.features
  if(pins?.length!==1||features?.length!==1||pins[0]!.nodeId!==features[0]!.nodeId||pins[0]!.nodeTypeId!=='custom.connector.pin-array-locate'||!project.selectedProjectId)return
  const token=++referenceGeneration
  try{
    const layout=hydratePinLayout(JSON.parse(JSON.stringify(pins[0]!.parameters.layout)))
    if(!isPinLayoutValid(layout)||!layout.reference_sha256)return
    referenceAbort=new AbortController()
    const resources=await listMeasurementResources(project.selectedProjectId,referenceAbort.signal)
    if(token!==referenceGeneration)return
    const resource=resources.find(item=>item.reference.sha256===layout.reference_sha256&&item.content.template?.reference_id===layout.reference_id)
    if(!resource?.content.template)return
    const image=await readMeasurementResourceImage(resource.reference,referenceAbort.signal)
    if(token!==referenceGeneration)return
    referenceLayout.value=layout;referenceSize.value=[resource.content.template.image_width,resource.content.template.image_height];referenceUrl.value=URL.createObjectURL(image)
  }catch(e){if(token===referenceGeneration&&!referenceAbort?.signal.aborted&&open.value)referenceError.value=e instanceof Error?e.message:String(e)}
}
const viewerImage=computed(()=>{
  const item=active.value,layout=referenceLayout.value
  if(!referenceUrl.value||!layout||!item)return null
  const chosen=layout.pins.filter(p=>p.pin_id===item.pin_a||p.pin_id===item.pin_b)
  const overlays:PreviewImageOverlay[]=chosen.map(p=>({kind:'point',id:p.pin_id,label:p.pin_id,pointsXy:[p.center],bboxXyxy:null,lineXyxy:null,circle:null,targetParameters:[],parameters:{}}))
  let line:[number,number,number,number]|undefined
  if(chosen[0]&&item.direction.every(Number.isFinite)){
    const [dx,dy]=item.direction,[x,y]=chosen[0].center
    const shift=['width','gap'].includes(item.kind)&&item.section!==null?item.section-(-dy*x+dx*y):0
    const cx=x-dy*shift,cy=y+dx*shift
    line=[cx-dx*60,cy-dy*60,cx+dx*60,cy+dy*60]
    overlays.push({kind:'line',id:'direction-section',label:text.value.configuration,pointsXy:[],bboxXyxy:null,lineXyxy:line,circle:null,targetParameters:[],parameters:{}})
  }
  return {title:`${item.item_id} · ${text.value.configuration}`,nodeId:'connector-measure',src:referenceUrl.value,mediaType:'image/png',width:referenceSize.value?.[0],height:referenceSize.value?.[1],overlays,
    interaction:{mode:'edit',coordinateSpace:'image',tools:[{tool:'line',targetParameters:['direction','section'],maxPoints:2,initialPointsXy:line?[[line[0],line[1]],[line[2],line[3]]] as Array<[number,number]>:[]}]}}
})
function applyDirection(event:{pointsXy?:Array<[number,number]>;lineXyxy?:[number,number,number,number];onApplied?:(ok:boolean)=>void}){
  const line=event.lineXyxy
  const points=line?[[line[0],line[1]],[line[2],line[3]]]:event.pointsXy,item=active.value
  if(!item||points?.length!==2){event.onApplied?.(false);return}
  const a=points[0]!,b=points[1]!,dx=b[0]-a[0],dy=b[1]-a[1],length=Math.hypot(dx,dy)
  if(!Number.isFinite(length)||length<1e-6){event.onApplied?.(false);return}
  item.direction=[dx/length,dy/length]
  if(['width','gap'].includes(item.kind))item.section=-item.direction[1]*a[0]+item.direction[0]*a[1]
  event.onApplied?.(true)
}
watch(()=>project.selectedProjectId,close)
watch(()=>JSON.stringify(props.inputSources),()=>{if(open.value)close()})
onBeforeUnmount(close)
</script>
<style scoped>
.measurement-edit { width:100%; text-align:left; padding:6px 8px; color:var(--am-text); background:var(--am-input); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); font:inherit; cursor:pointer; }
.measurement-workspace,.measurement-detail { display:grid; gap:12px; }
.measurement-workspace p { margin:0; font-size:13px; color:var(--am-text-muted); }
.measurement-table { max-height:340px; overflow:auto; border:1px solid var(--am-border); }
table { width:100%; min-width:640px; border-collapse:collapse; font-size:13px; }
th,td { padding:6px; text-align:left; border-bottom:1px solid var(--am-border); }
th { position:sticky; top:0; background:var(--am-surface); }
tr.selected { background:color-mix(in srgb,var(--am-brand-primary) 12%,transparent); }
input { width:100%; min-width:60px; padding:6px; background:var(--am-input); color:var(--am-text); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); font:inherit; }
input:focus-visible { outline:2px solid var(--am-input-focus-ring); }
input[type=checkbox] { width:auto; min-width:0; accent-color:var(--am-brand-primary); }
.measurement-grid { display:flex; flex-wrap:wrap; gap:12px; align-items:end; }
label { display:grid; gap:6px; flex:1 1 130px; font-size:12px; color:var(--am-text-muted); }
.measurement-workspace .measurement-error { color:var(--am-danger-text); }
</style>
