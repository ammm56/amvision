<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ zh ? '点云去噪' : 'Denoise cloud' }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="geometry-dialog" :title="zh ? '点云去噪' : 'Denoise cloud'" size="wide" scroll-body
      :confirm-label="zh ? '应用' : 'Apply'" :cancel-label="zh ? '取消' : 'Cancel'" :confirm-disabled="disabled || !denoiseValid(draft)"
      @confirm="apply" @cancel="open=false">
      <MetrologyWorkspace>
        <template #parameters>
          <label>{{ zh ? '方法' : 'Method' }}<select :value="draft.kind" @change="changeMethod">
            <option value="statistical">{{ zh ? '统计邻域' : 'Statistical neighbors' }}</option>
            <option value="radius">{{ zh ? '半径邻域' : 'Radius neighbors' }}</option>
          </select></label>
          <GeometryFields :model-value="draft" :fields="fields" @update:model-value="draft=$event as DenoiseDraft" />
        </template>
        <template #view="{presentation}">
          <section class="denoise-view">
            <CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />
            <CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :project-id="preview.projectId" />
          </section>
        </template>
      </MetrologyWorkspace>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import {computed, defineAsyncComponent, inject, ref, watch} from 'vue'
import {useI18n} from 'vue-i18n'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {parameterCloudPreviewsKey, parameterPreviewStateKey, type ParameterEditorSources} from '@/workflows/workflow-editor/parameters/editor-context'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import MetrologyWorkspace from './MetrologyWorkspace.vue'
import GeometryFields from './GeometryFields.vue'
import {newDenoise, denoiseValid, type DenoiseDraft} from './denoise-form'
import {copy, type Field} from './form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources}>()
const emit=defineEmits<{'update:modelValue':[value:DenoiseDraft]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(), zh=computed(()=>locale.value==='zh-CN')
const open=ref(false), draft=ref<DenoiseDraft>(newDenoise('statistical')), initial=ref(''), previewId=ref('')
const resolve=inject(parameterCloudPreviewsKey,()=>[]), state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
const fields=computed<Field[]>(()=>draft.value.kind==='statistical' ? [
  {path:'neighbors',type:'number',label:zh.value?'其他邻居数':'Other neighbors'},
  {path:'std_ratio',type:'number',label:zh.value?'总体标准差倍数':'Population standard deviation ratio'},
] : [
  {path:'radius',type:'number',label:zh.value?'半径（输入点云单位）':'Radius (input cloud unit)'},
  {path:'min_neighbors',type:'number',label:zh.value?'最少其他邻居数':'Minimum other neighbors'},
])
function show(){draft.value=props.modelValue && typeof props.modelValue==='object' ? copy(props.modelValue) as DenoiseDraft : newDenoise('statistical');initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function changeMethod(event:Event){draft.value=newDenoise((event.target as HTMLSelectElement).value)}
function apply(){if(!props.disabled && denoiseValid(draft.value)){emit('update:modelValue',copy(draft.value));open.value=false}}
watch([()=>props.modelValue,()=>props.nodeType,()=>props.disabled,()=>JSON.stringify(props.inputSources)],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
label{display:grid;gap:6px;margin-bottom:12px;min-width:0}select{width:100%;min-width:0}.denoise-view{display:grid;gap:10px;min-width:0}
.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}
</style>
