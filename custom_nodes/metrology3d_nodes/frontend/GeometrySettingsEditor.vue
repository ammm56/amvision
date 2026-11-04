<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ title }} · {{ String(object(modelValue)[plane?'feature_id':'pose_id']||'-') }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" class="geometry-dialog" :title="title" size="wide" scroll-body confirm-variant="primary" :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="!!issues.length||disabled" @confirm="apply" @cancel="open=false">
    <MetrologyWorkspace>
      <template #parameters>
      <GeometrySettingsForm v-model="draft" :plane="plane" :input-sources="inputSources" />
      </template>
      <template #view="{presentation}">
      <section class="geometry-view">
        <CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />

        <CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" />

      </section>
      </template>
      <template #issues>
      <p v-if="issues.length" role="alert">{{ zh?'待完善':'Incomplete' }}: {{ issues.join(' · ') }}</p>
      <p v-if="referenceIssues.length" role="status">{{ referenceIssues.join(' · ') }}</p>
      </template>
    </MetrologyWorkspace>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import GeometrySettingsForm from './GeometrySettingsForm.vue'
import {object,copy,newSettings,geometryIssues,type Form} from './form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources;draftIssues?:(value:unknown)=>string[]}>(),emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue').then(m=>m.default))
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN'),plane=computed(()=>props.nodeType.endsWith('fit-plane'))
const title=computed(()=>plane.value?(zh.value?'平面拟合':'Plane fit'):(zh.value?'建立坐标系':'Build frame'))
const open=ref(false),draft=ref<Form>({}),previewId=ref(''),initial=ref('')
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
const issues=computed(()=>geometryIssues(plane.value?'fit-plane':'build-frame',draft.value))
const referenceIssues=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):newSettings(plane.value);initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function apply(){if(!issues.value.length&&!props.disabled){emit('update:modelValue',copy(draft.value));open.value=false}}
watch([()=>props.modelValue,()=>props.disabled,()=>props.nodeType,()=>JSON.stringify(props.inputSources)],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}
.geometry-view{display:grid;gap:10px;min-width:0}
</style>
