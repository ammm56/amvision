<template>
  <button type="button" class="measurement-edit" :disabled="disabled" @click="show">{{ count }} · {{ text.title }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="measurement-dialog" :title="text.title" :confirm-label="text.apply" :cancel-label="text.cancel" size="wide" scroll-body confirm-variant="primary" :confirm-disabled="!valid || disabled" @confirm="apply" @cancel="close">
      <div class="measurement-workspace">
        <p>{{ text.help }}</p>
        <p v-if="error" role="alert" class="measurement-error">{{ error }}</p>
        <p v-if="referenceIssues.length" role="status" class="measurement-error">{{ referenceIssues.join('; ') }}</p>
        <div class="measurement-tabs" role="group" :aria-label="text.title"><Button :variant="view==='items'?'primary':'secondary'" :aria-pressed="view==='items'" @click="view='items'">{{ viewText.items }} · {{ draft.length }}</Button><Button :variant="view==='batch'?'primary':'secondary'" :aria-pressed="view==='batch'" :disabled="!referenceLayout" @click="view='batch'">{{ viewText.batch }}</Button></div>
        <div v-if="referenceLayout && view==='batch'" class="measurement-batch">
          <button v-if="referenceUrl" type="button" class="measurement-reference" @click="viewerOpen=true"><img :src="referenceUrl" :alt="text.configuration"><span>{{ text.mark }}</span></button>
          <label>{{ batchText.row }}<SelectField v-model="batchRow" :options="[{value:'',label:batchText.all},...rows.map(row=>({value:row,label:row}))]" @update:model-value="selectRow" /></label>
          <div class="measurement-options"><label v-for="pin in referenceLayout.pins.filter(p=>!batchRow||p.row_id===batchRow)" :key="pin.pin_id"><input v-model="batchPins" type="checkbox" :value="pin.pin_id" :disabled="!pin.expected_present">{{ pin.pin_id }}{{ pin.expected_present?'':` · ${batchText.empty}` }}</label></div>
          <div class="measurement-options"><label v-for="kind in batchKinds" :key="kind"><input v-model="batchSelectedKinds" type="checkbox" :value="kind">{{ kindLabel(kind) }}</label></div>
          <p>{{ batchText.preserve }}</p>
          <Button variant="secondary" :disabled="!batchPins.length || !batchSelectedKinds.length" @click="previewBatch">{{ batchText.preview }}</Button>
          <div v-if="pendingBatch" role="status">
            <p>{{ pendingBatch.length }} · {{ batchText.items }} · {{ batchText.preserve }}</p>
            <p v-if="!pendingBatch.length">{{ batchText.duplicates }}</p>
            <div v-else class="measurement-table measurement-candidates">
              <table><thead><tr><th>ID</th><th>{{ batchText.kind }}</th><th>PIN A</th><th>PIN B</th><th>{{ batchText.direction }}</th><th>{{ batchText.section }}</th></tr></thead>
                <tbody><tr v-for="item in pendingBatch" :key="item.item_id"><td>{{ item.item_id }}</td><td>{{ kindLabel(item.kind) }}</td><td>{{ item.pin_a }}</td><td>{{ item.pin_b ?? '—' }}</td><td>{{ item.direction.join(', ') }}</td><td>{{ item.section ?? '—' }}</td></tr></tbody>
              </table>
            </div>
            <Button variant="secondary" :disabled="!pendingBatch.length || draft.length+pendingBatch.length>8192" @click="acceptBatch">{{ batchText.add }}</Button><Button variant="secondary" @click="pendingBatch=null">{{ text.cancel }}</Button>
          </div>
        </div>
        <Button v-if="previousBatch" variant="secondary" @click="restoreBatch">{{ batchText.restore }}</Button>
        <p v-if="!referenceLayout" role="status">{{ batchText.unresolved }}</p>
        <p v-if="invalidReferences.length" role="alert" class="measurement-error">{{ batchText.invalid }}: {{ invalidReferences.join(', ') }}</p>
        <div v-if="view==='items'" class="measurement-main">
        <section class="measurement-list">
        <div class="measurement-table"><table><thead><tr><th>ID</th><th>{{ batchText.kind }}</th><th>PIN A</th><th>PIN B</th><th>{{ text.enabled }}</th><th></th></tr></thead>
          <tbody><tr v-for="{item,index} in pageRows" :key="index" :class="{selected:index === selected}" @click="selected = index" @focusin="selected=index">
            <td><input v-model="item.item_id" :aria-label="`ID ${index+1}`"></td><td><SelectField :model-value="item.kind" :options="kinds" @update:model-value="setKind(item, String($event))" /></td>
            <td><SelectField v-if="referenceLayout" v-model="item.pin_a" :options="pinOptions" :aria-label="`PIN A ${index+1}`" /><input v-else v-model="item.pin_a" :aria-label="`PIN A ${index+1}`"></td><td><span v-if="!paired(item)">—</span><SelectField v-else-if="referenceLayout" v-model="item.pin_b" :options="pinOptions" :aria-label="`PIN B ${index+1}`" /><input v-else v-model="item.pin_b" :aria-label="`PIN B ${index+1}`"></td>
            <td><input v-model="item.enabled" type="checkbox" :aria-label="`${text.enabled} ${index+1}`"></td><td><button type="button" :aria-label="`${text.remove} ${index+1}`" @click.stop="draft.splice(index,1); selected = Math.min(selected,draft.length-1)">×</button></td>
          </tr></tbody></table></div>
        <PaginationControls v-if="draft.length>100" :offset="offset" :limit="100" :item-count="pageRows.length" :total-count="draft.length" @previous="offset-=100" @next="offset+=100" />
        <Button variant="secondary" :disabled="draft.length >= 8192" @click="add">{{ text.add }}</Button>
        </section>
        <div v-if="active" class="measurement-detail">
          <strong>{{ active.item_id }}</strong>
          <button v-if="referenceUrl" type="button" class="measurement-reference" @click="viewerOpen=true"><img :src="referenceUrl" :alt="text.configuration"><span>{{ text.mark }}</span></button>
          <p>{{ referenceError || text.visualHelp }}</p>
          <div class="measurement-grid">
            <label>Direction X<input v-model.number="active.direction[0]" type="number" step=".01"></label>
            <label>Direction Y<input v-model.number="active.direction[1]" type="number" step=".01"></label>
            <Button variant="secondary" @click="normalize">{{ text.normalize }}</Button>
            <label v-if="['width','gap'].includes(active.kind)">Section<input v-model.number="active.section" type="number" step=".1"></label>
            <label v-if="active.kind !== 'angle'">Distance<SelectField v-model="active.distance_mode" :options="[{value:'projected',label:'Projected'}, {value:'euclidean',label:'Euclidean'}]" /></label>
          </div>
          <div v-if="active.kind === 'length'" class="measurement-grid">
            <label>Start Feature<SelectField v-if="referenceLayout" v-model="active.feature_a" :options="endpointIds(referenceLayout,active.pin_a).map(value=>({value,label:value}))" /><input v-else v-model="active.feature_a" placeholder="R1P01:tip"></label><label>End Feature<SelectField v-if="referenceLayout" v-model="active.feature_b" :options="endpointIds(referenceLayout,active.pin_b??'').map(value=>({value,label:value}))" /><input v-else v-model="active.feature_b" placeholder="R1P01:root"></label>
          </div>
          <p>{{ active.kind === 'length' ? text.length : text.reference }}</p>
        </div>
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
import PaginationControls from '@/shared/ui/components/PaginationControls.vue'
import {hydratePinLayout,isPinLayoutValid,type PinLayout} from './pin-layout'
import {buildMeasurementBatch,batchKinds,endpointIds,invalidMeasurementReferences,type MeasurementItem as Item} from './measurement-items'
defineOptions({ inheritAttrs: false })

const props = defineProps<{ modelValue:unknown; disabled?:boolean; inputSources?:ParameterEditorSources; draftIssues?:(value:unknown)=>string[] }>()
const emit = defineEmits<{ 'update:modelValue':[value:Item[]] }>()
const { locale } = useI18n()
const text = computed(() => locale.value === 'zh-CN' ? {title:'尺寸项',mark:'在参考图设置方向 / 截面',configuration:'配置示意',visualHelp:'图上只显示参考配置，不代表测量结果。Pins 和 Features 须来自同一个 Pin Array Locate，并选择了参考模板。',apply:'应用',cancel:'取消',enabled:'启用',remove:'移除',add:'添加尺寸',normalize:'归一化方向',help:'按稳定 PIN ID 配置尺寸。公差在 Check Limits 中定义；未观测到的特征不会补名义值。',reference:'方向和截面采用参考原图坐标。截面为点在方向法线上的投影；Angle 输出 0–90° 无向夹角。',length:'长度端点必须是 Pin Array Locate 实际提取的具名点。不可见针根不能用检测框代替。',invalid:'请检查唯一 ID、PIN 配对、单位方向和必要的截面/端点。'} : {title:'Measurements',mark:'Set direction / section on reference',configuration:'Configuration guide',visualHelp:'Reference configuration only, not measured geometry. Pins and Features must come from the same Pin Array Locate with a reference template.',apply:'Apply',cancel:'Cancel',enabled:'Enabled',remove:'Remove',add:'Add measurement',normalize:'Normalize direction',help:'Use stable PIN IDs. Configure tolerances in Check Limits. Missing observations are never replaced by nominal values.',reference:'Direction and section use reference-image coordinates. Section is the projection onto the direction normal. Angle is an unsigned 0–90° angle.',length:'Length requires named points observed by Pin Array Locate. An invisible root is not inferred from a bounding box.',invalid:'Check unique IDs, PIN pairs, unit directions and required section/endpoints.'})
const kindNames:Record<string,[string,string]>={width:['宽度','Width'],pitch:['中心距','Pitch'],total_pitch:['总中心距','Total Pitch'],gap:['间隙','Gap'],offset:['偏移','Offset'],length:['长度','Length'],angle:['角度','Angle']}
function kindLabel(value:string){return kindNames[value]?.[locale.value==='zh-CN'?0:1]??value}
const kinds=computed(()=>Object.keys(kindNames).map(value=>({value,label:kindLabel(value)})))
const open = ref(false), selected = ref(0), error = ref(''), draft = ref<Item[]>([])
const offset=ref(0),pageRows=computed(()=>draft.value.slice(offset.value,offset.value+100).map((item,i)=>({item,index:offset.value+i})))
watch(selected,()=>{offset.value=Math.floor(Math.max(0,selected.value)/100)*100})
watch(()=>draft.value.length,()=>{if(offset.value>=draft.value.length)offset.value=Math.max(0,Math.floor((draft.value.length-1)/100)*100)})
const view=ref('items')
const viewText=computed(()=>locale.value==='zh-CN'?{items:'已有尺寸',batch:'批量新增'}:{items:'Measurements',batch:'Add batch'})
const referenceIssues=computed(()=>open.value ? props.draftIssues?.(draft.value)??[] : [])
const batchRow=ref<string|number|boolean|null>(''),batchPins=ref<string[]>([]),batchSelectedKinds=ref<string[]>([...batchKinds]),pendingBatch=ref<Item[]|null>(null),previousBatch=ref<Item[]|null>(null)
const batchText=computed(()=>locale.value==='zh-CN'?{kind:'类型',direction:'方向',section:'截面（px）',row:'选择排列',all:'全部排列',empty:'设计留空',preview:'预览批量尺寸',items:'新增尺寸',preserve:'已存在的 ID 保持不变；默认沿参考 X 方向，截面取所选 PIN 中心。应用前核对方向和截面。',duplicates:'没有新增尺寸；相同 ID 已存在。',add:'添加到草稿',restore:'恢复批量添加前',unresolved:'无法从显式 Pins / Features 连线解析名义布局；仅可手动配置，引用将在执行前验证。',invalid:'无效 PIN / 端点引用'}:{kind:'Kind',direction:'Direction',section:'Section (px)',row:'Select row',all:'All rows',empty:'Designed empty',preview:'Preview batch',items:'new measurements',preserve:'Existing IDs are unchanged. Defaults use reference X and PIN center sections; review direction and sections.',duplicates:'No new items; IDs already exist.',add:'Add to draft',restore:'Restore before batch',unresolved:'Nominal layout cannot be resolved from explicit Pins / Features connections. Manual configuration only; references are validated before execution.',invalid:'Invalid PIN / endpoint references'})
const rows=computed(()=>[...new Set(referenceLayout.value?.pins.map(p=>p.row_id)??[])])
const pinOptions=computed(()=>referenceLayout.value?.pins.map(p=>({value:p.pin_id,label:p.pin_id}))??[])
const invalidReferences=computed(()=>referenceLayout.value?invalidMeasurementReferences(draft.value,referenceLayout.value):[])
const project=useProjectStore(), referenceUrl=ref(''), referenceError=ref(''), viewerOpen=ref(false), referenceLayout=ref<PinLayout>(), referenceSize=ref<[number,number]>()
let referenceAbort:AbortController|undefined,referenceGeneration=0
const count = computed(() => Array.isArray(props.modelValue) ? props.modelValue.length : 0)
const active = computed(() => draft.value[selected.value])
const paired = (item:Item) => !['width','offset'].includes(item.kind)
const valid = computed(() => {
  const id = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/
  return !invalidReferences.value.length && draft.value.length > 0 && draft.value.length <= 8192 && new Set(draft.value.map(i => i.item_id)).size === draft.value.length && draft.value.every(i =>
    id.test(i.item_id) && id.test(i.pin_a) && kinds.value.some(k => k.value === i.kind) && (paired(i) ? !!i.pin_b && id.test(i.pin_b) && (i.pin_a !== i.pin_b || i.kind === 'length') : i.pin_b === null) &&
    i.direction.every(Number.isFinite) && Math.abs(i.direction[0]**2+i.direction[1]**2-1) <= 1e-6 && ['projected','euclidean'].includes(i.distance_mode) &&
    (!['width','gap'].includes(i.kind) || (i.section !== null && Number.isFinite(i.section))) &&
    (i.kind === 'length' ? !!i.feature_a && !!i.feature_b && i.feature_a !== i.feature_b && id.test(i.feature_a) && id.test(i.feature_b) : i.feature_a === null && i.feature_b === null))
})
function blank():Item { return {item_id:'width',kind:'width',enabled:true,pin_a:'R1P01',pin_b:null,direction:[1,0],section:0,distance_mode:'projected',feature_a:null,feature_b:null} }
function show() {
  close()
  error.value = ''; selected.value = 0;offset.value=0;view.value='items'
  pendingBatch.value=null;previousBatch.value=null;batchRow.value='';batchSelectedKinds.value=[...batchKinds]
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
  if(pins?.length!==1||features?.length!==1||pins[0]!.nodeId!==features[0]!.nodeId||pins[0]!.nodeTypeId!=='custom.connector.pin-array-locate')return
  const token=++referenceGeneration
  try{
    const layout=hydratePinLayout(JSON.parse(JSON.stringify(pins[0]!.parameters.layout)))
    if(!isPinLayoutValid(layout))return
    referenceLayout.value=layout;selectRow()
    if(!layout.reference_sha256||!project.selectedProjectId)return
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
function selectRow(){batchPins.value=referenceLayout.value?.pins.filter(p=>p.expected_present&&(!batchRow.value||p.row_id===batchRow.value)).map(p=>p.pin_id)??[];pendingBatch.value=null}
function previewBatch(){if(referenceLayout.value){const existing=new Set(draft.value.map(i=>i.item_id));pendingBatch.value=buildMeasurementBatch(referenceLayout.value,batchPins.value,batchSelectedKinds.value).filter(i=>!existing.has(i.item_id))}}
function acceptBatch(){if(!pendingBatch.value?.length||draft.value.length+pendingBatch.value.length>8192)return;const items=pendingBatch.value;previousBatch.value=JSON.parse(JSON.stringify(draft.value));selected.value=draft.value.length;draft.value.push(...items);pendingBatch.value=null;view.value='items'}
function restoreBatch(){if(previousBatch.value){draft.value=previousBatch.value;previousBatch.value=null;selected.value=0}}
watch([batchPins,batchSelectedKinds],()=>{pendingBatch.value=null},{deep:true})
watch(draft,()=>{pendingBatch.value=null},{deep:true,flush:'sync'})
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
.measurement-dialog :deep(.confirm-dialog) { width:min(1240px,calc(100vw - 36px)); }
.measurement-tabs { display:flex;gap:8px; }
.measurement-main { display:grid;grid-template-columns:minmax(620px,3fr) minmax(280px,2fr);gap:16px;align-items:start; }
.measurement-list { display:grid;gap:12px;min-width:0; }
.measurement-detail { min-width:0;position:sticky;top:0; }
.measurement-edit { width:100%; text-align:left; padding:6px 8px; color:var(--am-text); background:var(--am-input); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); font:inherit; cursor:pointer; }
.measurement-workspace,.measurement-detail { display:grid; gap:12px; }
.measurement-workspace p { margin:0; font-size:13px; color:var(--am-text-muted); }
.measurement-table { max-height:400px; overflow:auto; border:1px solid var(--am-border); }
table { width:100%; min-width:640px; border-collapse:collapse; font-size:13px; }
th,td { padding:6px; text-align:left; border-bottom:1px solid var(--am-border); }
th { position:sticky; top:0; background:var(--am-surface); }
tr.selected { background:color-mix(in srgb,var(--am-brand-primary) 12%,transparent); }
input { width:100%; min-width:60px; padding:6px; background:var(--am-input); color:var(--am-text); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); font:inherit; }
input:focus-visible { outline:2px solid var(--am-input-focus-ring); }
input[type=checkbox] { width:16px; height:16px; min-width:16px; min-height:16px; padding:0; flex:none; }
th { white-space:nowrap; }
.measurement-grid { display:flex; flex-wrap:wrap; gap:12px; align-items:end; }
label { display:grid; gap:6px; flex:1 1 130px; font-size:12px; color:var(--am-text-muted); }
.measurement-workspace .measurement-error { color:var(--am-danger-text); }
.measurement-batch { display:grid; gap:10px; border:1px solid var(--am-border); border-radius:var(--am-radius-sm); padding:12px; }
.measurement-reference { display:grid; gap:8px; padding:8px; background:var(--am-surface); border:1px solid var(--am-border); color:var(--am-text); cursor:pointer; }
.measurement-reference img { width:100%; max-height:240px; object-fit:contain; }
.measurement-options { display:flex; flex-wrap:wrap; gap:10px; }
.measurement-options label { display:flex; align-items:center; flex:0 0 auto; }
.measurement-candidates { max-height:220px; margin:8px 0; }
@media(max-width:1050px) { .measurement-main {grid-template-columns:1fr;}.measurement-detail {position:static;} }
</style>
