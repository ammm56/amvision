<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ label('高度图网格','Height map grid') }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="geometry-dialog" :title="label('点云转高度图','Cloud to height map')" size="wide" scroll-body :confirm-label="label('应用','Apply')" :cancel-label="label('取消','Cancel')" :confirm-disabled="disabled||issues.length>0" @confirm="apply" @cancel="open=false">
      <MetrologyWorkspace>
        <template #parameters>
          <label>{{ label('坐标来源','Coordinate source') }}<select aria-label="Coordinate source" :value="frame.kind" @change="changeFrame"><option value="current-frame">{{ label('当前点云坐标','Current cloud frame') }}</option><option value="pose-frame">{{ label('输入本次位姿','Current input pose') }}</option></select></label>
          <GeometryFields v-model="draft" :fields="frameFields" />
          <label>{{ label('聚合方法','Aggregation') }}<select v-model="draft.aggregation" aria-label="Aggregation"><option disabled value="">{{ label('选择方法','Select method') }}</option><option value="minimum">{{ label('最小值','Minimum') }}</option><option value="maximum">{{ label('最大值','Maximum') }}</option><option value="mean">{{ label('平均值','Mean') }}</option><option value="median">{{ label('中位数','Median') }}</option></select></label>
          <fieldset><legend>{{ label('固定物理网格','Fixed physical grid') }}</legend><GeometryFields v-model="draft" :fields="gridFields" /></fieldset>
          <p v-if="issues.length" role="alert">{{ label('未完成或无效字段','Incomplete or invalid fields') }}: {{ issues.map(v=>issueLabel[v]??v).join(' · ') }}</p>
        </template>
        <template #view="{presentation}"><section class="height-view"><CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" /><CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" /></section></template>
      </MetrologyWorkspace>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import GeometryFields from './GeometryFields.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import {copy,object,type Form,type Field} from './form'
import {newHeightMap,heightMapIssues} from './height-map-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(),label=(cn:string,en:string)=>locale.value==='zh-CN'?cn:en
const open=ref(false),draft=ref<Form>(newHeightMap()),initial=ref(''),previewId=ref('')
const frame=computed(()=>object(draft.value.frame)),issues=computed(()=>heightMapIssues(draft.value))
const issueLabel=computed<Record<string,string>>(()=>({frame:label('坐标系','Frame'),pose:label('位姿','Pose'),unit:label('单位','Unit'),aggregation:label('聚合','Aggregation'),size:label('行列数','Rows / columns'),grid:label('原点与步距','Origin / spacing'),axes:label('正交右手单位方向','Orthonormal right-handed axes'),precision:label('格边界精度','Grid precision')}))
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value)),changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
const field=(path:string,cn:string,en:string,type?:Field['type'],options?:string[]):Field=>({path,label:label(cn,en),type,options})
const frameFields=computed(()=>[...(frame.value.kind==='current-frame'?[field('frame.frame_id','输入坐标系','Input frame')]:[field('frame.pose_id','位姿 ID','Pose ID'),field('frame.target_frame_id','目标坐标系','Target frame')]),field('length_unit','长度单位','Length unit','select',['m','mm','um'])])
const gridFields=computed(()=>[field('width','列数','Columns','number'),field('height','行数','Rows','number'),field('grid.origin','首格零高度中心','First cell zero-height center','vector'),field('grid.column_direction','列单位方向','Column unit direction','vector'),field('grid.row_direction','行单位方向','Row unit direction','vector'),field('grid.height_direction','高度单位方向','Height unit direction','vector'),field('grid.column_step','列步距','Column spacing','number'),field('grid.row_step','行步距','Row spacing','number')])
function show(){draft.value=props.modelValue&&typeof props.modelValue==='object'?copy(object(props.modelValue)):newHeightMap();initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function changeFrame(e:Event){draft.value={...draft.value,frame:(e.target as HTMLSelectElement).value==='pose-frame'?{kind:'pose-frame',pose_id:'',target_frame_id:''}:{kind:'current-frame',frame_id:''}}}
function apply(){if(!props.disabled&&!issues.value.length){emit('update:modelValue',copy(draft.value));open.value=false}}
watch([()=>props.modelValue,()=>props.nodeType,()=>props.disabled,()=>JSON.stringify(props.inputSources)],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
label{display:grid;gap:6px;margin:10px 0;min-width:0}select{width:100%;min-width:0;background:var(--am-input);color:var(--am-text);border:1px solid var(--am-border);border-radius:4px;padding:6px}fieldset{margin:12px 0;padding:10px;border:1px solid var(--am-border);min-width:0}legend{font-size:13px}.height-view{display:grid;gap:10px;min-width:0}[role=alert]{font-size:12px;color:var(--am-danger)}.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}
</style>
