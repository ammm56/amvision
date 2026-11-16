<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ parameterName==='support'?(zh?'支持范围':'Fitting support'):(zh?'平面拟合':'Plane fit') }} · {{ parameterName==='support'?(object(parameters?.support).kind==='parameters'?object(object(parameters?.support).roi).roi_id:(zh?'完整输入':'Entire input')):object(parameters?.settings).feature_id }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" class="geometry-dialog" :title="zh?'平面拟合':'Plane fit'" size="wide" scroll-body :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" confirm-variant="primary" :confirm-disabled="disabled||issues.length>0||!batch" @confirm="apply" @cancel="open=false">
    <MetrologyWorkspace>
      <template #parameters>
        <label>{{ zh?'拟面支持范围':'Fitting support' }}<UiSelect :model-value="support.kind" @change="changeMode(String($event))" :options="[...[{ value: 'cloud', label: String(zh?'完整输入点云':'Entire input cloud'), disabled: false }], ...[{ value: 'parameters', label: String(zh?'显式 ROI':'Explicit ROI'), disabled: false }]]" floating /></label>
        <RoiForm v-if="support.kind==='parameters'" ref="form" v-model="support" :allow-input="false" :can-view="matching" :visibility-scope="scope" @view="roiView=$event" @visibility="hidden=$event" />
        <GeometrySettingsForm v-model="settings" plane :input-sources="inputSources" />
      </template>
      <template #view="{presentation}">
        <CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />
        <RoiCreationTools v-if="support.kind==='parameters'" ref="creation" :roi="form?.current" :payload="preview?.payload" :scope="scope" @change="form?.setCurrent($event)" @active="creating=$event" />
        <CloudViewer v-if="preview" :key="scope" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" :edit-rois="support.kind==='parameters'&&matching?roiView.rois:[]" :selected-roi-id="roiView.selectedId" :hidden-roi-ids="hidden" :roi-scope="scope" allow-pick :pick-active="creating" @candidate="creation?.pick($event)" @roi-change="changeRoi" />
      </template>
      <template #issues><p v-if="issues.length" role="alert">{{ zh?'待完善':'Incomplete' }}: {{ issues.join(' · ') }}</p><p v-if="error" role="alert">{{ error }}</p></template>
    </MetrologyWorkspace>
    <template #leading-actions><Button variant="secondary" :disabled="disabled||issues.length>0||!batch||!runNode||busy" @click="applyPreview"><Play :size="16" />{{ busy?(zh?'拟面预览中':'Previewing fit'):(zh?'应用并预览拟面':'Apply and preview fit') }}</Button></template>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import UiSelect from '@/shared/ui/components/Select.vue'
import {computed,defineAsyncComponent,inject,nextTick,onBeforeUnmount,ref,shallowRef,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import {Play} from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import {parameterBatchUpdateKey,parameterNodePreviewKey,parameterNodeContextKey,parameterCloudPreviewsKey,parameterPreviewStateKey,parameterSourceSignature,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import type {WorkflowJsonObject} from '@/workflows/workflow-editor/types'
import RoiForm from './RoiForm.vue'
import RoiCreationTools from './RoiCreationTools.vue'
import GeometrySettingsForm from './GeometrySettingsForm.vue'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {copy,object,newRoi,newSettings,planeSupportIssues,geometryIssues,type Form} from './form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;parameters?:WorkflowJsonObject;parameterName?:string;disabled?:boolean;inputSources?:ParameterEditorSources}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const batch=inject(parameterBatchUpdateKey,undefined),context=inject(parameterNodeContextKey,undefined),resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const runNode=inject(parameterNodePreviewKey,undefined),running=ref(false)
const busy=computed(()=>running.value||state().phase==='running')
let generation=0
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const open=ref(false),support=ref<Form>({}),settings=ref<Form>({}),expected=ref<WorkflowJsonObject>({}),cachedRoi=ref<Form|null>(null),previewId=ref(''),error=ref(''),creating=ref(false)
const form=ref<InstanceType<typeof RoiForm>>(),creation=ref<InstanceType<typeof RoiCreationTools>>(),hidden=shallowRef<ReadonlySet<string>>(new Set())
const roiView=ref<{rois:Form[];selectedId:string}>({rois:[],selectedId:''})
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(view=>view.id===previewId.value))
const scope=computed(()=>JSON.stringify([state().runId,previewId.value,support.value.kind]))
const matching=computed(()=>{const spatial=object(preview.value?.payload.spatial);return !!preview.value&&roiView.value.rois.every(roi=>roi.frame_id===spatial.frame_id&&roi.length_unit===spatial.length_unit)})
const changed=computed(()=>JSON.stringify(support.value)!==JSON.stringify(expected.value.support??{kind:'cloud'})||JSON.stringify(settings.value)!==JSON.stringify(expected.value.settings))
const issues=computed(()=>[...planeSupportIssues(support.value),...geometryIssues('fit-plane',settings.value)])
function changeMode(kind:string){if(support.value.kind==='parameters')cachedRoi.value=copy(support.value);support.value=kind==='cloud'?{kind:'cloud'}:cachedRoi.value?copy(cachedRoi.value):{kind:'parameters',roi:newRoi(),bounds:[]};creating.value=false}
function changeRoi(value:Form){if(open.value&&!props.disabled&&matching.value&&value.roi_id===roiView.value.selectedId)form.value?.setCurrent(value)}
function show(){if(props.disabled)return;expected.value=copy(props.parameters??{});support.value=expected.value.support===undefined?{kind:'cloud'}:copy(object(expected.value.support));settings.value=expected.value.settings===undefined?newSettings(true):copy(object(expected.value.settings));cachedRoi.value=null;error.value='';previewId.value='';open.value=true}
function apply(){if(props.disabled||issues.value.length||!batch||!context)return;if(batch(context().nodeId,expected.value,{support:copy(support.value),settings:copy(settings.value)} as WorkflowJsonObject))open.value=false;else error.value=zh.value?'节点已修改，请重新打开核对':'Node changed; reopen to review'}
async function applyPreview(){
  if(!open.value||props.disabled||issues.value.length||!batch||!context||!runNode||busy.value)return
  const nodeId=context().nodeId,previous=expected.value,updates={support:copy(support.value),settings:copy(settings.value)} as WorkflowJsonObject
  expected.value={...previous,...updates}
  if(!batch(nodeId,previous,updates)){expected.value=previous;error.value=zh.value?'节点已修改，请重新打开核对':'Node changed; reopen to review';return}
  const ticket=++generation;running.value=true;error.value='';creating.value=false
  await nextTick()
  if(ticket!==generation||!open.value||props.disabled||context().nodeId!==nodeId)return
  try{await runNode(nodeId)}catch(reason){if(ticket===generation&&open.value)error.value=String(reason)}finally{if(ticket===generation)running.value=false}
}
function invalidate(){generation++;running.value=false;open.value=false;previewId.value='';creating.value=false;hidden.value=new Set()}
watch(()=>props.parameters,()=>{if(JSON.stringify(props.parameters)!==JSON.stringify(expected.value))invalidate()},{deep:true})
watch([()=>props.disabled,()=>parameterSourceSignature(props.inputSources)],invalidate)
watch(()=>[state().runId,state().succeeded],()=>{previewId.value='';creating.value=false})
watch(open,value=>{if(!value){generation++;running.value=false;creating.value=false}})
onBeforeUnmount(invalidate)
</script>
<style src="./editor.css" scoped></style>
<style scoped>.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}</style>
