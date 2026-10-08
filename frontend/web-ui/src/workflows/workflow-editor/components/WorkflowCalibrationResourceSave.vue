<template>
  <button type="button" class="calibration-save" :disabled="!result || !project.selectedProjectId" @mousedown.stop @click.stop="show">{{ text.open }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" :title="text.open" :confirm-label="text.save" :cancel-label="text.cancel" confirm-variant="primary" :confirm-disabled="!result || !name.trim() || !!saved" :busy="busy" @cancel="close" @confirm="save">
      <div class="calibration-save-form">
        <p v-if="!result" role="alert">{{ text.stale }}</p>
        <template v-else>
          <p>{{ result.image_width }} × {{ result.image_height }} · {{ result.unit }} · {{ result.plane_id }}</p>
          <p>{{ text.error }}: {{ formatResultValue(result.validation_max_error) }} · {{ text.fit }}: {{ formatResultValue(result.fit_rms) }} {{ result.unit }}</p>
          <p>{{ text.scope }}</p>
        </template>
        <label>{{ text.name }}<input v-model="name" maxlength="128"></label>
        <label>{{ text.version }}<SelectField v-model="resourceId" :options="[{value:'',label:text.create},...resources.map(r=>({value:r.reference.resource_id,label:r.name}))]" /></label>
        <p v-if="error" role="alert">{{ error }}</p>
        <p v-if="saved" role="status">{{ saved }} · {{ text.saved }}</p>
      </div>
    </ConfirmDialog>
  </Teleport>
</template>
<script setup lang="ts">
import { computed, inject, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { formatResultValue } from '@/shared/ui/image-viewer/result-geometry'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import { useProjectStore } from '@/app/stores/project.store'
import { parameterPreviewStateKey } from '../parameters/editor-context'
import { currentCalibration } from '../parameters/calibration-preview'
import type { PreviewNodeDisplay } from '../preview/useWorkflowPreviewDisplays'
import { listMeasurementResources, saveMeasurementResource, type MeasurementResourceDocument } from '../services/measurement-resource.service'
const props=defineProps<{parameters:Record<string,unknown>;display?:PreviewNodeDisplay|null}>()
const state=inject(parameterPreviewStateKey,undefined), project=useProjectStore(), {locale}=useI18n()
const result=computed(()=>currentCalibration(props.display,props.parameters,state?.()))
const text=computed(()=>locale.value==='zh-CN'?{open:'保存为标定资源',save:'保存版本',cancel:'关闭',name:'资源名称',version:'版本目标',create:'新建资源',error:'独立验证最大误差',fit:'拟合 RMS',scope:'此平面映射仅适用于相同成像条件和测量平面；不是相机内参。保存后在测量节点显式选择版本。',stale:'预览已改变或未成功完成，请重新预览。',saved:'已保存；现有节点和运行实例不会自动切换。'}:{open:'Save calibration resource',save:'Save version',cancel:'Close',name:'Resource name',version:'Version target',create:'New resource',error:'Independent maximum error',fit:'Fit RMS',scope:'This plane mapping requires the same imaging conditions and plane. It is not camera intrinsics. Select its version explicitly in measurement nodes.',stale:'Preview changed or did not succeed. Run again.',saved:'Saved; existing nodes and runtimes are unchanged.'})
const open=ref(false),busy=ref(false),name=ref(''),error=ref(''),saved=ref(''),resourceId=ref<string|number|boolean|null>(''),resources=ref<MeasurementResourceDocument[]>([])
let generation=0,controller:AbortController|undefined
function close(){generation++;controller?.abort();controller=undefined;open.value=false;busy.value=false}
async function show(){
  if(!result.value)return
  close();open.value=true;name.value=String(result.value.plane_id);saved.value='';error.value='';resourceId.value='';resources.value=[]
  const token=generation;controller=new AbortController()
  try{const items=await listMeasurementResources(project.selectedProjectId,controller.signal);if(token===generation)resources.value=[...new Map(items.filter(r=>r.reference.kind==='planar-calibration').map(r=>[r.reference.resource_id,r])).values()]}
  catch(e){if(token===generation)error.value=String(e)}
}
async function save(){
  if(!result.value||busy.value||!name.value.trim()||saved.value)return
  const token=generation,body=new FormData();body.set('name',name.value.trim());body.set('content',JSON.stringify({kind:'planar-calibration',calibration:result.value}));if(resourceId.value)body.set('resource_id',String(resourceId.value))
  busy.value=true;error.value=''
  try{const item=await saveMeasurementResource(project.selectedProjectId,body,controller?.signal);if(token===generation)saved.value=`${item.name} · v${item.reference.version}`}
  catch(e){if(token===generation)error.value=String(e)}finally{if(token===generation)busy.value=false}
}
watch(()=>project.selectedProjectId,close)
onBeforeUnmount(close)
</script>
<style scoped>
.calibration-save { padding:6px 8px; color:var(--am-text); background:var(--am-input); border:1px solid var(--am-border); border-radius:var(--am-radius-sm); font:inherit; cursor:pointer; }
.calibration-save:disabled { opacity:.5; cursor:default; }
.calibration-save-form { display:grid; gap:12px; font-size:13px; }
label { display:grid; gap:6px; }
input { padding:8px; border:1px solid var(--am-border); background:var(--am-input); color:var(--am-text); font:inherit; }
input:focus-visible { outline:2px solid var(--am-input-focus-ring); }
[role=alert] { color:var(--am-danger-text); }
</style>
