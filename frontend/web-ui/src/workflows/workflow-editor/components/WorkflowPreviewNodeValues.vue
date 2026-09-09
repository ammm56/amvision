<template>
  <section v-if="ports.length" class="workflow-graph-inspector-card">
    <div class="workflow-graph-inspector-card__header"><strong>{{ t('workflowEditor.editor.previewNodeOutputs') }}</strong></div>
    <label class="workflow-graph-preview-field">
      <span>{{ t('workflowEditor.editor.previewOutputPort') }}</span>
      <select v-model="selectedPort" @change="resetPage">
        <option v-for="port in ports" :key="String(port.output_port)" :value="String(port.output_port)">{{ port.output_port }}</option>
      </select>
    </label>
    <p v-if="descriptor?.kind === 'unavailable'" role="status">{{ descriptor.error }}</p>
    <template v-else>
      <Button v-if="descriptor?.kind === 'json' && !page" type="button" variant="secondary" size="sm" :disabled="loading" @click="read(0)">
        {{ t(loading ? 'workflowEditor.editor.previewValueLoading' : 'workflowEditor.editor.previewValueRead') }}
      </Button>
      <pre v-if="descriptor?.kind === 'inline' || page" class="json-view">{{ text }}</pre>
      <div v-if="page" class="workflow-graph-preview-binding__tools">
        <Button v-if="page.path.length" type="button" variant="secondary" size="sm" :disabled="loading" @click="read(0, page.path.slice(0, -1))">{{ t('workflowEditor.editor.previewValueParent') }}</Button>
        <Button type="button" variant="secondary" size="sm" :disabled="loading || page.offset === 0" @click="read(Math.max(0, page.offset - page.limit))">{{ t('workflowEditor.editor.previewValuePrevious') }}</Button>
        <span>{{ page.total ? page.offset + 1 : 0 }}–{{ Math.min(page.total, page.offset + page.limit) }} / {{ page.total }}</span>
        <Button type="button" variant="secondary" size="sm" :disabled="loading || !page.has_more" @click="read(page.offset + page.limit)">{{ t('workflowEditor.editor.previewValueNext') }}</Button>
      </div>
      <div v-if="page?.children.length" class="workflow-graph-preview-binding__tools">
        <Button v-for="child in page.children" :key="String(child.key)" type="button" variant="secondary" size="sm" :disabled="loading" @click="read(0, child.path)">{{ child.key }} · {{ child.total }}</Button>
      </div>
    </template>
    <p v-if="error" role="alert">{{ error }}</p>
  </section>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useTranslation } from '@/platform/i18n'
import Button from '@/shared/ui/components/Button.vue'
import type { WorkflowPreviewRun, WorkflowJsonObject } from '../types'
import type { PreviewValuePage } from '../services/workflow-preview-session.service'

const props = defineProps<{ run: WorkflowPreviewRun; nodeId: string }>()
const { t } = useTranslation()
const ports = computed(() => (props.run.values ?? []).filter(item => item.node_id === props.nodeId))
const selectedPort = ref('')
const selected = computed(() => ports.value.find(item => item.output_port === selectedPort.value))
const descriptor = computed(() => selected.value?.value as WorkflowJsonObject | undefined)
const page = ref<PreviewValuePage | null>(null)
const loading = ref(false)
const error = ref('')
let generation = 0
const text = computed(() => JSON.stringify(page.value ? page.value.value : descriptor.value?.value, null, 2))
function resetPage() { generation++; page.value = null; error.value = ''; loading.value = false }
watch(() => [props.run.preview_run_id, props.nodeId], () => { selectedPort.value = ''; resetPage() })
watch(ports, () => {
  if (!ports.value.some(item => item.output_port === selectedPort.value)) selectedPort.value = String(ports.value[0]?.output_port ?? '')
}, { immediate: true })
watch(() => selected.value?.revision, resetPage)
async function read(offset: number, path = page.value?.path ?? []) {
  const blobId = descriptor.value?.blob_id
  if (typeof blobId !== 'string' || !props.run.readValue) return
  const token = ++generation
  loading.value = true; error.value = ''
  try {
    const result = await props.run.readValue(blobId, offset, path)
    if (token === generation) page.value = result
  } catch (reason) { if (token === generation) error.value = reason instanceof Error ? reason.message : String(reason) }
  finally { if (token === generation) loading.value = false }
}
</script>

<style scoped>
pre { max-height: 280px; overflow: auto; overflow-wrap: anywhere; white-space: pre-wrap; }
select { min-width: 0; width: 100%; }
</style>
