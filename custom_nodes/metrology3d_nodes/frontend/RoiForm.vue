<template><section class="roi-config">
      <div class="geometry-toolbar"><label v-if="allowInput !== false">{{ zh?'ROI 来源':'ROI source' }}<select :value="draft.kind" @change="changeSource(($event.target as HTMLSelectElement).value)"><option value="parameters">{{ zh?'节点参数':'Node parameters' }}</option><option value="input">{{ zh?'输入端口':'Input port' }}</option></select></label>
        <label>{{ zh?'编辑对象':'Edit ROI' }}<select v-model="selected"><option v-if="draft.kind==='parameters'" value="target">{{ zh?'目标 ROI':'Target ROI' }}</option><option v-for="(roi,i) in bounds" :key="i" :value="String(i)">{{ String(roi.roi_id||`#${i+1}`) }}</option></select></label>
        <button :title="zh?'添加有限边界':'Add finite bound'" @click="add"><Plus :size="18" /></button><button :title="referencedBy.length?(zh?'被引用：':'Referenced by: ')+referencedBy.join(', '):(zh?'删除边界':'Remove bound')" :disabled="selected==='target'||!current||!!referencedBy.length" @click="remove"><Trash2 :size="18" /></button>
      </div>
      <template v-if="current"><label>{{ zh?'几何类型':'Geometry' }}<select :value="current.kind" @change="changeKind(($event.target as HTMLSelectElement).value)"><option value="box">{{ zh?'有向盒':'Oriented box' }}</option><option value="cylinder">{{ zh?'有限圆柱':'Finite cylinder' }}</option><option value="section-band">{{ zh?'有限截面带':'Bounded section' }}</option><option value="union">{{ zh?'并集':'Union' }}</option></select></label>
        <GeometryFields :model-value="current" :fields="fields" @update:model-value="setCurrent" />
        <fieldset v-if="current.kind==='union'" class="roi-members"><legend>{{ zh?'成员 ROI':'Member ROIs' }}</legend>
          <label v-for="id in memberOptions" :key="id"><input type="checkbox" :value="id" :checked="members.includes(id)" @change="toggleMember(id,($event.target as HTMLInputElement).checked)" />{{ id }}<span v-if="!rois.some(r=>r.roi_id===id)">{{ zh?'（缺失）':' (missing)' }}</span></label>
        </fieldset>
      </template>

</section></template>
<script setup lang="ts">
import {computed,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {Plus,Trash2} from '@lucide/vue'
import GeometryFields from './GeometryFields.vue'
import {object,newRoi,roiIssues,type Form,type Field} from './form'
import {roiDependencies,roiDependencyClosure,renameRoiReference} from '@/workflows/workflow-editor/point-cloud/roi-graph'
const props=defineProps<{modelValue:Form;allowInput?:boolean}>()
const emit=defineEmits<{'update:modelValue':[value:Form];view:[value:{rois:Form[];selectedId:string}]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const currentDraft=ref(props.modelValue)
const draft=computed({get:()=>currentDraft.value,set:(value:Form)=>{currentDraft.value=value;emit('update:modelValue',value)}})
watch(()=>props.modelValue,value=>{currentDraft.value=value})
const selected=ref(props.modelValue.kind==='parameters'?'target':'0')
const bounds=computed(()=>(Array.isArray(draft.value.bounds)?draft.value.bounds:[]).map(object))
const current=computed(()=>selected.value==='target'&&draft.value.kind==='parameters'?object(draft.value.roi):bounds.value[Number(selected.value)])
const rois=computed(()=>[...(draft.value.kind==='parameters'?[object(draft.value.roi)]:[]),...bounds.value])
const members=computed(()=>current.value?roiDependencies(current.value):[])
const memberOptions=computed(()=>[...new Set([...rois.value.filter(r=>r!==current.value&&r.roi_id).map(r=>String(r.roi_id)),...members.value])])
const referencedBy=computed(()=>current.value?rois.value.filter(r=>r!==current.value&&roiDependencies(r).includes(String(current.value!.roi_id))).map(r=>String(r.roi_id)):[])
const validRois=computed(()=>{
  if(roiIssues(rois.value).length)return []
  const roots=[String(current.value?.roi_id||'')]
  if(draft.value.kind==='parameters')roots.push(String(object(draft.value.roi).roi_id))
  return roiDependencyClosure(rois.value,roots)
})
const fields=computed<Field[]>(()=>{
  const label=(cn:string,en:string)=>zh.value?cn:en
  const base:Field[]=[{path:'roi_id',label:'ROI ID'},{path:'frame_id',label:label('坐标系 ID','Frame ID')},{path:'length_unit',label:label('长度单位','Length unit'),type:'select',options:['m','mm','um']}]
  const kind=current.value?.kind
  if(kind==='union')return base
  return [...base,...(kind==='box'?[{path:'geometry.center',label:label('中心 XYZ','Center XYZ'),type:'vector'},{path:'geometry.size',label:label('尺寸 XYZ','Size XYZ'),type:'vector'},{path:'geometry.rotation',label:label('旋转矩阵（列为局部轴）','Rotation (local axes in columns)'),type:'matrix'}]:kind==='cylinder'?[{path:'geometry.center',label:label('中心 XYZ','Center XYZ'),type:'vector'},{path:'geometry.axis',label:label('单位轴向量','Unit axis'),type:'vector'},{path:'geometry.radius',label:label('半径','Radius'),type:'number'},{path:'geometry.length',label:label('长度','Length'),type:'number'}]:[{path:'geometry.origin',label:label('截面原点 XYZ','Section origin XYZ'),type:'vector'},{path:'geometry.normal',label:label('单位法向量','Unit normal'),type:'vector'},{path:'geometry.thickness',label:label('厚度','Thickness'),type:'number'},{path:'geometry.bounds_roi_id',label:label('有限边界 ROI','Finite bound ROI'),type:'select',options:rois.value.filter(r=>r!==current.value&&r.roi_id).map(r=>String(r.roi_id))}]) as Field[]].map(f=>({...f,unit:['geometry.center','geometry.size','geometry.origin','geometry.radius','geometry.length','geometry.thickness'].includes(f.path)?String(current.value?.length_unit??''):undefined}))
})
function setCurrent(value:Form){
  const previous=current.value?.roi_id
  let next:Form=selected.value==='target'?{...draft.value,roi:value}:{...draft.value,bounds:bounds.value.map((r,i)=>i===Number(selected.value)?value:r)}
  if(typeof previous==='string'&&previous&&typeof value.roi_id==='string'&&value.roi_id&&previous!==value.roi_id&&!rois.value.some(r=>r!==current.value&&r.roi_id===value.roi_id)){
    next={...next,...(next.kind==='parameters'?{roi:renameRoiReference(object(next.roi),previous,value.roi_id)}:{}),bounds:(Array.isArray(next.bounds)?next.bounds:[]).map(r=>renameRoiReference(object(r),previous,value.roi_id as string))}
  }
  draft.value=next
}
function toggleMember(id:string,checked:boolean){if(current.value)setCurrent({...current.value,geometry:{roi_ids:checked?[...members.value,id]:members.value.filter(v=>v!==id)}})}
function changeSource(kind:string){draft.value=kind==='input'?{kind,bounds:bounds.value}:{kind,roi:newRoi(),bounds:bounds.value};selected.value=kind==='input'?'0':'target'}
function changeKind(kind:string){const old=current.value;if(!old)return;setCurrent({...newRoi(kind),roi_id:old.roi_id,frame_id:old.frame_id,length_unit:old.length_unit})}
function add(){const space=current.value??rois.value[0];draft.value={...draft.value,bounds:[...bounds.value,{...newRoi(),...(space?{frame_id:space.frame_id,length_unit:space.length_unit}:{})}]};selected.value=String(bounds.value.length-1)}
function remove(){if(referencedBy.value.length||selected.value==='target')return;draft.value={...draft.value,bounds:bounds.value.filter((_,i)=>i!==Number(selected.value))};selected.value=draft.value.kind==='parameters'?'target':'0'}

watch(()=>[validRois.value,current.value?.roi_id],()=>emit('view',{rois:validRois.value,selectedId:String(current.value?.roi_id??'')}),{immediate:true,deep:true})
defineExpose({setCurrent})
</script>
<style src="./editor.css" scoped></style>
<style scoped>.roi-config{display:grid;gap:12px;min-width:0}.roi-members{min-width:0;border:1px solid var(--am-border);padding:10px;display:grid;gap:8px}.roi-members label{display:flex;align-items:center;gap:8px;overflow-wrap:anywhere}</style>
