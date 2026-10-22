<template>
  <button class="cloud-resource-open" type="button" :disabled="disabled || !project.selectedProjectId" @click="show"><FolderOpen :size="16" />{{ currentLabel }}</button>
  <Teleport to="body">
    <ConfirmDialog v-if="open" :title="t('resources')" :cancel-label="t('cancel')" :confirm-label="t('apply')" confirm-variant="primary" size="wide"
      :confirm-disabled="busy || disabled || !selectedDocument" @cancel="cancelSelection" @confirm="apply">
      <section class="cloud-resources" :aria-busy="busy">
        <div class="cloud-resource-actions">
          <button :title="t('refresh')" :aria-label="t('refresh')" :disabled="busy" @click="refresh"><RefreshCw :size="17" /></button>
          <label>{{ t('name') }}<input v-model="name" maxlength="128" :disabled="busy || disabled"></label>
          <label class="cloud-import">{{ t('import') }}<input type="file" accept=".zip,application/zip" :disabled="busy || disabled || !archiveLimit || !name.trim()" @change="importFile"></label>
          <button v-if="busy" :title="t('cancel')" :aria-label="t('cancel')" @click="cancelOperation"><X :size="17" /></button>
        </div>
        <p v-if="archiveLimit === null" role="status">{{ t('unconfigured') }}</p>
        <p v-if="error" role="alert" class="cloud-resource-error">{{ error }}</p>
        <p v-if="busy" role="status">{{ t('loading') }}</p>
        <div class="cloud-resource-list">
          <table><thead><tr><th>{{ t('name') }}</th><th>{{ t('version') }}</th><th>{{ t('points') }}</th><th>{{ t('unit') }}</th></tr></thead>
            <tbody><tr v-for="item in documents" :key="key(item.reference)" :class="{selected: selected === key(item.reference)}"><td><label><input v-model="selected" type="radio" name="cloud-resource" :value="key(item.reference)" :disabled="busy">{{ item.name }}</label></td><td>{{ item.reference.version }}</td><td>{{ item.content.point_cloud?.point_count }}</td><td>{{ item.content.point_cloud?.spatial.length_unit || t('unknown') }}</td></tr></tbody>
          </table>
          <p v-if="!busy && !documents.length">{{ t('empty') }}</p>
        </div>
        <template v-if="selectedDocument">
          <dl class="cloud-resource-summary"><dt>ID</dt><dd>{{ selectedDocument.reference.resource_id }}</dd><dt>SHA-256</dt><dd>{{ selectedDocument.reference.sha256 }}</dd><dt>{{ t('fields') }}</dt><dd>{{ selectedDocument.content.point_cloud?.fields.map(f => `${f.name}: ${f.dtype} x ${f.components}`).join(', ') }}</dd></dl>
          <div class="cloud-resource-actions">
            <button :title="t('export')" :disabled="busy || !archiveLimit" @click="exportSelected"><Download :size="17" />{{ t('export') }}</button>
            <button :title="t('delete')" :disabled="busy || disabled" @click="confirmDelete = true"><Trash2 :size="17" />{{ t('delete') }}</button>
          </div>
        </template>
      </section>
    </ConfirmDialog>
    <ConfirmDialog v-if="confirmDelete && selectedDocument" :title="t('delete')" :message="`${selectedDocument.name} · v${selectedDocument.reference.version}`" :cancel-label="t('cancel')" :confirm-label="t('delete')" :busy="busy" @cancel="confirmDelete = false" @confirm="removeSelected" />
  </Teleport>
</template>
<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { Download, FolderOpen, RefreshCw, Trash2, X } from '@lucide/vue'
import { useI18n } from 'vue-i18n'
import { useProjectStore } from '@/app/stores/project.store'
import { apiRequest } from '@/shared/api/http-client'
import ConfirmDialog from '@/shared/ui/components/ConfirmDialog.vue'
import { deleteMeasurementResource, importCloudResource, listMeasurementResources, readCloudCapabilities, resourceVersionPath, type MeasurementResourceDocument, type MeasurementResourceReference } from '../services/measurement-resource.service'
const props = defineProps<{ modelValue?: MeasurementResourceReference; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: MeasurementResourceReference]; cancel: [] }>()
const project = useProjectStore()
const { t } = useI18n({ useScope: 'local', messages: {
  'zh-CN': { resources: '点云资源', cancel: '取消', apply: '应用', refresh: '刷新', name: '名称', import: '导入资源包', export: '导出资源包', delete: '删除版本', version: '版本', points: '点数', unit: '单位', fields: '字段', unknown: '单位未确认', loading: '处理中', empty: '暂无点云资源', select: '选择点云资源', unconfigured: '点云资产包预算尚未配置', tooLarge: '资源包超过配置限额', unavailable: '资源不可用' },
  'en-US': { resources: 'Cloud resources', cancel: 'Cancel', apply: 'Apply', refresh: 'Refresh', name: 'Name', import: 'Import package', export: 'Export package', delete: 'Delete version', version: 'Version', points: 'Points', unit: 'Unit', fields: 'Fields', unknown: 'Unit unconfirmed', loading: 'Working', empty: 'No cloud resources', select: 'Select cloud resource', unconfigured: 'Cloud archive budget is not configured', tooLarge: 'Package exceeds configured limit', unavailable: 'Resource unavailable' },
} })
const open = ref(false), busy = ref(false), confirmDelete = ref(false), error = ref(''), name = ref(''), selected = ref('')
const documents = ref<MeasurementResourceDocument[]>([]), archiveLimit = ref<number | null>(null)
const key = (r: MeasurementResourceReference) => `${r.project_id}:${r.resource_id}:${r.version}:${r.sha256}`
const selectedDocument = computed(() => documents.value.find(d => key(d.reference) === selected.value))
const currentLabel = computed(() => props.modelValue ? `${props.modelValue.resource_id} · v${props.modelValue.version}` : t('select'))
let generation = 0, controller: AbortController | null = null, downloadUrl: string | null = null
function cancelOperation() { generation++; controller?.abort(); controller = null; busy.value = false }
function close() { cancelOperation(); open.value = false; confirmDelete.value = false; documents.value = []; if (downloadUrl) URL.revokeObjectURL(downloadUrl); downloadUrl = null }
function cancelSelection() { close(); emit('cancel') }
async function perform(action: (signal: AbortSignal, current: () => boolean) => Promise<void>) {
  cancelOperation(); const token = generation; controller = new AbortController(); const signal = controller.signal
  busy.value = true; error.value = ''
  try { await action(signal, () => !signal.aborted && token === generation && open.value) }
  catch (e) { if (!signal.aborted && token === generation) { confirmDelete.value = false; error.value = e instanceof Error ? e.message : t('unavailable') } }
  finally { if (token === generation) busy.value = false }
}
async function refresh() {
  const projectId = project.selectedProjectId
  await perform(async (signal, current) => {
    const capability = await readCloudCapabilities(projectId, signal)
    const items = await listMeasurementResources(projectId, signal)
    if (current()) { archiveLimit.value = capability.max_archive_bytes; documents.value = items.filter(d => d.reference.kind === 'point-cloud') }
  })
}
async function show() { close(); open.value = true; name.value = ''; error.value = ''; archiveLimit.value = null; selected.value = props.modelValue ? key(props.modelValue) : ''; await refresh() }
function apply() { if (!busy.value && !props.disabled && selectedDocument.value) { emit('update:modelValue', selectedDocument.value.reference); close() } }
async function importFile(event: Event) {
  const input = event.target as HTMLInputElement, file = input.files?.[0]; input.value = ''
  if (!file || props.disabled || !name.value.trim() || !archiveLimit.value) return
  if (file.size > archiveLimit.value) { error.value = t('tooLarge'); return }
  const projectId = project.selectedProjectId, requestedName = name.value.trim()
  await perform(async (signal, current) => {
    const result = await importCloudResource(projectId, file, requestedName, crypto.randomUUID(), signal)
    if (current()) { documents.value = [result, ...documents.value]; selected.value = key(result.reference) }
  })
}
async function exportSelected() {
  const item = selectedDocument.value
  if (!item || !archiveLimit.value) return
  await perform(async (signal, current) => {
    const blob = await apiRequest<Blob>(`${resourceVersionPath(item.reference)}/export`, { responseType: 'blob', signal, retryTransientRead: false })
    if (!current()) return
    if (downloadUrl) URL.revokeObjectURL(downloadUrl)
    downloadUrl = URL.createObjectURL(blob)
    const link = document.createElement('a'); link.href = downloadUrl; link.download = `${item.reference.resource_id}-v${item.reference.version}.zip`; link.click()
  })
}
async function removeSelected() {
  const item = selectedDocument.value
  if (!item || props.disabled) return
  await perform(async (signal, current) => {
    await deleteMeasurementResource(item.reference, signal)
    if (current()) { documents.value = documents.value.filter(d => key(d.reference) !== key(item.reference)); selected.value = ''; confirmDelete.value = false }
  })
}
watch(() => props.modelValue, close)
watch(() => [project.selectedProjectId, props.disabled], cancelSelection)
onBeforeUnmount(close)
defineExpose({ show })
</script>
<style scoped>
.cloud-resource-open { display: flex; align-items: center; gap: 6px; width: 100%; min-width: 0; overflow-wrap: anywhere; }
.cloud-resources { display: grid; gap: 12px; min-width: 0; font-size: 13px; }
.cloud-resource-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; }
.cloud-resource-actions button, .cloud-resource-open { border: 1px solid var(--am-border); border-radius: 4px; padding: 7px; background: var(--am-surface); color: var(--am-text); }
.cloud-resource-actions button { display: inline-flex; align-items: center; gap: 6px; }
.cloud-resource-actions label { display: flex; flex-direction: column; gap: 4px; }
.cloud-import input { max-width: 220px; }
.cloud-resource-list { overflow: auto; max-height: 280px; }
table { width: 100%; border-collapse: collapse; text-align: left; }
th, td { padding: 8px; border-bottom: 1px solid var(--am-border); white-space: nowrap; }
tr.selected { background: var(--am-surface-soft); }
td label { display: flex; align-items: center; gap: 8px; }
.cloud-resource-summary { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 14px; }
dd { margin: 0; overflow-wrap: anywhere; }
.cloud-resource-error { color: var(--am-danger-text); }
</style>
