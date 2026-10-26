<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ title }} · {{ object(modelValue).feature_id||'-' }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" class="boundary-dialog" :title="title" size="wide" scroll-body confirm-variant="primary" :confirm-label="label('应用','Apply')" :cancel-label="label('取消','Cancel')" :confirm-disabled="disabled||!!issues.length||!!referenceIssues.length" @confirm="apply" @cancel="open=false">
    <div class="geometry-workspace boundary-workspace">
      <section class="boundary-config">
        <GeometryFields v-model="draft" :fields="identityFields" />
        <template v-if="extract">
          <label>{{ label('提取方法','Extraction') }}<select :value="object(draft.method).kind??''" @change="changeMethod(($event.target as HTMLSelectElement).value)"><option value="" disabled>{{ label('选择方法','Select method') }}</option><option value="projection">{{ label('投影边界','Projection boundary') }}</option><option value="section">{{ label('平面截线','Plane section') }}</option><option value="contour">{{ label('显式基准等高线','Configured datum contour') }}</option><option value="pose-contour">{{ label('本次位姿等高线','Current pose contour') }}</option></select></label>
          <label v-if="poseContour">{{ label('等高值来源','Contour height source') }}<select :value="object(object(draft.method).height).kind" @change="draft=put(draft,'method.height',newContourHeight(($event.target as HTMLSelectElement).value))"><option value="fixed">{{ label('固定基准高度','Fixed datum height') }}</option><option value="measurement-ratio">{{ label('本次测量比例','Current measurement ratio') }}</option></select></label>
          <GeometryFields v-model="draft" :fields="methodFields" :suggestions="suggestions" />
          <label v-if="poseContour&&object(object(draft.method).height).kind==='measurement-ratio'">{{ label('沿基准正法向的顺序','Order along positive datum normal') }}<select v-model="object(object(draft.method).height).order"><option :value="null" disabled>{{ label('选择顺序','Select order') }}</option><option value="target-above">{{ label('目标高于基体','Target above reference') }}</option><option value="target-below">{{ label('目标低于基体','Target below reference') }}</option></select></label>
          <label>{{ label('表面 ROI','Surface ROI') }}<RoiEditor :model-value="regionSource(draft.region)" :allow-input="false" @update:model-value="draft=put(draft,'region',regionValue($event))" /></label>
          <div class="target-toolbar"><label>{{ label('目标边界','Target boundary') }}<select v-model="targetIndex"><option v-for="(target,i) in targets" :key="i" :value="i">{{ target.segment_id||`#${i+1}` }}</option></select></label><button :title="label('添加目标','Add target')" @click="addTarget"><Plus :size="16" /></button><button :title="label('删除目标','Remove target')" :disabled="!target" @click="removeTarget"><Trash2 :size="16" /></button></div>
          <template v-if="target"><GeometryFields :model-value="target" :fields="targetFields" @update:model-value="setTarget" /><label><input type="checkbox" :checked="target.closed===true" @change="setTarget({...target,closed:($event.target as HTMLInputElement).checked,role:'unknown'})">{{ label('要求完整闭环','Require complete closed loop') }}</label><label>{{ label('连续实测段 ROI','Continuous measured segment ROI') }}<RoiEditor :model-value="regionSource(target.region)" :allow-input="false" @update:model-value="setTarget({...target,region:regionValue($event)})" /></label></template>
        </template>
        <template v-else>
          <GeometryFields v-model="draft" :fields="selectionFields" :suggestions="suggestions" />
          <fieldset><legend>{{ label('支持段','Support segments') }}</legend><label v-for="segment in availableSegments" :key="segment"><input type="checkbox" :checked="selectedSegments.includes(segment)" @change="toggleSegment(segment,($event.target as HTMLInputElement).checked)">{{ segment }}</label></fieldset>
          <div v-if="!availableSegments.length" class="segment-rows"><label v-for="(segment,i) in selectedSegments" :key="i">{{ label('段 ID','Segment ID') }}<input :value="segment" @input="setSegment(i,($event.target as HTMLInputElement).value)"><button :title="label('删除段','Remove segment')" @click="removeSegment(i)"><Trash2 :size="16" /></button></label><button :title="label('添加段','Add segment')" @click="setSegment(selectedSegments.length,'')"><Plus :size="16" /></button></div>
          <GeometryFields v-model="draft" :fields="fitFields" />
          <EvaluationDirectionEditor v-if="kind==='fit-line'" v-model="draft.positive_direction" :label="label('直线正方向','Positive line direction')" />
        </template>
        <EvaluationEditor v-model="draft.evaluation" :allow-feature="!extract" :pose="poseContour" :suggestions="suggestions" />
      </section>
      <section class="boundary-view"><label>{{ label('点云显示','Point cloud view') }}<select v-model="previewId"><option value="">{{ label('未选择','None') }}</option><option v-for="item in previews" :key="item.id" :value="item.id">{{ item.label }}</option></select></label><CloudViewer v-if="preview" :key="preview.id" :payload="preview.payload" :project-id="preview.projectId" @feature-selection="chooseFeature" /></section>
      <details class="boundary-advanced"><summary>{{ label('支持条件与几何质量','Support and geometry quality') }}</summary><GeometryFields v-if="extract" v-model="draft" :fields="surfaceFields" /><GeometryFields v-if="kind==='fit-circle'" v-model="draft" :fields="solverFields" /><GeometryFields v-model="draft" :fields="qualityFields" /><WorkflowLimitRulesEditor :model-value="object(draft.quality_policy).rules" quality @update:model-value="draft=put(draft,'quality_policy.rules',$event)" /></details>
      <p v-if="issues.length" role="alert">{{ label('待完善','Incomplete') }}: {{ issues.join(' · ') }}</p><p v-if="referenceIssues.length" role="alert">{{ referenceIssues.join(' · ') }}</p>
    </div>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {Plus,Trash2} from '@lucide/vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import {curveItems} from '@/workflows/workflow-editor/point-cloud/boundary-display'
import GeometryFields from './GeometryFields.vue'
import EvaluationEditor from './EvaluationEditor.vue'
import EvaluationDirectionEditor from './EvaluationDirectionEditor.vue'
import {newEvaluation} from './evaluation-form'
import RoiEditor from './RoiEditor.vue'
import {object,copy,put,type Form,type Field} from './form'
import {newBoundarySettings,newBoundaryMethod,newContourHeight,newRegion,regionSource,regionValue,boundaryIssues} from './boundary-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources;draftIssues?:(value:unknown)=>string[]}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),label=(cn:string,en:string)=>zh.value?cn:en
const kind=computed(()=>props.nodeType.split('.').at(-1)!),extract=computed(()=>kind.value==='extract-boundary')
const poseContour=computed(()=>extract.value&&object(draft.value.method).kind==='pose-contour')
const title=computed(()=>extract.value?label('提取边界','Extract boundary'):kind.value==='fit-line'?label('拟合直线','Fit line'):label('拟合圆','Fit circle'))
const open=ref(false),draft=ref<Form>({}),previewId=ref(''),targetIndex=ref(0)
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const targets=computed(()=>(Array.isArray(draft.value.targets)?draft.value.targets:[]).map(object)),target=computed(()=>targets.value[targetIndex.value])
const issues=computed(()=>boundaryIssues(kind.value,draft.value)),referenceIssues=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
const upstream=computed(()=>(props.inputSources?.features??[]).map(s=>({type:s.nodeTypeId,p:object(s.parameters.settings)})))
const suggestions=computed(()=>{
  const planes=upstream.value.filter(s=>s.type.endsWith('fit-plane')||s.type.endsWith('height-query')).map(s=>String((s.type.endsWith('height-query')?object(s.p.plane_fit):s.p).feature_id||''))
  const poses=(props.inputSources?.pose??[]).map(s=>object(s.parameters.settings))
  return {'selection.feature_id':upstream.value.filter(s=>s.type.endsWith('extract-boundary')).map(s=>String(s.p.feature_id||'')), 'method.reference_feature_id':planes,'method.height.reference_feature_id':planes,'method.height.target_feature_id':planes,'method.height.item_id':(props.inputSources?.evidence??[]).map(s=>String(object(s.parameters.settings).item_id||'')),'evaluation.pose_id':poses.map(s=>String(s.pose_id||'')),'evaluation.target_frame_id':poses.map(s=>String(s.target_frame_id||''))}
})
const availableSegments=computed(()=>{const id=object(draft.value.selection).feature_id;const source=upstream.value.find(s=>s.p.feature_id===id);return (Array.isArray(source?.p.targets)?source.p.targets:[]).map(t=>String(object(t).segment_id||'')).filter(Boolean)})
const selectedSegments=computed(()=>(Array.isArray(object(draft.value.selection).segment_ids)?object(draft.value.selection).segment_ids:[]) as string[])
const identityFields=computed<Field[]>(()=>[{path:'feature_id',label:label('特征 ID','Feature ID')}])
const methodFields=computed<Field[]>(()=>poseContour.value?[
  {path:'method.reference_feature_id',label:label('台面基准平面','Datum plane')},
  ...(object(object(draft.value.method).height).kind==='fixed'?[{path:'method.height.value',label:label('有符号基准高度','Signed datum height'),type:'number' as const}]:[
    {path:'method.height.item_id',label:label('本次方向测量量 ID','Current directional measurement ID')},{path:'method.height.reference_feature_id',label:label('基体平面 ID','Reference surface ID')},{path:'method.height.target_feature_id',label:label('目标平面 ID','Target surface ID')},{path:'method.height.ratio',label:label('基体至目标的比例','Reference-to-target ratio'),type:'number' as const},
  ]),{path:'method.numeric_tolerance',label:label('数值距离容差','Numeric distance tolerance'),type:'number'},
]:object(draft.value.method).kind==='section'?[{path:'method.origin',label:label('截面原点','Section origin'),type:'vector'},{path:'method.normal',label:label('截面单位法向','Section unit normal'),type:'vector'},{path:'method.numeric_tolerance',label:label('数值距离容差','Numeric distance tolerance'),type:'number'}]:object(draft.value.method).kind==='contour'?[{path:'method.reference_feature_id',label:label('基准平面','Datum plane')},{path:'method.positive_normal',label:label('正法向','Positive normal'),type:'vector'},{path:'method.min_orientation_cosine',label:label('最小方向余弦','Minimum orientation cosine'),type:'number'},{path:'method.height',label:label('有符号高度','Signed height'),type:'number'},{path:'method.numeric_tolerance',label:label('数值距离容差','Numeric distance tolerance'),type:'number'}]:[])
const targetFields=computed<Field[]>(()=>[{path:'segment_id',label:label('目标段 ID','Target segment ID')},{path:'role',label:label('边界角色','Boundary role'),type:'select',options:target.value?.closed?['outer','inner','unknown']:['open','unknown']}])
const selectionFields=computed<Field[]>(()=>[{path:'selection.feature_id',label:label('边界特征','Boundary feature')}])
const fitFields=computed<Field[]>(()=>kind.value==='fit-line'?[{path:'min_orientation_cosine',label:label('最小方向余弦','Minimum orientation cosine'),type:'number'}]:[{path:'radius_range',label:label('半径搜索范围','Radius search range'),type:'pair'},{path:'max_arc_step',label:label('相邻支持最大转角 rad','Maximum adjacent angle rad'),type:'number'}])
const surfaceFields=computed<Field[]>(()=>[['alpha_radius','支持圆半径','Support circle radius'],['max_edge_length','最大连接边长','Maximum edge length'],['max_normal_step','最大法向高度跳变','Maximum normal step'],['min_projected_area','最小投影三角面积','Minimum projected triangle area']].map(([key,cn,en])=>({path:`surface.${key}`,label:label(cn!,en!),type:'number'})))
const solverFields=computed<Field[]>(()=>['ftol','xtol','gtol','max_nfev'].map(key=>({path:`solver.${key}`,label:key,type:'number'} as Field)).concat([{path:'solver.x_scale',label:label('求解变量尺度','Solver variable scale'),type:'vector'}]))
const qualityFields=computed<Field[]>(()=>[{path:'quality_policy.policy_id',label:label('质量策略 ID','Quality policy ID')},{path:'quality_policy.policy_version',label:label('策略版本','Policy version'),type:'number'}])
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):newBoundarySettings(kind.value);targetIndex.value=0;previewId.value='';open.value=true}
function changeMethod(kind:string){const wasPose=poseContour.value;draft.value={...draft.value,method:newBoundaryMethod(kind),evaluation:kind==='pose-contour'?newEvaluation('pose',draft.value.evaluation):wasPose?newEvaluation('configured',draft.value.evaluation):draft.value.evaluation};previewId.value=''}
function addTarget(){draft.value={...draft.value,targets:[...targets.value,{segment_id:'',closed:false,role:'unknown',region:newRegion()}]};targetIndex.value=targets.value.length-1}
function removeTarget(){draft.value={...draft.value,targets:targets.value.filter((_,i)=>i!==targetIndex.value)};targetIndex.value=0}
function setTarget(value:Form){const next=[...targets.value];next[targetIndex.value]=value;draft.value={...draft.value,targets:next}}
function toggleSegment(segment:string,enabled:boolean){draft.value=put(draft.value,'selection.segment_ids',enabled?[...selectedSegments.value,segment]:selectedSegments.value.filter(s=>s!==segment))}
function setSegment(index:number,value:string){const next=[...selectedSegments.value];next[index]=value;draft.value=put(draft.value,'selection.segment_ids',next)}
function removeSegment(index:number){draft.value=put(draft.value,'selection.segment_ids',selectedSegments.value.filter((_,i)=>i!==index))}
function chooseFeature(value:{payload:Form;featureId:string;segmentId:string}){if(!open.value||props.disabled||extract.value||value.payload!==preview.value?.payload)return;const source=upstream.value.find(s=>s.p.feature_id===value.featureId&&s.type.endsWith('extract-boundary'));if(!source||!curveItems(value.payload).some(f=>f.kind==='boundary'&&f.valid&&f.feature_id===value.featureId))return;draft.value=put(draft.value,'selection',{feature_id:value.featureId,segment_ids:value.segmentId?[value.segmentId]:[]})}
function apply(){if(!issues.value.length&&!referenceIssues.value.length&&!props.disabled){emit('update:modelValue',copy(draft.value));open.value=false}}
watch(()=>[props.modelValue,props.disabled,props.nodeType],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
watch(()=>object(draft.value.selection).feature_id,(next,previous)=>{if(open.value&&next!==previous&&availableSegments.value.length)draft.value=put(draft.value,'selection.segment_ids',selectedSegments.value.filter(s=>availableSegments.value.includes(s)))})
watch(()=>JSON.stringify(props.inputSources),()=>{open.value=false;previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.boundary-config fieldset label{display:flex;align-items:center;gap:6px}.boundary-config input[type=checkbox]{width:16px;height:16px;min-width:16px;flex:none}.segment-rows{display:grid;gap:6px}.segment-rows label{display:grid;grid-template-columns:minmax(0,1fr) 30px;gap:6px}.segment-rows label input{grid-column:1;min-width:0}.segment-rows button{width:30px;height:30px;display:grid;place-items:center}
.boundary-dialog :deep(.confirm-dialog){width:min(1260px,calc(100vw - 36px))}.boundary-workspace{grid-template-columns:minmax(280px,370px) minmax(0,1fr);align-items:start}.boundary-config,.boundary-view{display:grid;gap:10px;min-width:0}.boundary-view :deep(.cloud-viewer){height:min(60dvh,660px)}.boundary-advanced,.boundary-workspace>p{grid-column:1/-1}.target-toolbar{display:flex;gap:8px;align-items:end;flex-wrap:wrap}.target-toolbar button{display:grid;place-items:center;width:30px;height:30px}fieldset{border:1px solid var(--am-border);display:flex;gap:10px;flex-wrap:wrap}details>summary{padding:8px 0;cursor:pointer;font-weight:600}@media(max-width:900px){.boundary-workspace{grid-template-columns:minmax(0,1fr)}}
</style>
