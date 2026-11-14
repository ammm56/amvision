<template>
  <button :disabled="disabled" @click="show">{{ label('关系测量','Relation measurement') }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" :title="label('关系测量','Relation measurement')" size="wide" scroll-body :confirm-label="label('应用','Apply')" :cancel-label="label('取消','Cancel')" :confirm-disabled="disabled||!!issues.length||!!referenceIssues.length" @confirm="apply" @cancel="open=false">
      <MetrologyWorkspace>
        <template #parameters>
          <div class="relation-settings">
            <label>{{ label('测量方法','Method') }}<select :value="r.kind" @change="changeMethod(($event.target as HTMLSelectElement).value)"><option v-for="kind in relationKinds" :key="kind" :value="kind">{{ methodLabel(kind) }}</option></select></label>
            <GeometryFields v-model="draft" :fields="[{path:'item_id',label:label('量值 ID','Measurement ID')}]" />
            <label>{{ label('测量空间','Measurement space') }}<select :value="space.kind" @change="changeSpace(($event.target as HTMLSelectElement).value)"><option value="spatial">{{ label('三维空间','3D space') }}</option><option value="projection" :disabled="r.kind==='point-plane'">{{ label('评价面投影','Evaluation plane projection') }}</option></select></label>
            <EvaluationEditor v-if="space.kind==='projection'" :model-value="space.plane" @update:model-value="draft=put(draft,'space.plane',$event)" />
            <GeometryFields v-else v-model="draft" :fields="spaceFields" />
            <fieldset v-for="role in roles" :key="role"><legend>{{ role==='reference'?label('基准 A','Reference A'):label('目标 B','Target B') }}</legend>
              <label v-if="isPoint(role)">{{ label('点来源','Point source') }}<select :value="object(r[role]).kind" @change="setOperand(role,($event.target as HTMLSelectElement).value)"><option value="coordinate">{{ label('指定坐标','Specified coordinates') }}</option><option value="source-point">{{ label('原始行号','Original row') }}</option><option value="circle-center">{{ label('拟合圆心','Fitted circle center') }}</option></select></label>
              <GeometryFields v-if="object(r[role]).kind==='coordinate'" v-model="draft" :fields="[{path:`relation.${role}.position`,type:'vector',label:'XYZ'}]" />
              <GeometryFields v-else-if="object(r[role]).kind==='source-point'" v-model="draft" :fields="[{path:`relation.${role}.source_index`,type:'number',label:label('原始行号','Original row')}]" />
              <label v-else>{{ label('输入特征','Input feature') }}<input :value="object(r[role]).feature_id" :list="`${uid}-${role}`" @input="draft=put(draft,`relation.${role}.feature_id`,($event.target as HTMLInputElement).value)"><datalist :id="`${uid}-${role}`"><option v-for="c in choicesFor(role)" :key="`${c.nodeId}:${c.id}`" :value="c.id">{{ c.nodeId }}</option></datalist></label>
              <button v-if="object(r[role]).kind==='coordinate'" :disabled="!canPick" :aria-pressed="activeRole===role" :title="label('在当前点云选择候选坐标','Choose candidate coordinates in current cloud')" @click="activeRole=activeRole===role?'':role"><MousePointer2 :size="16" /></button>
            </fieldset>
            <label v-if="r.support_mode!==undefined">{{ label('支持范围','Support range') }}<select :value="r.support_mode" @change="changeSupport(($event.target as HTMLSelectElement).value)"><option value="finite">{{ label('有限实测支持','Finite measured support') }}</option><option value="model">{{ label('无限模型','Infinite model') }}</option></select></label>
            <label v-if="r.kind==='point-plane'">{{ label('距离符号','Distance sign') }}<select v-model="r.value_mode"><option value="absolute">{{ label('绝对值','Absolute') }}</option><option value="signed">{{ label('沿目标正法向','Along target positive normal') }}</option></select></label>
            <label v-if="String(r.kind).endsWith('angle')">{{ label('角度定义','Angle definition') }}<select v-model="r.angle_mode"><option value="unoriented">{{ label('无向 0–90°','Unoriented 0–90°') }}</option><option value="oriented">{{ label('有向向量 0–180°','Oriented vectors 0–180°') }}</option><option value="signed" :disabled="space.kind!=='projection'">{{ label('绕评价面 +N，−180–180°','Around evaluation +N, −180–180°') }}</option></select></label>
          </div>
        </template>
        <template #view="{presentation}">
          <CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />
          <CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" :allow-pick="canPick&&!!activeRole" :candidate="candidate??undefined" @candidate="pick" />
        </template>
        <template #advanced>
          <details><summary>{{ label('数值条件与几何质量','Numerical conditions and geometry quality') }}</summary>
            <GeometryFields v-model="draft" :fields="conditionFields" />
            <GeometryFields v-model="draft" :fields="[{path:'quality_policy.policy_id',label:label('质量策略 ID','Quality policy ID')},{path:'quality_policy.policy_version',type:'number',label:label('策略版本','Policy version')}]" />
            <WorkflowLimitRulesEditor :model-value="object(draft.quality_policy).rules" quality @update:model-value="draft=put(draft,'quality_policy.rules',$event)" />
          </details>
        </template>
        <template #issues><p v-if="issues.length" role="alert">{{ label('待完善','Incomplete') }}: {{ issues.join(' · ') }}</p><p v-if="referenceIssues.length" role="status">{{ referenceIssues.join(' · ') }}</p></template>
      </MetrologyWorkspace>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,useId,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {MousePointer2} from '@lucide/vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import GeometryFields from './GeometryFields.vue'
import EvaluationEditor from './EvaluationEditor.vue'
import {copy,object,put,vector,type Field,type Form} from './form'
import {newRelation,newOperand,newCoverage,relationSpace,relationKinds,relationIssues,relationChoices} from './relation-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources;draftIssues?:(value:unknown)=>string[]}>()
const emit=defineEmits<{(e:'update:modelValue',value:unknown):void}>()
const {locale}=useI18n(),label=(cn:string,en:string)=>locale.value.startsWith('zh')?cn:en
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const uid=useId(),roles=['reference','target'],open=ref(false),draft=ref<Form>({}),previewId=ref(''),activeRole=ref(''),candidate=ref<number[]|null>(null),initial=ref('')
const r=computed(()=>object(draft.value.relation)),space=computed(()=>object(draft.value.space)),issues=computed(()=>relationIssues(draft.value))
const changed=computed(()=>JSON.stringify(draft.value)!==initial.value),referenceIssues=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const choices=computed(()=>relationChoices(props.inputSources??{}))
const currentSpace=computed(()=>space.value.kind==='projection'?object(space.value.plane):space.value)
const canPick=computed(()=>!!preview.value&&currentSpace.value.frame_id===object(preview.value.payload.spatial).frame_id&&currentSpace.value.length_unit===object(preview.value.payload.spatial).length_unit)
const spaceFields=computed<Field[]>(()=>[{path:'space.frame_id',label:label('坐标系 ID','Frame ID')},{path:'space.length_unit',label:label('长度单位','Length unit'),type:'select',options:['m','mm','um']}])
const conditionFields=computed<Field[]>(()=>[
  ...(space.value.kind==='projection'?[{path:'space.min_direction_norm',label:label('投影方向最小模长','Minimum projected direction norm'),type:'number' as const}]:[]),
  ...(r.value.kind==='line-line'?[{path:'relation.min_crossing_sine',label:label('最小求交正弦','Minimum crossing sine'),type:'number' as const}]:[]),
  ...(r.value.kind==='point-plane'&&r.value.support_mode==='finite'?[['support_radius','支持半径','Support radius'],['min_support_count','最少支持点','Minimum support points'],['max_triangle_edge','最大三角边长','Maximum triangle edge'],['max_plane_residual','最大平面残差','Maximum plane residual']].map(([key,cn,en])=>({path:`relation.coverage.${key}`,label:label(cn!,en!),type:'number' as const})):[])
])
function methodLabel(kind:string){return ({'point-point':label('点点距离','Point-point distance'),'point-line':label('点线距离','Point-line distance'),'point-plane':label('点面距离','Point-plane distance'),'line-line':label('线线距离','Line-line distance'),'line-angle':label('直线夹角','Line angle'),'plane-angle':label('平面法向夹角','Plane-normal angle')})[kind]??kind}
function isPoint(role:string){return String(r.value.kind).startsWith('point')&&(role==='reference'||r.value.kind==='point-point')}
function choicesFor(role:string){const kind=object(r.value[role]).kind;return choices.value.filter(c=>c.kind===(kind==='circle-center'?'circle':kind))}
function reset(){previewId.value='';activeRole.value='';candidate.value=null}
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):newRelation();initial.value=JSON.stringify(draft.value);reset();open.value=true}
function changeMethod(kind:string){draft.value={...draft.value,relation:newRelation(kind).relation};if(kind==='point-plane')draft.value.space=relationSpace(space.value,'spatial');activeRole.value='';candidate.value=null}
function changeSpace(kind:string){draft.value={...draft.value,space:relationSpace(space.value,kind)};if(kind==='spatial'&&r.value.angle_mode==='signed')draft.value=put(draft.value,'relation.angle_mode','oriented');candidate.value=null;activeRole.value=''}
function changeSupport(kind:string){draft.value=put(draft.value,'relation.support_mode',kind);if(r.value.kind==='point-plane')draft.value=put(draft.value,'relation.coverage',kind==='finite'?newCoverage():null)}
function setOperand(role:string,kind:string){draft.value=put(draft.value,`relation.${role}`,newOperand(kind));candidate.value=null;activeRole.value=''}
function pick(value:{payload:Form;xyz:number[]}){if(!open.value||props.disabled||!canPick.value||!activeRole.value||object(r.value[activeRole.value]).kind!=='coordinate'||value.payload!==preview.value?.payload||!vector(value.xyz))return;draft.value=put(draft.value,`relation.${activeRole.value}.position`,[...value.xyz]);candidate.value=[...value.xyz];activeRole.value=''}
function apply(){if(props.disabled||issues.value.length||referenceIssues.value.length)return;emit('update:modelValue',copy(draft.value));open.value=false}
watch(()=>[props.modelValue,props.nodeType,props.inputSources],()=>{if(open.value){open.value=false;reset()}},{deep:true})
watch(()=>props.disabled,value=>{if(value){open.value=false;reset()}})
watch(()=>state().runId,reset)
watch(()=>preview.value?.payload,()=>{activeRole.value='';candidate.value=null})
</script>
<style scoped>
.relation-settings{display:grid;gap:12px;min-width:0}.relation-settings label{display:grid;gap:4px;min-width:0}.relation-settings fieldset{display:grid;gap:8px;min-width:0;border:1px solid var(--am-border);padding:10px}.relation-settings input,.relation-settings select{width:100%;min-width:0;padding:6px;border:1px solid var(--am-border);border-radius:4px;background:var(--am-input);color:var(--am-text);font:inherit}.relation-settings button{width:32px;height:32px;display:grid;place-items:center}
</style>
