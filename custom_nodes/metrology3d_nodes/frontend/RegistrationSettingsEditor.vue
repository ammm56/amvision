<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ zh?'局部配准':'Local registration' }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" class="geometry-dialog" :title="zh?'局部配准':'Local registration'" size="wide" scroll-body
    :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="disabled||!!issues.length" @confirm="apply" @cancel="open=false">
    <MetrologyWorkspace>
      <template #parameters>
        <label>{{ zh?'方法':'Method' }}<select v-model="draft.algorithm"><option value="point-to-point">{{ zh?'点到点':'Point to point' }}</option><option value="point-to-plane">{{ zh?'点到面（参考云法向）':'Point to plane (reference normals)' }}</option></select></label>
        <dl class="sources"><template v-for="port in ['source','reference']" :key="port"><dt>{{ port==='source'?(zh?'移动云':'Moving cloud'):(zh?'参考云':'Reference cloud') }}</dt><dd>{{ (inputSources?.[port]??[]).map(s=>s.nodeId).join(', ')||(zh?'未连接':'Not connected') }}</dd></template></dl>
        <GeometryFields v-model="draft" :fields="identityFields" />
        <fieldset><legend>{{ zh?'显式初值':'Explicit initial pose' }}</legend><GeometryFields v-model="draft" :fields="initialFields" /></fieldset>
        <fieldset><legend>{{ zh?'对应与停止':'Correspondence and stopping' }}</legend><GeometryFields v-model="draft" :fields="solverFields" /></fieldset>
        <GeometryFields v-model="draft" :fields="qualityFields" />
        <WorkflowLimitRulesEditor :model-value="object(draft.quality_policy).rules" quality @update:model-value="draft=put(draft,'quality_policy.rules',$event)" />
      </template>
      <template #view="{presentation}"><section class="registration-view"><CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />
        <CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" />
      </section></template>
      <template #issues><p v-if="issues.length" role="alert">{{ zh?'待完善':'Incomplete' }}: {{ issues.join(' · ') }}</p></template>
    </MetrologyWorkspace>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import GeometryFields from './GeometryFields.vue'
import {copy,object,put,type Form,type Field} from './form'
import {newRegistration,registrationIssues} from './registration-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources}>(),emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),label=(cn:string,en:string)=>zh.value?cn:en
const open=ref(false),draft=ref<Form>(newRegistration()),initial=ref(''),previewId=ref('')
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value)),changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
const issues=computed(()=>registrationIssues(draft.value)),unit=computed(()=>String(draft.value.length_unit||''))
const field=(path:string,cn:string,en:string,type:Field['type']=undefined,unit?:string):Field=>({path,label:label(cn,en),type,unit})
const identityFields=computed<Field[]>(()=>[field('pose_id','位姿 ID','Pose ID'),field('source_frame_id','移动坐标系','Moving frame'),field('target_frame_id','参考坐标系','Reference frame'),{...field('length_unit','长度单位','Length unit','select'),options:['m','mm','um']}])
const initialFields=computed(()=>[field('initial_translation','平移 XYZ（参考坐标）','Translation XYZ (reference frame)','vector',unit.value),field('initial_rotation_degrees','外旋 XYZ','Extrinsic XYZ rotation','vector','deg')])
const solverFields=computed(()=>[field('max_correspondence_distance','最大对应距离','Maximum correspondence distance','number',unit.value),field('max_iterations','最大迭代次数','Maximum iterations','number'),field('fitness_change','覆盖率变化停止阈值','Coverage change threshold','number'),field('rmse_change','RMS 变化停止阈值','RMS change threshold','number',unit.value)])
const qualityFields=computed(()=>[field('quality_policy.policy_id','质量策略 ID','Quality policy ID'),field('quality_policy.policy_version','质量策略版本','Quality policy version','number')])
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):newRegistration();initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function apply(){if(!props.disabled&&!issues.value.length){emit('update:modelValue',copy(draft.value));open.value=false}}
watch([()=>props.modelValue,()=>props.nodeType,()=>props.disabled,()=>JSON.stringify(props.inputSources)],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
label{display:grid;gap:6px;margin:10px 0;min-width:0}select{width:100%;min-width:0}fieldset{margin:12px 0;padding:10px;border:1px solid var(--am-border);min-width:0}legend{font-size:13px}.sources{display:grid;grid-template-columns:auto minmax(0,1fr);gap:8px;font-size:13px}.sources dd{margin:0;overflow-wrap:anywhere}.registration-view{display:grid;gap:10px;min-width:0}.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}[role=alert]{font-size:13px;color:var(--am-danger)}
</style>
