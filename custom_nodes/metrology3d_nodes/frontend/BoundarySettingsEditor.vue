<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ title }} · {{ object(modelValue).feature_id||'-' }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" class="boundary-dialog" :title="title" size="wide" scroll-body confirm-variant="primary" :confirm-label="label('应用','Apply')" :cancel-label="label('取消','Cancel')" :confirm-disabled="disabled||!!issues.length" @confirm="apply" @cancel="open=false">
    <MetrologyWorkspace>
      <template #parameters>
      <section class="boundary-config">
        <GeometryFields v-model="draft" :fields="identityFields" />
        <template v-if="extract">
          <label>{{ label('提取方法','Extraction') }}<select :value="object(draft.method).kind??''" @change="changeMethod(($event.target as HTMLSelectElement).value)"><option value="" disabled>{{ label('选择方法','Select method') }}</option><option value="projection">{{ label('投影边界','Projection boundary') }}</option><option value="section">{{ label('平面截线','Plane section') }}</option><option value="contour">{{ label('显式基准等高线','Configured datum contour') }}</option><option value="pose-contour">{{ label('本次位姿等高线','Current pose contour') }}</option><option value="visible-envelope">{{ label('可见包络（栅格剖面）','Visible envelope (grid profiles)') }}</option></select></label>
          <label v-if="poseContour">{{ label('等高值来源','Contour height source') }}<select :value="object(object(draft.method).height).kind" @change="draft=put(draft,'method.height',newContourHeight(($event.target as HTMLSelectElement).value))"><option value="fixed">{{ label('固定基准高度','Fixed datum height') }}</option><option value="measurement-ratio">{{ label('本次测量比例','Current measurement ratio') }}</option></select></label>
          <GeometryFields v-model="draft" :fields="methodFields" :suggestions="suggestions" />
          <label v-if="poseContour&&object(object(draft.method).height).kind==='measurement-ratio'">{{ label('沿基准正法向的顺序','Order along positive datum normal') }}<select v-model="object(object(draft.method).height).order"><option :value="null" disabled>{{ label('选择顺序','Select order') }}</option><option value="target-above">{{ label('目标高于基体','Target above reference') }}</option><option value="target-below">{{ label('目标低于基体','Target below reference') }}</option></select></label>
          <label>{{ label('编辑 ROI','Edit ROI') }}<select v-model="roiScope"><option value="surface">{{ label('表面 ROI','Surface ROI') }}</option><option v-if="target" value="target">{{ label('实测支持 ROI','Measured support ROI') }}</option></select></label>
          <details><summary>{{ roiScope==='target'?label('实测支持 ROI','Measured support ROI'):label('表面 ROI','Surface ROI') }}</summary><RoiForm ref="roiForm" :key="roiScope+':'+targetIndex" :model-value="roiSource" :allow-input="false" :can-view="!!preview&&!!matchingRois.length" :visibility-scope="visibilityScope" @update:model-value="setRegion" @view="roiView=$event" @visibility="hiddenRois=$event" /></details>
          <EnvelopeSettingsEditor v-if="visibleEnvelope" :model-value="object(object(draft.method).envelope)" @update:model-value="draft=put(draft,'method.envelope',$event)" />
          <div v-else class="target-toolbar"><label>{{ label('目标边界','Target boundary') }}<select v-model="targetIndex"><option v-for="(target,i) in targets" :key="i" :value="i">{{ target.group_id||target.segment_id||`#${i+1}` }}</option></select></label><button :title="label('添加目标','Add target')" @click="addTarget"><Plus :size="16" /></button><button :title="label('删除目标','Remove target')" :disabled="!target" @click="removeTarget"><Trash2 :size="16" /></button></div>
          <template v-if="target">
            <label>{{ label('目标方式','Target mode') }}<select :value="'group_id' in target?'group':'single'" @change="changeTarget(($event.target as HTMLSelectElement).value)"><option value="single">{{ label('单连续段','Single continuous segment') }}</option><option value="group">{{ label('部分圆弧片段组','Partial circular arc group') }}</option></select></label>
            <GeometryFields :model-value="target" :fields="targetFields" @update:model-value="setTarget" />
            <label v-if="!('group_id' in target)"><input type="checkbox" :checked="target.closed===true" @change="setTarget({...target,closed:($event.target as HTMLInputElement).checked,role:'unknown'})">{{ label('要求完整闭环','Require complete closed loop') }}</label>
            <ArcSettingsForm v-if="'group_id' in target" :model-value="target.arc" band :unit="String(object(draft.evaluation).length_unit??'')" v-model:handle="arcHandle" :available="!!arcEdit" @update:model-value="setTarget({...target,arc:$event})" />
            <details v-if="'group_id' in target"><summary>{{ label('每个片段的质量条件','Individual fragment quality') }}</summary><GeometryFields :model-value="object(target.fragment_quality_policy)" :fields="fragmentQualityFields" @update:model-value="setTarget({...target,fragment_quality_policy:$event})" /><WorkflowLimitRulesEditor :model-value="object(target.fragment_quality_policy).rules" quality @update:model-value="setTarget(put(target,'fragment_quality_policy.rules',$event))" /></details>
          </template>
        </template>
        <template v-else>
          <GeometryFields v-model="draft" :fields="selectionFields" :suggestions="suggestions" />
          <BoundarySelectionEditor v-model="draft.selection" :segments="availableSegments" :groups="availableGroups" />
          <GeometryFields v-model="draft" :fields="fitFields" />
          <template v-if="kind==='fit-circle'"><label>{{ label('拟合方法','Fit method') }}<select :value="object(draft.robust).kind??'linear'" @change="draft=changeCircleFit(draft,($event.target as HTMLSelectElement).value)"><option value="linear">{{ label('等权几何最小二乘','Equal-weight geometric least squares') }}</option><option value="angular-soft-l1">{{ label('角区均衡稳健拟合','Angular-balanced robust fit') }}</option><option value="arc-length-soft-l1">{{ label('连续边长加权稳健拟合','Continuous-edge-length robust fit') }}</option></select></label><GeometryFields v-if="draft.robust" v-model="draft" :fields="robustFields" /></template>
          <EvaluationDirectionEditor v-if="kind==='fit-line'" v-model="draft.positive_direction" :label="label('直线正方向','Positive line direction')" />
        </template>
        <ArcSettingsForm v-if="!extract&&kind==='fit-circle'&&draft.robust" :model-value="draft.robust" :band="false" :unit="String(object(draft.evaluation).length_unit??'')" v-model:handle="arcHandle" :available="!!arcEdit" @update:model-value="draft=put(draft,'robust',$event)" />
        <EvaluationEditor v-model="draft.evaluation" :allow-feature="!extract" :pose="poseContour" :suggestions="suggestions" />
      </section>
      </template>
      <template #view="{presentation}">
      <section class="boundary-view"><CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" /><CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" :edit-rois="matchingRois" :hidden-roi-ids="hiddenRois" :roi-scope="visibilityScope" :selected-roi-id="arcEdit?undefined:roiView.selectedId" :edit-arc="arcEdit??undefined" @arc-change="changeArc" @roi-change="changeRoi" :allow-pick="canPickSeed" :candidate="candidate??undefined" @candidate="pickSeed" @feature-selection="chooseFeature" /><p v-if="candidate" role="status">{{ label('种子窗口候选中心','Candidate seed center') }}: {{ candidate.join(', ') }}</p></section>
      </template>
      <template #advanced>
      <details class="boundary-advanced"><summary>{{ label('支持条件与几何质量','Support and geometry quality') }}</summary><GeometryFields v-if="extract&&!visibleEnvelope" v-model="draft" :fields="surfaceFields" /><GeometryFields v-if="kind==='fit-circle'" v-model="draft" :fields="solverFields" /><GeometryFields v-model="draft" :fields="qualityFields" /><WorkflowLimitRulesEditor :model-value="object(draft.quality_policy).rules" quality @update:model-value="draft=put(draft,'quality_policy.rules',$event)" /></details>
      </template>
      <template #issues><p v-if="issues.length" role="alert">{{ label('待完善','Incomplete') }}: {{ issues.join(' · ') }}</p><p v-if="referenceIssues.length" role="status">{{ referenceIssues.join(' · ') }}</p></template>
    </MetrologyWorkspace>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,shallowRef,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import {Plus,Trash2} from '@lucide/vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import {curveItems} from '@/workflows/workflow-editor/point-cloud/boundary-display'
import GeometryFields from './GeometryFields.vue'
import EvaluationEditor from './EvaluationEditor.vue'
import EvaluationDirectionEditor from './EvaluationDirectionEditor.vue'
import EnvelopeSettingsEditor from './EnvelopeSettingsEditor.vue'
import BoundarySelectionEditor from './BoundarySelectionEditor.vue'
import ArcSettingsForm from './ArcSettingsForm.vue'
import {boundaryArcEdit} from './arc-form'
import type {ArcHandle,ArcValues} from '@/workflows/workflow-editor/point-cloud/arc-edit'
import {newFragmentTarget,changeCircleFit} from './circle-form'
import {dimensionFeatureChoices} from './dimension-form'
import {normalizeLimitRule} from '@/workflows/workflow-editor/parameters/limit-rules'
import {newEvaluation} from './evaluation-form'
import {candidateUV} from './pose-pick'
import RoiForm from './RoiForm.vue'
import {object,copy,put,type Form,type Field} from './form'
import {newBoundarySettings,newBoundaryMethod,newContourHeight,newRegion,regionSource,regionValue,boundaryIssues} from './boundary-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources;draftIssues?:(value:unknown)=>string[]}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),label=(cn:string,en:string)=>zh.value?cn:en
const kind=computed(()=>props.nodeType.split('.').at(-1)!),extract=computed(()=>kind.value==='extract-boundary')
const visibleEnvelope=computed(()=>extract.value&&object(draft.value.method).kind==='visible-envelope')
const poseContour=computed(()=>extract.value&&['pose-contour','visible-envelope'].includes(String(object(draft.value.method).kind)))
const title=computed(()=>extract.value?label('提取边界','Extract boundary'):kind.value==='fit-line'?label('拟合直线','Fit line'):label('拟合圆','Fit circle'))
const open=ref(false),draft=ref<Form>({}),previewId=ref(''),targetIndex=ref(0)
const candidate=ref<number[]|null>(null)
const roiScope=ref('surface'),roiForm=ref<InstanceType<typeof RoiForm>>(),roiView=ref<{rois:Form[];selectedId:string}>({rois:[],selectedId:''})
const hiddenRois=shallowRef<ReadonlySet<string>>(new Set())
const visibilityScope=computed(()=>JSON.stringify([state().runId,previewId.value,preview.value?.payload.observation_id,preview.value?.payload.spatial,roiScope.value,targetIndex.value,object(draft.value.method).kind]))
function changeRoi(value:Form){if(open.value&&!props.disabled&&preview.value&&matchingRois.value.length&&value.roi_id===roiView.value.selectedId)roiForm.value?.setCurrent(value)}
const initial=ref(''),changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
const roiRegion=computed(()=>roiScope.value==='target'&&target.value?target.value.region:draft.value.region)
const roiSource=computed(()=>regionSource(roiRegion.value))
const matchingRois=computed(()=>{const s=object(preview.value?.payload.spatial);return extract.value&&roiView.value.rois.every(r=>r.frame_id===s.frame_id&&r.length_unit===s.length_unit)?roiView.value.rois:[]})
function setRegion(value:Form){if(roiScope.value==='target'&&target.value)setTarget({...target.value,region:regionValue(value)});else draft.value=put(draft.value,'region',regionValue(value))}
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const previewFrame=computed(()=>object(object(preview.value?.payload.geometry).frame))
const seedSize=computed(()=>{const seed=object(object(object(draft.value.method).envelope).selection),lo=seed.seed_min,hi=seed.seed_max;if(!Array.isArray(lo)||!Array.isArray(hi)||lo.length!==2||hi.length!==2||![...lo,...hi].every(v=>typeof v==='number'&&Number.isFinite(v)))return null;const size=hi.map((v,i)=>v-lo[i]);return size.every(v=>v>0)?size:null})
const canPickSeed=computed(()=>{const e=object(draft.value.evaluation),s=object(preview.value?.payload.spatial),f=previewFrame.value;return visibleEnvelope.value&&!!seedSize.value&&!!preview.value&&e.frame_id===s.frame_id&&e.length_unit===s.length_unit&&f.state==='found'&&f.pose_id===e.pose_id&&f.target_frame_id===e.target_frame_id})
const targets=computed(()=>(Array.isArray(draft.value.targets)?draft.value.targets:[]).map(object)),target=computed(()=>targets.value[targetIndex.value])
const arcHandle=ref<ArcHandle|'none'>('none')
const arcEdit=computed(()=>!open.value||props.disabled||arcHandle.value==='none'?null:boundaryArcEdit(kind.value,draft.value,target.value,preview.value?.payload,props.inputSources??{},state().runId,arcHandle.value))
function changeArc(event:{payload:Form;key:string;values:ArcValues}){if(!open.value||props.disabled||event.payload!==preview.value?.payload||event.key!==arcEdit.value?.key)return;if(extract.value&&target.value)setTarget({...target.value,arc:{...object(target.value.arc),...event.values}});else draft.value=put(draft.value,'robust',{...object(draft.value.robust),...event.values})}
const issues=computed(()=>boundaryIssues(kind.value,draft.value)),referenceIssues=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
const upstream=computed(()=>(props.inputSources?.features??[]).map(s=>({type:s.nodeTypeId,p:object(s.parameters.settings)})))
const boundaryChoices=computed(()=>dimensionFeatureChoices(props.inputSources??{}).filter(c=>c.kind==='boundary'))
const suggestions=computed(()=>{
  const planes=upstream.value.filter(s=>s.type.endsWith('fit-plane')||s.type.endsWith('height-query')).map(s=>String((s.type.endsWith('height-query')?object(s.p.plane_fit):s.p).feature_id||''))
  const poses=(props.inputSources?.pose??[]).map(s=>object(s.parameters.settings))
  return {'selection.feature_id':boundaryChoices.value.map(c=>c.id), 'method.reference_feature_id':planes,'method.height.reference_feature_id':planes,'method.height.target_feature_id':planes,'method.height.item_id':(props.inputSources?.evidence??[]).map(s=>String(object(s.parameters.settings).item_id||'')),'evaluation.pose_id':poses.map(s=>String(s.pose_id||'')),'evaluation.target_frame_id':poses.map(s=>String(s.target_frame_id||''))}
})
const availableSegments=computed(()=>boundaryChoices.value.find(c=>c.id===object(draft.value.selection).feature_id)?.segments??[])
const availableGroups=computed(()=>boundaryChoices.value.find(c=>c.id===object(draft.value.selection).feature_id)?.groups??[])
const identityFields=computed<Field[]>(()=>[{path:'feature_id',label:label('特征 ID','Feature ID')}])
const methodFields=computed<Field[]>(()=>poseContour.value?[
  {path:'method.reference_feature_id',label:label('台面基准平面','Datum plane')},
  ...(object(object(draft.value.method).height).kind==='fixed'?[{path:'method.height.value',label:label('有符号基准高度','Signed datum height'),type:'number' as const}]:[
    {path:'method.height.item_id',label:label('本次方向测量量 ID','Current directional measurement ID')},{path:'method.height.reference_feature_id',label:label('基体平面 ID','Reference surface ID')},{path:'method.height.target_feature_id',label:label('目标平面 ID','Target surface ID')},{path:'method.height.ratio',label:label('基体至目标的比例','Reference-to-target ratio'),type:'number' as const},
  ]),{path:'method.numeric_tolerance',label:label('数值距离容差','Numeric distance tolerance'),type:'number'},
]:object(draft.value.method).kind==='section'?[{path:'method.origin',label:label('截面原点','Section origin'),type:'vector'},{path:'method.normal',label:label('截面单位法向','Section unit normal'),type:'vector'},{path:'method.numeric_tolerance',label:label('数值距离容差','Numeric distance tolerance'),type:'number'}]:object(draft.value.method).kind==='contour'?[{path:'method.reference_feature_id',label:label('基准平面','Datum plane')},{path:'method.positive_normal',label:label('正法向','Positive normal'),type:'vector'},{path:'method.min_orientation_cosine',label:label('最小方向余弦','Minimum orientation cosine'),type:'number'},{path:'method.height',label:label('有符号高度','Signed height'),type:'number'},{path:'method.numeric_tolerance',label:label('数值距离容差','Numeric distance tolerance'),type:'number'}]:[])
const targetFields=computed<Field[]>(()=>target.value&&'group_id' in target.value?[
  {path:'group_id',label:label('目标组 ID','Target group ID')},
]:[{path:'segment_id',label:label('目标段 ID','Target segment ID')},{path:'role',label:label('边界角色','Boundary role'),type:'select',options:target.value?.closed?['outer','inner','unknown']:['open','unknown']}])
const fragmentQualityFields=computed<Field[]>(()=>[{path:'policy_id',label:label('片段质量 ID','Fragment quality ID')},{path:'policy_version',label:label('策略版本','Policy version'),type:'number'}])
const robustFields=computed<Field[]>(()=>[
  ...[['sector_count','角区数','Sector count'],['loss_scale','稳健残差尺度','Robust residual scale'],['inlier_residual','内点残差上限','Inlier residual limit']].map(([key,cn,en])=>({path:`robust.${key}`,label:label(cn!,en!),type:'number' as const})),
])
const selectionFields=computed<Field[]>(()=>[{path:'selection.feature_id',label:label('边界特征','Boundary feature')}])
const fitFields=computed<Field[]>(()=>kind.value==='fit-line'?[{path:'min_orientation_cosine',label:label('最小方向余弦','Minimum orientation cosine'),type:'number'}]:[{path:'radius_range',label:label('半径搜索范围','Radius search range'),type:'pair'},{path:'max_arc_step',label:label('相邻支持最大转角 rad','Maximum adjacent angle rad'),type:'number'}])
const surfaceFields=computed<Field[]>(()=>[['alpha_radius','支持圆半径','Support circle radius'],['max_edge_length','最大连接边长','Maximum edge length'],['max_normal_step','最大法向高度跳变','Maximum normal step'],['min_projected_area','最小投影三角面积','Minimum projected triangle area']].map(([key,cn,en])=>({path:`surface.${key}`,label:label(cn!,en!),type:'number'})))
const solverFields=computed<Field[]>(()=>['ftol','xtol','gtol','max_nfev'].map(key=>({path:`solver.${key}`,label:key,type:'number'} as Field)).concat([{path:'solver.x_scale',label:label('求解变量尺度','Solver variable scale'),type:'vector'}]))
const qualityFields=computed<Field[]>(()=>[{path:'quality_policy.policy_id',label:label('质量策略 ID','Quality policy ID')},{path:'quality_policy.policy_version',label:label('策略版本','Policy version'),type:'number'}])
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):newBoundarySettings(kind.value);targetIndex.value=0;previewId.value='';arcHandle.value='none';roiScope.value='surface';initial.value=JSON.stringify(draft.value);open.value=true}
function changeMethod(kind:string){
  const wasPose=poseContour.value,wasVisible=visibleEnvelope.value,visible=kind==='visible-envelope',q=object(draft.value.quality_policy)
  const extra=['profile_coverage','estimated_fraction','profile_max_gap','max_cell_span','missing_neighbor_fraction','added_cell_count','profile_max_jump']
  let rules=Array.isArray(q.rules)?q.rules.map(normalizeLimitRule):[]
  if(wasVisible||visible)rules=rules.filter(r=>!extra.includes(r.item_id))
  if(visible)rules.push(...extra.slice(0,4).map(item_id=>normalizeLimitRule({item_id,unit:['profile_coverage','estimated_fraction'].includes(item_id)?'1':String(object(draft.value.evaluation).length_unit??'')})))
  draft.value={...draft.value,method:newBoundaryMethod(kind),evaluation:['pose-contour','visible-envelope'].includes(kind)?newEvaluation('pose',draft.value.evaluation):wasPose?newEvaluation('configured',draft.value.evaluation):draft.value.evaluation,surface:visible?null:wasVisible?{alpha_radius:null,max_edge_length:null,max_normal_step:null,min_projected_area:null}:draft.value.surface,targets:visible||wasVisible?[]:draft.value.targets,quality_policy:{...q,rules}}
  previewId.value='';targetIndex.value=0
}
function addTarget(){draft.value={...draft.value,targets:[...targets.value,{segment_id:'',closed:false,role:'unknown',region:newRegion()}]};targetIndex.value=targets.value.length-1}
function removeTarget(){draft.value={...draft.value,targets:targets.value.filter((_,i)=>i!==targetIndex.value)};targetIndex.value=0}
function setTarget(value:Form){const next=[...targets.value];next[targetIndex.value]=value;draft.value={...draft.value,targets:next}}
function changeTarget(mode:string){if(!target.value)return;setTarget(mode==='group'?newFragmentTarget(target.value):{segment_id:target.value.group_id??target.value.segment_id??'',closed:false,role:'unknown',region:target.value.region})}
function chooseFeature(value:{payload:Form;featureId:string;segmentId:string}){if(!open.value||props.disabled||extract.value||value.payload!==preview.value?.payload)return;const source=boundaryChoices.value.filter(c=>c.id===value.featureId),feature=curveItems(value.payload).find(f=>f.kind==='boundary'&&f.valid&&f.feature_id===value.featureId);if(source.length!==1||!feature)return;const group=feature.topology?.segments.find(s=>s.segment_id===value.segmentId||s.group_id===value.segmentId)?.group_id;draft.value=put(draft.value,'selection',{feature_id:value.featureId,...(group?{group_ids:[group]}:{segment_ids:value.segmentId?[value.segmentId]:[]})})}
function pickSeed(value:{payload:Form;xyz:number[]}){if(!open.value||props.disabled||!canPickSeed.value||value.payload!==preview.value?.payload)return;const uv=candidateUV(previewFrame.value,value.xyz),size=seedSize.value;if(!uv||!size)return;const path='method.envelope.selection';draft.value=put(put(draft.value,path+'.seed_min',uv.map((v,i)=>v-size[i]!/2)),path+'.seed_max',uv.map((v,i)=>v+size[i]!/2));candidate.value=[...value.xyz]}
// 全图引用问题由保存/发布预检拦截，不能锁住逐节点修正合法草稿的操作。
function apply(){if(!issues.value.length&&!props.disabled){emit('update:modelValue',copy(draft.value));open.value=false}}
watch(()=>[props.modelValue,props.disabled,props.nodeType],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
watch(()=>[targetIndex.value,previewId.value,open.value],()=>{arcHandle.value='none'})
watch(()=>[open.value,previewId.value,JSON.stringify(draft.value.evaluation),object(draft.value.method).kind],()=>{candidate.value=null})
watch(()=>object(draft.value.selection).feature_id,(next,previous)=>{if(open.value&&next!==previous){const s=object(draft.value.selection),key=Array.isArray(s.group_ids)&&s.group_ids.length?'group_ids':'segment_ids',allowed=key==='group_ids'?availableGroups.value:availableSegments.value,selected=Array.isArray(s[key])?s[key]:[],filtered=selected.filter((id:string)=>allowed.includes(id));if(allowed.length&&filtered.length!==selected.length)draft.value=put(draft.value,'selection',{...s,[key]:filtered})}})
watch(()=>JSON.stringify(props.inputSources),()=>{open.value=false;previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.boundary-config fieldset label{display:flex;align-items:center;gap:6px}.boundary-config input[type=checkbox]{width:16px;height:16px;min-width:16px;flex:none}.segment-rows{display:grid;gap:6px}.segment-rows label{display:grid;grid-template-columns:minmax(0,1fr) 30px;gap:6px}.segment-rows label input{grid-column:1;min-width:0}.segment-rows button{width:30px;height:30px;display:grid;place-items:center}
.boundary-dialog :deep(.confirm-dialog){width:min(1260px,calc(100vw - 36px))}.boundary-config,.boundary-view{display:grid;gap:10px;min-width:0}.target-toolbar{display:flex;gap:8px;align-items:end;flex-wrap:wrap}.target-toolbar button{display:grid;place-items:center;width:30px;height:30px}fieldset{border:1px solid var(--am-border);display:flex;gap:10px;flex-wrap:wrap}details>summary{padding:8px 0;cursor:pointer;font-weight:600}
</style>
