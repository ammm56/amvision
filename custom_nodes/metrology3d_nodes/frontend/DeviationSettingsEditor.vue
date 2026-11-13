<template>
  <button :disabled="disabled" @click="show">{{ label('基准偏差','Datum deviation') }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" :title="label('基准偏差','Datum deviation')" size="wide" scroll-body :confirm-label="label('应用','Apply')" :cancel-label="label('取消','Cancel')" :confirm-disabled="disabled||!!issues.length||!!references.length" @confirm="apply" @cancel="open=false">
    <MetrologyWorkspace>
      <template #parameters><div class="deviation-form">
        <GeometryFields v-model="draft" :fields="identity" :suggestions="suggestions" />
        <label>{{ label('基准支持','Datum support') }}<select :value="object(draft.reference_policy).kind" @change="changeReference(($event.target as HTMLSelectElement).value)"><option value="measured-support">{{ label('实测支持','Measured support') }}</option><option value="plane-extension">{{ label('有限延伸','Bounded extension') }}</option></select></label>
        <GeometryFields v-if="object(draft.reference_policy).kind==='plane-extension'" v-model="draft" :fields="extension" />
        <fieldset><legend>{{ label('输出量值 ID','Output measurement IDs') }}</legend><label v-for="(output,index) in outputs" :key="String(output.component)">{{ deviationLabel(String(output.component),zh) }}<input :value="output.item_id" @input="setOutput(index,($event.target as HTMLInputElement).value)"></label></fieldset>
      </div></template>
      <template #view="{presentation}"><CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" /><CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" /></template>
      <template #advanced><details><summary>{{ label('支持质量','Support quality') }}</summary><GeometryFields v-model="draft" :fields="qualityFields" /><WorkflowLimitRulesEditor :model-value="object(draft.quality_policy).rules" quality @update:model-value="draft=put(draft,'quality_policy.rules',$event)" /></details></template>
      <template #issues><p v-if="issues.length||references.length" role="alert">{{ [...issues,...references].join(' · ') }}</p></template>
    </MetrologyWorkspace>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import WorkflowLimitRulesEditor from '@/workflows/workflow-editor/components/WorkflowLimitRulesEditor.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import GeometryFields from './GeometryFields.vue'
import {copy,object,put,type Form,type Field} from './form'
import {deviationLabel,deviationIssues,newDeviation} from './deviation-form'
import {relationChoices} from './relation-form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources;draftIssues?:(value:unknown)=>string[]}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value.startsWith('zh')),label=(cn:string,en:string)=>zh.value?cn:en
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const open=ref(false),draft=ref<Form>({}),initial=ref(''),previewId=ref('')
const issues=computed(()=>deviationIssues(draft.value)),references=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
const changed=computed(()=>JSON.stringify(draft.value)!==initial.value),outputs=computed(()=>Array.isArray(draft.value.outputs)?draft.value.outputs.map(object):[])
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const suggestions=computed(()=>({reference_feature_id:relationChoices(props.inputSources??{}).filter(c=>c.kind==='plane').map(c=>c.id)}))
const identity=computed<Field[]>(()=>[{path:'reference_feature_id',label:label('基准平面 ID','Datum plane ID')},{path:'frame_id',label:label('坐标系 ID','Frame ID')},{path:'length_unit',label:label('长度单位','Length unit'),type:'select',options:['m','mm','um']},{path:'support_radius',label:label('支持半径','Support radius'),type:'number',unit:String(draft.value.length_unit??'')}])
const extension=computed<Field[]>(()=>[{path:'reference_policy.max_extension_distance',label:label('最大延伸距离','Maximum extension'),type:'number',unit:String(draft.value.length_unit??'')}])
const qualityFields=computed<Field[]>(()=>[{path:'quality_policy.policy_id',label:label('质量策略 ID','Quality policy ID')},{path:'quality_policy.policy_version',label:label('策略版本','Policy version'),type:'number'}])
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):newDeviation();initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function changeReference(kind:string){draft.value=put(draft.value,'reference_policy',kind==='plane-extension'?{kind,max_extension_distance:null}:{kind:'measured-support'})}
function setOutput(index:number,item_id:string){draft.value={...draft.value,outputs:outputs.value.map((o,i)=>i===index?{...o,item_id}:o)}}
function apply(){if(props.disabled||issues.value.length||references.value.length)return;emit('update:modelValue',copy(draft.value));open.value=false}
watch(()=>[props.modelValue,props.nodeType,props.inputSources,props.disabled],()=>{open.value=false;previewId.value=''},{deep:true})
watch(()=>state().runId,()=>{previewId.value=''})
</script>
<style scoped>
.deviation-form,.deviation-form fieldset{display:grid;gap:10px;min-width:0}.deviation-form label{display:grid;gap:4px;min-width:0}.deviation-form fieldset{border:1px solid var(--am-border);padding:10px}.deviation-form input,.deviation-form select{width:100%;min-width:0;padding:6px;border:1px solid var(--am-border);border-radius:4px;background:var(--am-input);color:var(--am-text);font:inherit}
</style>
