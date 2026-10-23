<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ zh?'三维 ROI':'3D ROI' }} · {{ object(modelValue).kind==='input'?(zh?'输入端口':'Input port'):String(object(object(modelValue).roi).roi_id||'-') }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" class="geometry-dialog" :title="zh?'裁剪 ROI':'Crop ROI'" size="wide" scroll-body confirm-variant="primary" :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="!!issues.length||disabled" @confirm="apply" @cancel="open=false">
    <div class="geometry-workspace roi-workspace">
      <section class="roi-config">
      <div class="geometry-toolbar"><label v-if="allowInput !== false">{{ zh?'ROI 来源':'ROI source' }}<select :value="draft.kind" @change="changeSource(($event.target as HTMLSelectElement).value)"><option value="parameters">{{ zh?'节点参数':'Node parameters' }}</option><option value="input">{{ zh?'输入端口':'Input port' }}</option></select></label>
        <label>{{ zh?'编辑对象':'Edit ROI' }}<select v-model="selected"><option v-if="draft.kind==='parameters'" value="target">{{ zh?'目标 ROI':'Target ROI' }}</option><option v-for="(roi,i) in bounds" :key="i" :value="String(i)">{{ String(roi.roi_id||`#${i+1}`) }}</option></select></label>
        <button :title="zh?'添加有限边界':'Add finite bound'" @click="add"><Plus :size="18" /></button><button :title="zh?'删除边界':'Remove bound'" :disabled="selected==='target'||!current" @click="remove"><Trash2 :size="18" /></button>
      </div>
      <template v-if="current"><label>{{ zh?'几何类型':'Geometry' }}<select :value="current.kind" @change="changeKind(($event.target as HTMLSelectElement).value)"><option value="box">{{ zh?'有向盒':'Oriented box' }}</option><option value="cylinder">{{ zh?'有限圆柱':'Finite cylinder' }}</option><option value="section-band">{{ zh?'有限截面带':'Bounded section' }}</option></select></label>
        <GeometryFields :model-value="current" :fields="fields" @update:model-value="setCurrent" />
      </template>
      </section>
      <section class="roi-view">
      <label>{{ zh?'点云显示':'Point cloud view' }}<select v-model="previewId"><option value="">{{ zh?'未选择':'None' }}</option><option v-for="view in previews" :key="view.id" :value="view.id">{{ view.label }}</option></select></label>
      <CloudViewer v-if="preview" :payload="preview.payload" :project-id="preview.projectId" :edit-rois="validRois" :selected-roi-id="String(current?.roi_id||'')" @roi-change="setCurrent" />
      </section>
      <p v-if="issues.length" role="alert">{{ zh?'待完善':'Incomplete' }}: {{ issues.join(' · ') }}</p>
      <p v-if="referenceIssues.length" role="status">{{ referenceIssues.join(' · ') }}</p>
    </div>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {Plus,Trash2} from '@lucide/vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
import GeometryFields from './GeometryFields.vue'
import {object,copy,newRoi,geometryIssues,roiIssues,type Form,type Field} from './form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;disabled?:boolean;allowInput?:boolean;draftIssues?:(value:unknown)=>string[]}>(),emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue').then(module=>module.default))
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const open=ref(false),draft=ref<Form>({}),selected=ref('target'),previewId=ref('')
const previews=computed(resolve),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const bounds=computed(()=>(Array.isArray(draft.value.bounds)?draft.value.bounds:[]).map(object))
const current=computed(()=>selected.value==='target'&&draft.value.kind==='parameters'?object(draft.value.roi):bounds.value[Number(selected.value)])
const rois=computed(()=>[...(draft.value.kind==='parameters'?[object(draft.value.roi)]:[]),...bounds.value])
const validRois=computed(()=>!roiIssues(rois.value).length?rois.value:[])
const issues=computed(()=>geometryIssues('crop-roi',draft.value))
const referenceIssues=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
const fields=computed<Field[]>(()=>{
  const label=(cn:string,en:string)=>zh.value?cn:en
  const base:Field[]=[{path:'roi_id',label:'ROI ID'},{path:'frame_id',label:label('坐标系 ID','Frame ID')},{path:'length_unit',label:label('长度单位','Length unit'),type:'select',options:['m','mm','um']}]
  const kind=current.value?.kind
  return [...base,...(kind==='box'?[{path:'geometry.center',label:label('中心 XYZ','Center XYZ'),type:'vector'},{path:'geometry.size',label:label('尺寸 XYZ','Size XYZ'),type:'vector'},{path:'geometry.rotation',label:label('旋转矩阵（列为局部轴）','Rotation (local axes in columns)'),type:'matrix'}]:kind==='cylinder'?[{path:'geometry.center',label:label('中心 XYZ','Center XYZ'),type:'vector'},{path:'geometry.axis',label:label('单位轴向量','Unit axis'),type:'vector'},{path:'geometry.radius',label:label('半径','Radius'),type:'number'},{path:'geometry.length',label:label('长度','Length'),type:'number'}]:[{path:'geometry.origin',label:label('截面原点 XYZ','Section origin XYZ'),type:'vector'},{path:'geometry.normal',label:label('单位法向量','Unit normal'),type:'vector'},{path:'geometry.thickness',label:label('厚度','Thickness'),type:'number'},{path:'geometry.bounds_roi_id',label:label('有限边界 ROI','Finite bound ROI'),type:'select',options:rois.value.filter(r=>r!==current.value&&r.roi_id).map(r=>String(r.roi_id))}]) as Field[]]
})
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):{kind:'parameters',roi:newRoi(),bounds:[]};selected.value=draft.value.kind==='parameters'?'target':'0';previewId.value='';open.value=true}
function setCurrent(value:Form){if(selected.value==='target')draft.value={...draft.value,roi:value};else{const next=[...bounds.value];next[Number(selected.value)]=value;draft.value={...draft.value,bounds:next}}}
function changeSource(kind:string){draft.value=kind==='input'?{kind,bounds:bounds.value}:{kind,roi:newRoi(),bounds:bounds.value};selected.value=kind==='input'?'0':'target'}
function changeKind(kind:string){const old=current.value;if(!old)return;setCurrent({...newRoi(kind),roi_id:old.roi_id,frame_id:old.frame_id,length_unit:old.length_unit})}
function add(){draft.value={...draft.value,bounds:[...bounds.value,newRoi()]};selected.value=String(bounds.value.length-1)}
function remove(){draft.value={...draft.value,bounds:bounds.value.filter((_,i)=>i!==Number(selected.value))};selected.value=draft.value.kind==='parameters'?'target':'0'}
function apply(){if(!issues.value.length&&!props.disabled){emit('update:modelValue',copy(draft.value));open.value=false}}
watch(()=>[props.modelValue,props.disabled],()=>{open.value=false})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.geometry-dialog :deep(.confirm-dialog) {width:min(1180px,calc(100vw - 36px))}
.roi-workspace {grid-template-columns:minmax(300px,380px) minmax(0,1fr);align-items:start}
.roi-config,.roi-view {display:grid;gap:12px;min-width:0}
.roi-config {max-height:65dvh;overflow:auto;padding-right:4px}
.roi-view :deep(.cloud-viewer) {height:min(60dvh,600px)}
.roi-workspace>p {grid-column:1/-1}
@media(max-width:900px){.roi-workspace{grid-template-columns:minmax(0,1fr)}.roi-config{max-height:none;overflow:visible}}
</style>
