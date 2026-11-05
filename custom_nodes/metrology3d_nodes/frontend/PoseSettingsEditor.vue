<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ title }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="geometry-dialog" :title="title" size="wide" scroll-body
      :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="disabled||!valid"
      @confirm="apply" @cancel="open=false">
      <MetrologyWorkspace>
        <template #parameters>
          <GeometryFields v-model="draft" :fields="fields" />
          <dl class="pose-inputs"><template v-for="port in ports" :key="port"><dt>{{ port }}</dt>
            <dd v-for="source in inputSources?.[port]??[]" :key="source.nodeId">
              {{ source.nodeId }} · {{ identity(source) }}
            </dd><dd v-if="!inputSources?.[port]?.length">{{ zh?'未连接':'Not connected' }}</dd>
          </template></dl>
          <p class="pose-order">{{ inverse?'source ← target':'first → second' }}</p>
          <p v-if="mismatch" role="alert">{{ zh?'first 目标与 second 源坐标不一致':'The first target differs from the second source' }}</p>
        </template>
        <template #view="{presentation}">
          <section class="pose-view"><CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />
            <CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" />
          </section>
        </template>
      </MetrologyWorkspace>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey,type ParameterEditorSources,type ParameterEditorSource} from '@/workflows/workflow-editor/parameters/editor-context'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import GeometryFields from './GeometryFields.vue'
import {copy,object,type Form,type Field} from './form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const inverse=computed(()=>props.nodeType.endsWith('invert-pose')),title=computed(()=>inverse.value?(zh.value?'位姿求逆':'Invert pose'):(zh.value?'组合位姿':'Compose poses'))
const ports=computed(()=>inverse.value?['pose']:['first','second']),fields=computed<Field[]>(()=>[{path:'pose_id',label:zh.value?'输出位姿 ID':'Output pose ID'}])
const open=ref(false),draft=ref<Form>({pose_id:''}),initial=ref(''),previewId=ref('')
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value)),changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
function current(source?:ParameterEditorSource){return state().succeeded?object(source?.previewOutput):{}}
function identity(source:ParameterEditorSource){const pose=current(source);return pose.source_frame_id&&pose.target_frame_id?`${pose.source_frame_id} → ${pose.target_frame_id} · ${pose.state}`:String(object(source.parameters.settings).pose_id??'—')}
const mismatch=computed(()=>{if(inverse.value)return false;const a=current(props.inputSources?.first?.[0]),b=current(props.inputSources?.second?.[0]);return !!a.target_frame_id&&!!b.source_frame_id&&a.target_frame_id!==b.source_frame_id})
const valid=computed(()=>typeof draft.value.pose_id==='string'&&/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(draft.value.pose_id)&&Object.keys(draft.value).length===1&&!mismatch.value)
function show(){draft.value=copy(object(props.modelValue));initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function apply(){if(!props.disabled&&valid.value){emit('update:modelValue',copy(draft.value));open.value=false}}
watch([()=>props.modelValue,()=>props.nodeType,()=>props.disabled,()=>JSON.stringify(props.inputSources)],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.pose-inputs{display:grid;grid-template-columns:auto minmax(0,1fr);gap:8px;font-size:13px}.pose-inputs dd{margin:0;overflow-wrap:anywhere}.pose-order{font-size:13px}.pose-view{display:grid;gap:10px;min-width:0}.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}[role=alert]{color:var(--am-danger);font-size:13px}
</style>
