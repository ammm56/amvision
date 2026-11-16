<template>
  <section class="preview-source">
    <div v-if="ports.length" class="input-preview">
      <label>{{ zh?'本节点点云输入':'This node input' }}<select v-model="inputPort"><option v-for="port in ports" :key="port" :value="port">{{ port }}</option></select></label>
      <button :disabled="!connected||busy||state().phase==='running'" @click="loadInput"><RefreshCw :size="16" />{{ zh?'查看输入点云':'Preview input cloud' }}</button>
    </div>
    <p v-if="error" role="alert">{{ error }}</p>
    <p v-if="state().error" role="alert">{{ state().error }}</p>
    <label>{{ zh?'点云显示':'Point cloud view' }}<select :value="modelValue" @change="emit('update:modelValue',($event.target as HTMLSelectElement).value)"><option value="">{{ zh?'未选择':'None' }}</option><option v-for="view in views" :key="view.id" :value="view.id">{{ view.label }} · {{ space(view) }}</option></select></label>
    <p v-if="changed" role="status">{{ zh?'参数已修改，结果未更新':'Parameters changed; results not updated' }}</p>
    <p v-if="selected" class="source-identity" :title="state().runId">{{ selected.id }} · {{ space(selected) }}</p>
    <p v-else role="status">{{ message }}</p>
  </section>
</template>
<script setup lang="ts">
import {computed,inject,onBeforeUnmount,ref,watch} from 'vue'
import {RefreshCw} from '@lucide/vue'
import {useI18n} from 'vue-i18n'
import {parameterPreviewStateKey,parameterNodeContextKey,parameterInputPreviewKey,type ParameterCloudPreview} from '@/workflows/workflow-editor/parameters/editor-context'
import {object} from './form'
const props=defineProps<{modelValue:string;previews:ParameterCloudPreview[];changed?:boolean}>(),emit=defineEmits<{'update:modelValue':[value:string]}>()
const {locale}=useI18n(),zh=computed(()=>locale.value==='zh-CN')
const state=inject(parameterPreviewStateKey,()=>({runId:'',succeeded:false,phase:'idle' as const}))
const context=inject(parameterNodeContextKey,undefined),request=inject(parameterInputPreviewKey,undefined)
const ports=computed(()=>context?.().cloudPorts??[]),inputPort=ref(''),busy=ref(false),error=ref('')
let generation=0
function invalidateRequest(){generation++;busy.value=false;error.value=''}
onBeforeUnmount(invalidateRequest)
watch(ports,values=>{if(!values.includes(inputPort.value))inputPort.value=values[0]??''},{immediate:true})
const source=computed(()=>{const sources=context?.().sources[inputPort.value]??[];return sources.length===1?sources[0]:undefined})
const connected=computed(()=>!!source.value&&!!request)
const views=computed(()=>ports.value.length?props.previews.filter(view=>view.sourceNodeId===source.value?.nodeId&&view.sourcePort===source.value?.outputPort):props.previews)
const selected=computed(()=>views.value.find(v=>v.id===props.modelValue))
watch(()=>[inputPort.value,context?.().nodeId,source.value?.nodeId,source.value?.outputPort],()=>{invalidateRequest();emit('update:modelValue','')},{flush:'sync'})
watch(()=>[views.value.map(view=>view.id).join('|'),props.modelValue],()=>{
  if(!selected.value)emit('update:modelValue',source.value&&ports.value.length&&views.value.length===1?views.value[0]!.id:'')
},{immediate:true,flush:'post'})
async function loadInput(){
  if(!connected.value||busy.value)return
  const ticket=++generation;busy.value=true;error.value=''
  try{await request!(context!().nodeId,inputPort.value)}catch(cause){if(ticket===generation)error.value=cause instanceof Error?cause.message:String(cause)}finally{if(ticket===generation)busy.value=false}
}
const message=computed(()=>{
  if(ports.value.length&&!source.value)return zh.value?'点云输入需连接唯一上游':'Connect a unique upstream cloud'
  if(views.value.length)return zh.value?'尚未选择当前显示':'Current display not selected'
  const phase=state().phase
  return phase==='running'?(zh.value?'当前 Preview 正在运行':'Current Preview is running'):phase==='failed'?(zh.value?'当前 Preview 未成功':'Current Preview did not succeed'):phase==='stale'?(zh.value?'结果已过期，需重新 Preview':'Results expired; Preview required'):(zh.value?'没有当前成功运行的三维显示':'No 3D display from a current successful run')
})
function space(view:ParameterCloudPreview){const s=object(view.payload.spatial);return `${s.frame_id??'-'} / ${s.length_unit??'-'}`}
</script>
<style scoped>
.preview-source{display:grid;gap:6px;min-width:0}label{display:grid;gap:4px;font-size:12px}select{width:100%;min-width:0;padding:6px;border:1px solid var(--am-border);border-radius:4px;background:var(--am-input);color:var(--am-text)}p{margin:0;font-size:12px;overflow-wrap:anywhere}.source-identity{color:var(--am-text-muted)}
.input-preview{display:flex;align-items:end;gap:8px;flex-wrap:wrap}.input-preview label{flex:1;min-width:100px}.input-preview button{display:flex;align-items:center;gap:6px;padding:7px;border:1px solid var(--am-border);border-radius:4px;background:var(--am-input);color:var(--am-text)}
@container(min-width:650px){.preview-source{grid-template-columns:minmax(0,1fr) minmax(0,1fr);align-items:end}.preview-source>p{grid-column:1/-1}}
</style>
