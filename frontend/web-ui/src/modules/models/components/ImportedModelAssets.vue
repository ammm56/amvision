<template>
  <section v-if="items.length || error" class="resource-section imported-assets">
    <div class="section-heading"><h2>{{ tr('importedModels') }}</h2><Button variant="secondary" size="sm" @click="load">{{ tr('refresh') }}</Button></div>
    <InlineError :message="error" />
    <div v-if="items.length" class="resource-table">
      <table>
        <thead><tr>
          <th scope="col">{{ tr('model') }}</th><th scope="col">{{ tr('task') }}</th>
          <th scope="col">{{ tr('resourceType') }}</th><th scope="col">{{ tr('size') }}</th>
          <th scope="col">{{ tr('origin') }}</th><th scope="col">{{ tr('actions') }}</th>
        </tr></thead>
        <tbody><tr v-for="item in items" :key="item.resource_id">
          <td class="imported-model-name"><strong>{{ item.model_name }}</strong><span>{{ item.resource_id }}</span></td>
          <td>{{ item.task_type }}</td>
          <td>{{ item.kind === 'model-version' ? tr('modelVersion') : item.kind === 'model-build' ? tr('modelBuild') : item.kind }}</td>
          <td class="asset-size">{{ (item.byte_size / 1024 / 1024).toFixed(1) }} MB</td>
          <td>{{ tr('importOrigin') }}</td>
          <td><Button variant="danger" size="sm" @click="selected = item; error = ''">{{ tr('delete') }}</Button></td>
        </tr></tbody>
      </table>
    </div>
    <Teleport to="body"><ConfirmDialog v-if="selected" :title="tr('deleteModel')" :message="tr('deleteModelMessage')" :details="selected.resource_id" :confirm-label="tr('delete')" :cancel-label="tr('cancel')" :busy="busy" @cancel="selected = null" @confirm="remove"><InlineError :message="error" /></ConfirmDialog></Teleport>
  </section>
</template>
<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from 'vue'
import { translate } from '@/platform/i18n'
const tr = (key: string) => translate(`deploymentTransfer.${key}`)
import { apiRequest } from '@/shared/api/http-client'
import Button from '@/shared/ui/components/Button.vue'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
interface Asset { kind: string; resource_id: string; model_name: string; task_type: string; byte_size: number }
const props = defineProps<{ projectId: string | null }>()
const items = ref<Asset[]>([])
const selected = ref<Asset | null>(null)
const error = ref('')
const busy = ref(false)
let generation = 0
const base = (id: string) => `/projects/${encodeURIComponent(id)}/model-deployment-transfers/assets`
async function load() {
  const project = props.projectId
  const current = generation
  if (!project) { items.value = []; return }
  try {
    const result = await apiRequest<Asset[]>(`${base(project)}/list`)
    if (current === generation) { items.value = result; error.value = '' }
  }
  catch (cause) { if (current === generation) error.value = cause instanceof Error ? cause.message : String(cause) }
}
async function remove() {
  if (!props.projectId || !selected.value || busy.value) return
  const current = generation
  busy.value = true; error.value = ''
  try {
    await apiRequest(`${base(props.projectId)}/${selected.value.kind}/${encodeURIComponent(selected.value.resource_id)}`, { method: 'DELETE', responseType: 'void' })
    if (current === generation) { selected.value = null; await load() }
  }
  catch (cause) { if (current === generation) error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { if (current === generation) busy.value = false }
}
// 项目切换或卸载后，旧请求不能恢复列表、错误或删除弹窗。
watch(() => props.projectId, () => { generation++; items.value = []; selected.value = null; busy.value = false; error.value = ''; void load() }, { immediate: true })
onBeforeUnmount(() => { generation++ })
</script>
<style scoped>
.imported-assets table { min-width: 760px; }
.imported-model-name { width: 45%; overflow-wrap: anywhere; }
.asset-size { white-space: nowrap; font-variant-numeric: tabular-nums; }
</style>
