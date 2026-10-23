<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ title }} · {{ object(modelValue).item_id || '-' }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" class="measurement-dialog" :title="title" size="wide" scroll-body confirm-variant="primary" :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="!!issues.length||disabled" @confirm="apply" @cancel="open=false">
    <div class="geometry-workspace measurement-workspace">
      <section class="measurement-config">
        <label v-if="!height">{{ zh?'测量定义':'Measurement' }}<select :value="settings.kind" @change="changeMode(($event.target as HTMLSelectElement).value)"><option value="directional-planes">{{ zh?'两平面方向距离':'Directional plane distance' }}</option><option value="roi-statistic">{{ zh?'两区域统计差':'ROI statistic difference' }}</option></select></label>
        <GeometryFields v-model="draft" :fields="identityFields" />
        <GeometryFields :model-value="settings" :fields="fields" :suggestions="suggestions" @update:model-value="setSettings" />
        <template v-if="height"><GeometryFields v-model="draft" :fields="searchFields" /><GeometrySettingsEditor :model-value="draft.plane_fit" node-type="custom.metrology3d.fit-plane" @update:model-value="draft=put(draft,'plane_fit',$event)" /></template>
        <label v-if="statistic">{{ zh?'统计量':'Statistic' }}<select :value="object(settings.statistic).kind" @change="changeStatistic(($event.target as HTMLSelectElement).value)"><option value="mean">{{ zh?'均值':'Mean' }}</option><option value="median">{{ zh?'中位数':'Median' }}</option><option value="quantile">{{ zh?'分位数':'Quantile' }}</option></select></label>
        <GeometryFields v-if="statistic&&object(settings.statistic).kind==='quantile'" :model-value="settings" :fields="quantileFields" @update:model-value="setSettings" />
        <p v-if="candidate" role="status">{{ zh?'候选位置':'Candidate position' }}: {{ candidate.join(', ') }}</p>
      </section>
      <section class="measurement-view"><label>{{ zh?'点云显示':'Point cloud view' }}<select v-model="previewId"><option value="">{{ zh?'未选择':'None' }}</option><option v-for="view in previews" :key="view.id" :value="view.id">{{ view.label }}</option></select></label>
        <CloudViewer v-if="preview" :key="preview.id" :payload="preview.payload" :project-id="preview.projectId" :allow-pick="canPick" :candidate="candidate??undefined" @candidate="pick" />
      </section>
      <details class="measurement-quality"><summary>{{ zh?'测量质量':'Measurement quality' }}</summary>
        <GeometryFields :model-value="settings" :fields="qualityFields" @update:model-value="setSettings" />
        <WorkflowLimitRulesEditor :model-value="object(settings.quality_policy).rules" quality @update:model-value="setSettings(put(settings,'quality_policy.rules',$event))" />
      </details>
      <p v-if="issues.length" role="alert">{{ zh?'待完善':'Incomplete' }}: {{ issues.join(' · ') }}</p>
      <p v-if="referenceIssues.length" role="status">{{ referenceIssues.join(' · ') }}</p>
    </div>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import GeometryFields from './GeometryFields.vue'
import GeometrySettingsEditor from './GeometrySettingsEditor.vue'
import {object,copy,put,vector,type Form,type Field} from './form'
import {newMeasurement,newMeasurementMode,measurementIssues,quantileMethods} from './measurement-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources;draftIssues?:(value:unknown)=>string[]}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue').then(m=>m.default))
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),height=computed(()=>props.nodeType.endsWith('height-query'))
const label=(cn:string,en:string)=>zh.value?cn:en
const title=computed(()=>height.value?label('高度查询','Height query'):label('高差测量','Step measurement'))
const open=ref(false),draft=ref<Form>({}),previewId=ref(''),candidate=ref<number[]|null>(null)
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const settings=computed(()=>height.value?draft.value:object(draft.value.mode)),statistic=computed(()=>settings.value.kind==='roi-statistic')
const issues=computed(()=>measurementIssues(height.value,draft.value)),referenceIssues=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
const canPick=computed(()=>!statistic.value&&!!preview.value&&draft.value.frame_id===object(preview.value.payload.spatial).frame_id&&draft.value.length_unit===object(preview.value.payload.spatial).length_unit)
const identityFields=computed<Field[]>(()=>[{path:'item_id',label:label('测量项 ID','Measurement ID')},{path:'frame_id',label:label('坐标系 ID','Frame ID')},{path:'length_unit',label:label('长度单位','Length unit'),type:'select',options:['m','mm','um']}])
const fields=computed<Field[]>(()=>[
  ...(statistic.value?[]:[{path:'reference_feature_id',label:label('基准平面 ID','Reference plane ID')},...(!height.value?[{path:'target_feature_id',label:label('目标平面 ID','Target plane ID')}]:[])]),
  {path:statistic.value?'origin':'query_position',label:statistic.value?label('投影原点 XYZ','Projection origin XYZ'):label('查询位置 XYZ','Query position XYZ'),type:'vector'},
  {path:'direction',label:label('测量方向（单位向量）','Measurement unit direction'),type:'vector'},
  ...(statistic.value?[]:[{path:'support_radius',label:label('支持搜索半径','Support radius'),type:'number'} as Field]),
])
const searchFields=computed<Field[]>(()=>[{path:'search_radius',label:label('目标搜索半径','Target search radius'),type:'number'},{path:'search_interval',label:label('轴向搜索区间（起 / 止）','Axial interval (start / end)'),type:'pair'}])
const quantileFields=computed<Field[]>(()=>[{path:'statistic.probability',label:label('分位概率','Quantile probability'),type:'number'},{path:'statistic.method',label:label('分位方法','Quantile method'),type:'select',options:quantileMethods}])
const qualityFields=computed<Field[]>(()=>[{path:'quality_policy.policy_id',label:label('质量策略 ID','Quality policy ID')},{path:'quality_policy.policy_version',label:label('策略版本','Policy version'),type:'number'}])
const suggestions=computed(()=>{const ids=(props.inputSources?.features??[]).map(s=>object(s.nodeTypeId.endsWith('height-query')?object(s.parameters.settings).plane_fit:s.parameters.settings).feature_id).filter((v):v is string=>typeof v==='string');return {reference_feature_id:ids,target_feature_id:ids}})
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):newMeasurement(height.value);previewId.value='';candidate.value=null;open.value=true}
function setSettings(value:Form){draft.value=height.value?value:{...draft.value,mode:value}}
function changeMode(kind:string){draft.value={...draft.value,mode:newMeasurementMode(kind==='roi-statistic')};candidate.value=null}
function changeStatistic(kind:string){setSettings({...settings.value,statistic:kind==='quantile'?{kind,probability:null,method:null}:{kind}})}
function pick(value:{payload:Record<string,unknown>;xyz:number[]}){
  if(!open.value||props.disabled||!canPick.value||value.payload!==preview.value?.payload||!vector(value.xyz))return
  candidate.value=[...value.xyz];setSettings({...settings.value,query_position:[...value.xyz]})
}
function apply(){if(!issues.value.length&&!props.disabled){emit('update:modelValue',copy(draft.value));open.value=false}}
watch(()=>[props.modelValue,props.disabled,props.nodeType],()=>{open.value=false;candidate.value=null})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value='';candidate.value=null})
watch(()=>[previewId.value,draft.value.frame_id,draft.value.length_unit],()=>{candidate.value=null})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.measurement-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}
.measurement-workspace{grid-template-columns:minmax(280px,360px) minmax(0,1fr);align-items:start}
.measurement-config,.measurement-view{display:grid;gap:12px;min-width:0}
.measurement-quality,.measurement-workspace>p{grid-column:1/-1;min-width:0}
.measurement-quality>summary{cursor:pointer;padding:8px 0;font-weight:600}
.measurement-view :deep(.cloud-viewer){height:min(57dvh,580px)}
@media(max-width:900px){.measurement-workspace{grid-template-columns:minmax(0,1fr)}}
</style>
