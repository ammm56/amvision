<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ zh ? '点云重采样' : 'Resample cloud' }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" class="geometry-dialog" :title="zh ? '点云重采样' : 'Resample cloud'" size="wide" scroll-body
      :confirm-label="zh ? '应用' : 'Apply'" :cancel-label="zh ? '取消' : 'Cancel'" :confirm-disabled="disabled || !resampleValid(draft)"
      @confirm="apply" @cancel="open=false">
      <MetrologyWorkspace>
        <template #parameters>
          <label>{{ zh ? '方法' : 'Method' }}<select :value="draft.kind" @change="changeMethod">
            <option value="stride">{{ zh ? '行间隔抽取' : 'Row stride' }}</option>
            <option value="voxel-representative">{{ zh ? '体素原点代表' : 'Voxel representative' }}</option>
            <option value="voxel-centroid">{{ zh ? '体素质心' : 'Voxel centroid' }}</option>
          </select></label>
          <GeometryFields :model-value="draft" :fields="fields" @update:model-value="draft=$event" />
          <dl><dt>{{ zh ? '输出' : 'Output' }}</dt><dd>{{ draft.kind==='voxel-centroid'
            ? (zh?'生成点 · 仅坐标 · 完整成员来源':'Generated points · positions only · complete member lineage')
            : (zh?'选择已有点 · 保留全部字段与来源':'Select existing points · preserve all fields and lineage') }}</dd></dl>
        </template>
        <template #view="{presentation}">
          <section class="resample-view">
            <CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />
            <label v-if="preview">{{ zh?'叠加对照':'Overlay comparison' }}<select v-model="comparisonId"><option value="">{{ zh?'关闭':'Off' }}</option><option v-for="item in comparisons" :key="item.id" :value="item.id">{{ item.label }}</option></select></label>
            <CloudViewer v-if="preview" :key="preview.id" :presentation="presentation" :payload="preview.payload" :compare-payload="comparison?.payload" :project-id="preview.projectId" allow-pick />
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
import {newResample, resampleValid} from './resample-form'
import {copy, type Field, type Form} from './form'
import {comparableClouds} from '@/workflows/workflow-editor/point-cloud/voxel-display'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;nodeType:string;disabled?:boolean;inputSources?:ParameterEditorSources}>()
const emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue'))
const {locale}=useI18n(), zh=computed(()=>locale.value==='zh-CN')
const open=ref(false), draft=ref<Form>(newResample('stride')), initial=ref(''), previewId=ref('')
const resolve=inject(parameterCloudPreviewsKey,()=>[]), state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
const comparisonId=ref('')
const comparisons=computed(()=>preview.value?previews.value.filter(p=>p.id!==preview.value!.id&&p.projectId===preview.value!.projectId&&comparableClouds(preview.value!.payload,p.payload)):[])
const comparison=computed(()=>comparisons.value.find(p=>p.id===comparisonId.value))
watch([previewId,()=>state().runId,open],()=>{comparisonId.value=''})
const fields=computed<Field[]>(()=>draft.value.kind==='stride' ? [
  {path:'every_k_points',type:'number',label:zh.value?'行间隔':'Row interval'},
  {path:'offset',type:'number',label:zh.value?'起始偏移':'Start offset'},
] : [
  {path:'voxel_size',type:'number',label:zh.value?'格边长':'Voxel size'},
  {path:'grid_origin',type:'vector',label:zh.value?'固定格原点':'Fixed grid origin'},
  {path:'frame_id',label:zh.value?'坐标系':'Coordinate frame'},
  {path:'length_unit',type:'select',options:['m','mm','um'],label:zh.value?'长度单位':'Length unit'},
  ...(draft.value.kind==='voxel-centroid'?[{path:'max_position_error',type:'number' as const,label:zh.value?'最大坐标回写误差':'Maximum position rounding error'}]:[]),
])
function show(){draft.value=props.modelValue && typeof props.modelValue==='object' ? copy(props.modelValue) as Form : newResample('stride');initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function changeMethod(event:Event){draft.value=newResample((event.target as HTMLSelectElement).value)}
function apply(){if(!props.disabled && resampleValid(draft.value)){emit('update:modelValue',copy(draft.value));open.value=false}}
watch([()=>props.modelValue,()=>props.nodeType,()=>props.disabled,()=>JSON.stringify(props.inputSources)],()=>{open.value=false;previewId.value=''})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
label{display:grid;gap:6px;margin-bottom:12px;min-width:0}select{width:100%;min-width:0}.resample-view{display:grid;gap:10px;min-width:0}dl{font-size:12px;line-height:1.5}dd{margin:0;overflow-wrap:anywhere}
.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}
</style>
