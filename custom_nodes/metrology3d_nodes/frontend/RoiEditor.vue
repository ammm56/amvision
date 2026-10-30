<template>
  <button class="geometry-open" :disabled="disabled" @click="show">{{ zh?'三维 ROI':'3D ROI' }} · {{ object(modelValue).kind==='input'?(zh?'输入端口':'Input port'):String(object(object(modelValue).roi).roi_id||'-') }}</button>
  <Teleport to="body"><ConfirmDialog v-if="open" class="geometry-dialog" :title="zh?'裁剪 ROI':'Crop ROI'" size="wide" scroll-body confirm-variant="primary" :confirm-label="zh?'应用':'Apply'" :cancel-label="zh?'取消':'Cancel'" :confirm-disabled="!!issues.length||disabled" @confirm="apply" @cancel="open=false">
    <div class="geometry-workspace roi-workspace">
      <RoiForm ref="form" v-model="draft" :allow-input="allowInput" @view="roiView=$event" />
      <section class="roi-view"><CloudPreviewSelector v-model="previewId" :previews="previews" :changed="changed" />

        <p v-if="preview&&!matching" role="status">{{ zh?'显示空间与 ROI 不一致，仅查看背景':'Display space differs from ROI; background only' }}</p>
        <CloudViewer v-if="preview" :payload="preview.payload" :project-id="preview.projectId" :edit-rois="matching?roiView.rois:[]" :selected-roi-id="roiView.selectedId" @roi-change="form?.setCurrent($event)" />

      </section>
      <p v-if="issues.length" role="alert">{{ zh?'待完善':'Incomplete' }}: {{ issues.join(' · ') }}</p>
      <p v-if="referenceIssues.length" role="status">{{ referenceIssues.join(' · ') }}</p>
    </div>
  </ConfirmDialog></Teleport>
</template>
<script setup lang="ts">
import {computed,defineAsyncComponent,inject,ref,watch} from 'vue'
import {useI18n} from 'vue-i18n'
import CloudPreviewSelector from './CloudPreviewSelector.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
import RoiForm from './RoiForm.vue'
import {object,copy,newRoi,geometryIssues,type Form} from './form'
defineOptions({inheritAttrs:false})
const props=defineProps<{modelValue:unknown;disabled?:boolean;allowInput?:boolean;draftIssues?:(value:unknown)=>string[]}>(),emit=defineEmits<{'update:modelValue':[value:Form]}>()
const CloudViewer=defineAsyncComponent(()=>import('@/workflows/workflow-editor/point-cloud/CloudViewer.vue').then(m=>m.default))
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const resolve=inject(parameterCloudPreviewsKey,()=>[]),state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false}))
const open=ref(false),draft=ref<Form>({}),previewId=ref(''),initial=ref(''),form=ref<InstanceType<typeof RoiForm>>()
const roiView=ref<{rois:Form[];selectedId:string}>({rois:[],selectedId:''})
const previews=computed(()=>state().succeeded?resolve():[]),preview=computed(()=>previews.value.find(p=>p.id===previewId.value))
const matching=computed(()=>{const s=object(preview.value?.payload.spatial);return roiView.value.rois.every(r=>r.frame_id===s.frame_id&&r.length_unit===s.length_unit)})
const changed=computed(()=>JSON.stringify(draft.value)!==initial.value)
const issues=computed(()=>geometryIssues('crop-roi',draft.value)),referenceIssues=computed(()=>open.value?props.draftIssues?.(draft.value)??[]:[])
function show(){draft.value=Object.keys(object(props.modelValue)).length?copy(object(props.modelValue)):{kind:'parameters',roi:newRoi(),bounds:[]};initial.value=JSON.stringify(draft.value);previewId.value='';open.value=true}
function apply(){if(!issues.value.length&&!props.disabled){emit('update:modelValue',copy(draft.value));open.value=false}}
watch(()=>[props.modelValue,props.disabled],()=>{open.value=false})
watch(()=>[state().runId,state().succeeded],()=>{previewId.value=''})
</script>
<style src="./editor.css" scoped></style>
<style scoped>
.geometry-dialog :deep(.confirm-dialog){width:min(1240px,calc(100vw - 36px))}.roi-workspace{grid-template-columns:minmax(280px,380px) minmax(0,1fr);align-items:start}.roi-view{display:grid;gap:12px;min-width:0;position:sticky;top:0}.roi-view :deep(.cloud-viewer){height:min(60dvh,660px)}.roi-workspace>p{grid-column:1/-1}
@media(max-width:900px){.roi-workspace{grid-template-columns:minmax(0,1fr)}.roi-view{position:static}}
</style>
