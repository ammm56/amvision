<template>
  <section v-if="items.length || error" class="form-panel imported-assets">
    <div class="section-heading"><h2>{{ tr('importedModels') }}</h2><Button variant="secondary" size="sm" @click="load">{{ tr('refresh') }}</Button></div>
    <InlineError :message="error" />
    <div v-for="item in items" :key="item.resource_id" class="imported-asset">
      <div><strong>{{ item.model_name }}</strong><p>{{ item.task_type }} · {{ item.kind }} · {{ (item.byte_size / 1024 / 1024).toFixed(1) }} MB · {{ tr('importOrigin') }}</p><small>{{ item.resource_id }}</small></div>
      <Button variant="danger" size="sm" @click="selected = item; error = ''">{{ tr('delete') }}</Button>
    </div>
    <Teleport to="body"><ConfirmDialog v-if="selected" :title="tr('deleteModel')" :message="tr('deleteModelMessage')" :details="selected.resource_id" :confirm-label="tr('delete')" :cancel-label="tr('cancel')" :busy="busy" @cancel="selected = null" @confirm="remove"><InlineError :message="error" /></ConfirmDialog></Teleport>
  </section>
</template>
<script setup lang="ts">
import { ref, watch } from 'vue'
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
const base = (id: string) => `/projects/${encodeURIComponent(id)}/model-deployment-transfers/assets`
async function load() {
  const project = props.projectId
  if (!project) { items.value = []; return }
  try { const result = await apiRequest<Asset[]>(`${base(project)}/list`); if (project === props.projectId) items.value = result }
  catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
}
async function remove() {
  if (!props.projectId || !selected.value) return
  busy.value = true; error.value = ''
  try { await apiRequest(`${base(props.projectId)}/${selected.value.kind}/${encodeURIComponent(selected.value.resource_id)}`, { method: 'DELETE', responseType: 'void' }); selected.value = null; await load() }
  catch (cause) { error.value = cause instanceof Error ? cause.message : String(cause) }
  finally { busy.value = false }
}
watch(() => props.projectId, () => { selected.value = null; error.value = ''; void load() }, { immediate: true })
</script>
<style scoped>
.imported-assets { padding: 16px; }
.imported-asset { display: flex; justify-content: space-between; align-items: center; gap: 16px; padding: 12px 0; overflow-wrap: anywhere; }
.imported-asset p, .imported-asset small { color: var(--am-text-muted); font-size: 12px; }
</style>
