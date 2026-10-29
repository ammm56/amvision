<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ title }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="dimension-dialog" :title="title" size="wide" scroll-body confirm-variant="primary" :confirm-label="label('应用','Apply')" :cancel-label="label('取消','Cancel')" :confirm-disabled="disabled||!!issues.length||!!referenceIssues.length" @confirm="apply" @cancel="open=false">
      <div class="geometry-workspace dimension-workspace">
        <section class="dimension-config">
          <template v-if="extents">
            <fieldset class="modes"><legend>{{ label('测量定义','Measurement') }}</legend>
              <label v-for="mode in ['axis-spans','minimum-area-rectangle']" :key="mode"><input type="radio" name="dimension-mode" :checked="object(draft.mode).kind===mode" @change="changeMode(mode)">{{ mode==='axis-spans'?label('轴向跨度 U/V','Axis spans U/V'):label('最小包络 L/W','Minimum rectangle L/W') }}</label>
            </fieldset>
            <fieldset class="modes"><legend>{{ label('输入来源','Input source') }}</legend>
              <label><input type="radio" name="dimension-source" :checked="object(draft.source).kind==='cloud'" @change="changeSource('cloud')">{{ label('点云','Cloud') }}</label>
              <label><input type="radio" name="dimension-source" :checked="object(draft.source).kind==='boundary'" @change="changeSource('boundary')">{{ label('边界','Boundary') }}</label>
            </fieldset>
          </template>
          <template v-if="!extents||object(draft.source).kind==='boundary'">
            <div v-for="slot in featureSlots" :key="slot.path" class="feature-slot">
              <label>{{ slot.label }}<select :value="get(draft,slot.path)??''" @change="selectFeature(slot.path,($event.target as HTMLSelectElement).value)">
                <option value="">{{ label('未选择','None') }}</option>
                <option v-if="get(draft,slot.path)&&!choices.some(c=>c.id===get(draft,slot.path))" :value="String(get(draft,slot.path))">{{ get(draft,slot.path) }} · {{ label('未获取','Unavailable') }}</option>
                <option v-for="choice in choices" :key="`${choice.nodeId}:${choice.id}`" :value="choice.id">{{ choice.id }} · {{ choice.nodeId }}</option>
              </select></label>
              <button :title="label('从显示选择此目标','Select this target from view')" :aria-pressed="activeSlot===slot.path" @click="activeSlot=activeSlot===slot.path?'':slot.path"><MousePointer2 :size="16" /></button>
            </div>
            <p v-if="!choices.length" role="status">{{ label('当前连线尚无可用特征候选','No feature candidates from current connections') }}</p>
            <button v-if="edge" class="swap" :title="label('交换基准边和目标边','Swap reference and target')" @click="swap"><ArrowLeftRight :size="16" /></button>
          </template>
          <fieldset v-if="extents&&object(draft.source).kind==='boundary'" class="segments"><legend>{{ label('支持段','Support segments') }}</legend>
            <label v-for="segment in segments" :key="segment"><input type="checkbox" :checked="selectedSegments.includes(segment)" @change="toggleSegment(segment,($event.target as HTMLInputElement).checked)">{{ segment }}</label>
          </fieldset>
          <template v-if="edge"><label>{{ label('查询坐标','Query coordinates') }}<select :value="object(draft.query_position).kind==='plane-uv'?'plane-uv':'xyz'" @change="changeQuery(($event.target as HTMLSelectElement).value)"><option value="xyz">XYZ</option><option value="plane-uv">{{ label('评价面 U/V','Evaluation U/V') }}</option></select></label><GeometryFields v-model="draft" :fields="edgeFields" /><EvaluationDirectionEditor v-model="draft.direction" :label="label('测量方向','Measurement direction')" /></template>
          <label v-if="edge">{{ label('距离符号','Distance sign') }}<select v-model="draft.value_mode"><option value="signed">{{ label('有符号','Signed') }}</option><option value="absolute">{{ label('绝对值','Absolute') }}</option></select></label>
          <label v-if="hole">{{ label('目标定义','Target definition') }}<select v-model="draft.target_kind"><option value="closed-hole">{{ label('闭合圆孔','Closed hole') }}</option><option value="open-arc">{{ label('开放圆弧','Open arc') }}</option></select></label>
          <EvaluationDirectionEditor v-if="hole" v-model="draft.display_direction" :label="label('直径辅助方向','Diameter display direction')" />
          <fieldset class="outputs"><legend>{{ label('输出量','Output quantities') }}</legend>
            <label v-for="component in outputComponents" :key="component">
              <input v-if="hole" type="checkbox" :checked="outputs.some(o=>o.component===component)" @change="toggleOutput(component,($event.target as HTMLInputElement).checked)">
              <span>{{ componentLabel(component) }}</span>
              <input :aria-label="`${componentLabel(component)} ID`" :value="outputs.find(o=>o.component===component)?.item_id??''" :disabled="!outputs.some(o=>o.component===component)" @input="setOutput(component,($event.target as HTMLInputElement).value)">
            </label>
          </fieldset>
          <EvaluationEditor v-model="draft.evaluation" :allow-feature="!extents||object(draft.source).kind==='boundary'" />
        </section>
        <section class="dimension-view">
          <label>{{ label('点云显示','Point cloud view') }}<select v-model="previewId"><option value="">{{ label('未选择','None') }}</option><option v-for="view in previews" :key="view.id" :value="view.id">{{ view.label }}</option></select></label>
          <CloudViewer v-if="preview" :key="preview.id" :payload="preview.payload" :project-id="preview.projectId" :allow-pick="canPick" :candidate="candidate??undefined" @candidate="pick" @feature-selection="chooseFeature" />
        </section>
        <details class="dimension-advanced"><summary>{{ label('数值条件与几何质量','Numerical conditions and geometry quality') }}</summary>
          <GeometryFields v-if="extents&&object(draft.mode).kind==='minimum-area-rectangle'" v-model="draft" :fields="rectangleFields" />
          <GeometryFields v-if="edge" v-model="draft" :fields="conditionFields" />
          <GeometryFields v-model="draft" :fields="qualityFields" />
          <WorkflowLimitRulesEditor :model-value="object(draft.quality_policy).rules" quality @update:model-value="draft=put(draft,'quality_policy.rules',$event)" />
        </details>
        <p v-if="issues.length" role="alert">{{ label('待完善','Incomplete') }}: {{ issues.join(' · ') }}</p>
        <p v-if="referenceIssues.length" role="alert">{{ referenceIssues.join(' · ') }}</p>
      </div>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {ArrowLeftRight,MousePointer2} from '@lucide/vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import {curveItems} from '@/workflows/workflow-editor/point-cloud/boundary-display'
import GeometryFields from './GeometryFields.vue'
import EvaluationEditor from './EvaluationEditor.vue'
import EvaluationDirectionEditor from './EvaluationDirectionEditor.vue'
import {newEvaluation} from './evaluation-form'
import {copy,get,object,put,vector,type Form,type Field} from './form'
import {dimensionComponents,dimensionFeatureChoices,dimensionIssues,newDimension,newExtentMode} from './dimension-form'

defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources;draftIssues?:(value:unknown)=>string[]}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(),label=(cn:string,en:string)=>locale.value==='zh-CN'?cn:en
const kind=computed(()=>props.nodeType.split('.').at(-1)!),extents=computed(()=>kind.value==='measure-extents'),edge=computed(()=>kind.value==='measure-edge-pair'),hole=computed(()=>kind.value==='measure-hole')
const title=computed(()=>extents.value?label('投影长宽','Projected extents'):edge.value?label('边间距','Edge distance'):label('孔径与圆心','Diameter and center'))
const open=ref(false),draft=ref<Form>({}),previewId=ref(''),activeSlot=ref(''),candidate=ref<number[]|null>(null)
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const issues=computed(()=>dimensionIssues(kind.value,draft.value)),referenceIssues=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
const wantedKind=computed(()=>extents.value?'boundary':edge.value?'line':'circle')
const choices=computed(()=>dimensionFeatureChoices(props.inputSources??{}).filter(c=>c.kind===wantedKind.value))
const featureSlots=computed(()=>extents.value?[{path:'source.selection.feature_id',label:label('边界','Boundary')}]:edge.value?[{path:'reference_feature_id',label:label('基准边 A','Reference edge A')},{path:'target_feature_id',label:label('目标边 B','Target edge B')}]:[{path:'feature_id',label:label('拟合圆','Fitted circle')}])
const segments=computed(()=>choices.value.find(c=>c.id===get(draft.value,'source.selection.feature_id'))?.segments??[])
const selectedSegments=computed(()=>(get(draft.value,'source.selection.segment_ids')??[]) as string[])
const outputs=computed(()=>(Array.isArray(draft.value.outputs)?draft.value.outputs:[]).map(object))
const outputComponents=computed(()=>hole.value?dimensionComponents:extents.value?(object(draft.value.mode).kind==='axis-spans'?['u','v']:['length','width']):['distance'])
const pickPlane=computed(()=>{
  const e=object(draft.value.evaluation)
  if(e.kind!=='feature')return e
  const matches=(props.inputSources?.features??[]).flatMap(s=>{const output=object(s.previewOutput);return Array.isArray(output.items)?output.items.map(object).filter(f=>f.feature_id===draft.value.reference_feature_id&&f.kind==='line'&&f.valid===true&&object(f.support).observation_id===preview.value?.payload.observation_id):[]})
  return matches.length===1?object(object(matches[0]!.method).evaluation):{}
})
const canPick=computed(()=>edge.value&&!!preview.value&&get(draft.value,'evaluation.frame_id')===object(preview.value.payload.spatial).frame_id&&get(draft.value,'evaluation.length_unit')===object(preview.value.payload.spatial).length_unit&&(object(draft.value.query_position).kind!=='plane-uv'||vector(pickPlane.value.origin)&&Array.isArray(pickPlane.value.rotation)&&pickPlane.value.rotation.length===3&&pickPlane.value.rotation.every(vector)))
const componentLabel=(c:string)=>({u:'U',v:'V',length:label('长边 L','Length L'),width:label('短边 W','Width W'),distance:label('距离','Distance'),diameter:label('直径','Diameter'),center_x:label('圆心 X','Center X'),center_y:label('圆心 Y','Center Y'),center_z:label('圆心 Z','Center Z')}[c]??c)
const edgeFields=computed<Field[]>(()=>object(draft.value.query_position).kind==='plane-uv'?[{path:'query_position.uv',label:label('查询位置 U/V','Query U/V'),type:'pair'}]:[{path:'query_position',label:label('查询位置 XYZ','Query XYZ'),type:'vector'}])
const rectangleFields=computed<Field[]>(()=>[['area_abs_tolerance','面积绝对容差（单位²）','Absolute area tolerance (unit squared)'],['area_rel_tolerance','面积相对容差','Relative area tolerance'],['dimension_abs_tolerance','尺寸绝对容差（长度单位）','Absolute dimension tolerance (length unit)'],['dimension_rel_tolerance','尺寸相对容差','Relative dimension tolerance'],['orientation_tolerance_radians','方向等价角 rad','Equivalent direction angle rad']].map(([key,cn,en])=>({path:`mode.${key}`,label:label(cn!,en!),type:'number'})))
const conditionFields=computed<Field[]>(()=>[['max_plane_distance','最大共面距离','Maximum plane distance'],['max_plane_angle_radians','最大共面夹角 rad','Maximum plane angle rad'],['min_crossing_sine','最小求交正弦','Minimum crossing sine']].map(([path,cn,en])=>({path:path!,label:label(cn!,en!),type:'number'})))
const qualityFields=computed<Field[]>(()=>[{path:'quality_policy.policy_id',label:label('质量策略 ID','Quality policy ID')},{path:'quality_policy.policy_version',label:label('策略版本','Policy version'),type:'number'}])
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):newDimension(kind.value);resetView();open.value=true}
function resetView(){previewId.value='';activeSlot.value='';candidate.value=null}
function changeMode(mode:string){draft.value={...draft.value,mode:newExtentMode(mode),outputs:(mode==='axis-spans'?['u','v']:['length','width']).map(component=>({component,item_id:''}))};candidate.value=null}
function changeSource(kind:string){draft.value={...draft.value,source:kind==='cloud'?{kind}:{kind,selection:{feature_id:'',segment_ids:[]}},evaluation:kind==='cloud'&&object(draft.value.evaluation).kind==='feature'?newEvaluation('configured',draft.value.evaluation):draft.value.evaluation};activeSlot.value='';candidate.value=null}
function changeQuery(kind:string){draft.value={...draft.value,query_position:kind==='plane-uv'?{kind,uv:[null,null]}:[null,null,null]};candidate.value=null}
function selectFeature(path:string,id:string){draft.value=put(draft.value,path,id);if(extents.value)draft.value=put(draft.value,'source.selection.segment_ids',[]);candidate.value=null}
function toggleSegment(id:string,on:boolean){draft.value=put(draft.value,'source.selection.segment_ids',on?[...selectedSegments.value,id]:selectedSegments.value.filter(s=>s!==id))}
function toggleOutput(component:string,on:boolean){draft.value={...draft.value,outputs:on?[...outputs.value,{component,item_id:''}]:outputs.value.filter(o=>o.component!==component)}}
function setOutput(component:string,item_id:string){draft.value={...draft.value,outputs:outputs.value.map(o=>o.component===component?{...o,item_id}:o)}}
function swap(){draft.value={...draft.value,reference_feature_id:draft.value.target_feature_id,target_feature_id:draft.value.reference_feature_id};candidate.value=null;activeSlot.value=''}
function pick(value:{payload:Form;xyz:number[]}){
  if(!open.value||props.disabled||!canPick.value||value.payload!==preview.value?.payload||!vector(value.xyz))return
  if(object(draft.value.query_position).kind==='plane-uv'){
    const e=pickPlane.value,origin=e.origin as number[],rotation=e.rotation as number[][],delta=value.xyz.map((v,i)=>v-origin[i]!)
    draft.value={...draft.value,query_position:{kind:'plane-uv',uv:[0,1].map(j=>delta.reduce((s,v,i)=>s+v*rotation[i]![j]!,0))}}
  }else draft.value={...draft.value,query_position:[...value.xyz]}
  candidate.value=[...value.xyz]
}
function chooseFeature(value:{payload:Form;featureId:string;segmentId:string}){
  if(!open.value||props.disabled||!activeSlot.value||value.payload!==preview.value?.payload||choices.value.filter(c=>c.id===value.featureId).length!==1)return
  if(!curveItems(value.payload).some(f=>f.kind===wantedKind.value&&f.feature_id===value.featureId))return
  selectFeature(activeSlot.value,value.featureId)
  if(extents.value&&value.segmentId&&segments.value.includes(value.segmentId))toggleSegment(value.segmentId,true)
  activeSlot.value=''
}
function apply(){if(!issues.value.length&&!referenceIssues.value.length&&!props.disabled){emit('update:modelValue',copy(draft.value));open.value=false;resetView()}}
watch(()=>[props.modelValue,props.nodeType,props.disabled,JSON.stringify(props.inputSources)],()=>{open.value=false;resetView()})
watch(()=>[state().runId,state().succeeded],resetView)
watch(()=>[previewId.value,JSON.stringify(draft.value.evaluation)],()=>{candidate.value=null;activeSlot.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.dimension-dialog :deep(.confirm-dialog){width:min(1260px,calc(100vw - 36px))}
.dimension-workspace{grid-template-columns:minmax(280px,370px) minmax(0,1fr);align-items:start}
.dimension-config,.dimension-view{display:grid;gap:12px;min-width:0}.dimension-view :deep(.cloud-viewer){height:min(60dvh,640px)}
.dimension-advanced,.dimension-workspace>p{grid-column:1/-1;min-width:0}details>summary{padding:8px 0;font-weight:600;cursor:pointer}
fieldset{border:1px solid var(--am-border);padding:8px;min-width:0}.modes,.segments{display:flex;flex-wrap:wrap;gap:10px}.modes label,.segments label{display:flex;align-items:center;gap:6px}
.dimension-config input[type=radio],.dimension-config input[type=checkbox]{width:16px;height:16px;min-width:16px;flex:none}.outputs label{display:flex;gap:8px;align-items:center}.outputs label>input:not([type=checkbox]){min-width:0;flex:1}.outputs label>span{min-width:64px}
.feature-slot{display:grid;grid-template-columns:minmax(0,1fr) 32px;gap:8px;align-items:end}.feature-slot button,.swap{width:32px;height:32px;display:grid;place-items:center}.feature-slot button[aria-pressed=true]{background:var(--am-accent-soft)}
@media(max-width:900px){.dimension-workspace{grid-template-columns:minmax(0,1fr)}}
</style>
