<template>
  <section class="preview-source"><label>{{ zh?'点云显示':'Point cloud view' }}<select :value="modelValue" @change="emit('update:modelValue',($event.target as HTMLSelectElement).value)"><option value="">{{ zh?'未选择':'None' }}</option><option v-for="view in previews" :key="view.id" :value="view.id">{{ view.label }} · {{ space(view) }}</option></select></label>
    <p v-if="changed" role="status">{{ zh?'参数已修改，结果未更新':'Parameters changed; results not updated' }}</p>
    <p v-if="selected" class="source-identity" :title="state().runId">{{ selected.id }} · {{ space(selected) }}</p>
    <p v-else role="status">{{ message }}</p>
  </section>
</template>
<script setup lang="ts">
import {computed,inject} from 'vue'
import {useI18n} from 'vue-i18n'
import {parameterPreviewStateKey,type ParameterCloudPreview} from '@/workflows/workflow-editor/parameters/editor-context'
import {object} from './form'
const props=defineProps<{modelValue:string;previews:ParameterCloudPreview[];changed?:boolean}>(),emit=defineEmits<{'update:modelValue':[value:string]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false,phase:'idle' as const}))
const selected=computed(()=>props.previews.find(v=>v.id===props.modelValue))
const message=computed(()=>{
  if(props.previews.length)return zh.value?'尚未选择当前显示':'Current display not selected'
  const phase=state().phase
  return phase==='running'?(zh.value?'当前 Preview 正在运行':'Current Preview is running'):phase==='failed'?(zh.value?'当前 Preview 未成功':'Current Preview did not succeed'):phase==='stale'?(zh.value?'结果已过期，需重新 Preview':'Results expired; Preview required'):(zh.value?'没有当前成功运行的三维显示':'No 3D display from a current successful run')
})
function space(view:ParameterCloudPreview){const s=object(view.payload.spatial);return `${s.frame_id??'-'} / ${s.length_unit??'-'}`}
</script>
<style scoped>
.preview-source{display:grid;gap:6px;min-width:0}label{display:grid;gap:4px;font-size:12px}select{width:100%;min-width:0;padding:6px;border:1px solid var(--am-border);border-radius:4px;background:var(--am-input);color:var(--am-text)}p{margin:0;font-size:12px;overflow-wrap:anywhere}.source-identity{color:var(--am-text-muted)}
</style>
