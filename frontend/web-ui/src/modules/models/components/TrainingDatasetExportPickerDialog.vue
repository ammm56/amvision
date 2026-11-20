<template>
  <ModelPickerDialogShell class="training-export-picker" :open="open" :loading="loading || namesLoading" compact :title="title" :close-label="closeLabel"
    :list-title="zh ? '数据集' : 'Datasets'" :list-count="groups.length" :detail-title="zh ? '版本与导出' : 'Versions and exports'" @close="$emit('close')">
    <template #toolbar>
      <label class="input-with-icon training-export-picker__search">
        <Search :size="16" aria-hidden="true" />
        <input :value="searchValue" :aria-label="searchLabel" :placeholder="searchLabel" @input="$emit('update:searchValue', ($event.target as HTMLInputElement).value)" />
      </label>
    </template>
    <template #list>
      <div class="training-export-picker__list">
        <p v-if="namesLoading" class="training-export-picker__hint" role="status">{{ zh ? '正在读取数据集名称和版本…' : 'Loading dataset names and versions…' }}</p>
        <p v-else-if="namesError" class="training-export-picker__hint" role="status">
          {{ zh ? '部分数据集名称暂不可用。' : 'Some dataset names are unavailable.' }}
          <Button size="sm" variant="ghost" @click="$emit('retry-names')">{{ zh ? '重试' : 'Retry' }}</Button>
        </p>
        <p v-if="!groups.length && !namesLoading" class="training-export-picker__hint">
          {{ exports.length ? (zh ? '没有符合条件的数据集' : 'No matching datasets') : emptyTitle }}
        </p>
        <button v-for="group in groups" :key="group.id" class="training-export-picker__dataset" type="button"
          :aria-pressed="group.id === selectedGroup?.id" @click="selectDataset(group)">
          <Database :size="17" aria-hidden="true" />
          <strong>{{ group.name }}</strong>
          <small>{{ group.exports.length }} {{ zh ? '条导出' : 'exports' }}</small>
          <ChevronRight :size="16" aria-hidden="true" />
        </button>
      </div>
    </template>
    <template #detail>
      <div class="training-export-picker__list" v-if="selectedGroup && selectedExport">
        <fieldset class="training-export-picker__versions">
          <legend>{{ selectedGroup.name }}</legend>
          <label v-for="item in selectedGroup.exports" :key="item.dataset_export_id" class="training-export-picker__export"
            :class="{ 'is-selected': item.dataset_export_id === selectedExport.dataset_export_id, 'is-disabled': !canUse(item) }">
            <input type="radio" :name="radioName" :checked="item.dataset_export_id === selectedExport.dataset_export_id" :disabled="!canUse(item)"
              @change="$emit('select-export', item.dataset_export_id)" />
            <span class="training-export-picker__export-copy">
              <strong>{{ versionLabel(item) }} · {{ datasetFormatLabel(item.format_id) }}</strong>
              <small>{{ count(item.sample_count) }} {{ zh ? '样本' : 'samples' }} · {{ formatSystemDateTime(item.created_at, 'minutes') }}</small>
            </span>
            <small :class="{ 'is-ready': canUse(item) }">{{ stateLabel(item) }}</small>
          </label>
        </fieldset>
        <div class="training-export-picker__categories">
          <strong>{{ zh ? '类别' : 'Classes' }} ({{ selectedExport.category_names.length }})</strong>
          <span>{{ selectedExport.category_names.join(' / ') || '—' }}</span>
        </div>
      </div>
      <p v-else class="training-export-picker__hint">{{ zh ? '选择数据集以查看它的训练导出。' : 'Select a dataset to see its training exports.' }}</p>
    </template>
    <template #footer>
      <Button @click="$emit('close')">{{ zh ? '取消' : 'Cancel' }}</Button>
      <Button variant="primary" :disabled="loading || !selectedExport || !canUse(selectedExport)" @click="applyExport">{{ applyLabel }}</Button>
    </template>
  </ModelPickerDialogShell>
</template>

<script setup lang="ts">
import { computed, useId } from 'vue'
import { ChevronRight, Database, Search } from '@lucide/vue'
import { useI18n } from 'vue-i18n'
import { datasetFormatLabel } from '@/modules/datasets/dataset-workspace'
import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import ModelPickerDialogShell from '@/shared/ui/components/ModelPickerDialogShell.vue'

interface DatasetGroup { id: string; name: string; exports: DatasetExportSummary[] }

const props = defineProps<{
  open: boolean
  loading: boolean
  namesLoading: boolean
  namesError: boolean
  title: string
  closeLabel: string
  searchValue: string
  applyLabel: string
  emptyTitle: string
  exports: DatasetExportSummary[]
  selectedExportId: string | null
  supportedFormats?: string[]
}>()

const emit = defineEmits<{
  close: []
  'update:searchValue': [value: string]
  'select-export': [datasetExportId: string]
  'apply-export': [datasetExport: DatasetExportSummary]
  'retry-names': []
}>()

const { locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const searchLabel = computed(() => zh.value ? '搜索数据集名称、版本或类别' : 'Search dataset names, versions, or classes')
const radioName = useId()

function versionLabel(item: DatasetExportSummary): string {
  return item.version_number ? `v${item.version_number}` : zh.value ? '版本未登记' : 'Unnumbered version'
}

function canUse(item: DatasetExportSummary): boolean {
  return !item.metadata?.files_cleaned_at && !!item.manifest_object_key?.trim()
    && (!props.supportedFormats?.length || props.supportedFormats.some(format => format.toLowerCase() === item.format_id.toLowerCase()))
}

function stateLabel(item: DatasetExportSummary): string {
  if (item.metadata?.files_cleaned_at) return zh.value ? '文件已清理' : 'Files cleaned'
  if (!item.manifest_object_key?.trim()) return zh.value ? '缺少导出清单' : 'Manifest missing'
  if (!canUse(item)) return zh.value ? '格式不兼容' : 'Incompatible format'
  return zh.value ? '已完成' : 'Completed'
}

function count(value: number): string {
  return value.toLocaleString(locale.value)
}

const groups = computed(() => {
  const grouped = new Map<string, DatasetGroup>()
  const terms = props.searchValue.trim().toLocaleLowerCase(locale.value).split(/\s+/).filter(Boolean)
  const names = new Map(props.exports.filter(item => item.display_name).map(item => [item.dataset_id, item.display_name!]))
  for (const item of props.exports) {
    const name = names.get(item.dataset_id) || item.package_file_name || (zh.value ? '数据集名称暂不可用' : 'Dataset name unavailable')
    const searchable = [name, datasetFormatLabel(item.format_id), item.format_id, item.dataset_export_id,
      item.dataset_id, item.dataset_version_id, ...item.category_names].join(' ').toLocaleLowerCase(locale.value)
    if (!terms.every(term => /^v\d+$/.test(term) ? term === `v${item.version_number}` : searchable.includes(term))) continue
    let group = grouped.get(item.dataset_id)
    if (!group) {
      group = { id: item.dataset_id, name, exports: [] }
      grouped.set(group.id, group)
    }
    group.exports.push(item)
  }
  return [...grouped.values()]
})

const selectedGroup = computed(() => groups.value.find(group => group.exports.some(item => item.dataset_export_id === props.selectedExportId)) ?? groups.value[0])
const selectedExport = computed(() => selectedGroup.value?.exports.find(item => item.dataset_export_id === props.selectedExportId)
  ?? selectedGroup.value?.exports.find(canUse) ?? selectedGroup.value?.exports[0])

function selectDataset(group: DatasetGroup): void {
  const item = group.exports.find(item => item.dataset_export_id === props.selectedExportId) ?? group.exports.find(canUse) ?? group.exports[0]
  if (item) emit('select-export', item.dataset_export_id)
}

function applyExport(): void {
  if (selectedExport.value && canUse(selectedExport.value) && !props.loading) emit('apply-export', selectedExport.value)
}
</script>

<style scoped>
.training-export-picker :deep(.model-picker-shell) { height:auto; min-height:min(460px,calc(100dvh - 36px)); max-height:min(680px,calc(100dvh - 36px)); }
.training-export-picker__search { width:100%; }
.training-export-picker__list { display:grid; align-content:start; gap:8px; min-height:0; min-width:0; padding:2px 5px 2px 2px; overflow:auto; overscroll-behavior:contain; scrollbar-gutter:stable; }
.training-export-picker__dataset,.training-export-picker__export { display:flex; align-items:center; gap:10px; min-width:0; padding:10px 12px; border:1px solid var(--am-border); border-radius:6px; background:var(--am-surface); color:var(--am-text); text-align:start; cursor:pointer; }
.training-export-picker__dataset strong,.training-export-picker__export-copy { flex:1; min-width:0; overflow-wrap:anywhere; }
.training-export-picker__dataset svg,.training-export-picker__export input { flex:none; }
.training-export-picker__dataset:hover,.training-export-picker__export:not(.is-disabled):hover { background:var(--am-hover-surface); }
.training-export-picker__dataset[aria-pressed='true'],.training-export-picker__export.is-selected { border-color:var(--am-action-primary); background:var(--am-row-selected); }
.training-export-picker__dataset small,.training-export-picker__export small,.training-export-picker__hint,.training-export-picker__categories span { color:var(--am-text-muted); }
.training-export-picker__export-copy { display:grid; gap:3px; }
.training-export-picker__export input { accent-color:var(--am-action-primary); }
.training-export-picker__export.is-disabled { cursor:not-allowed; }
.training-export-picker__export .is-ready { color:var(--am-success-text); }
.training-export-picker__versions { display:grid; gap:8px; padding:0; margin:0; border:0; min-inline-size:0; }
.training-export-picker__versions legend { margin-block-end:8px; color:var(--am-text-strong); font-weight:600; overflow-wrap:anywhere; }
.training-export-picker__categories { display:grid; gap:5px; padding:10px 12px; border:1px solid var(--am-border); border-radius:6px; overflow-wrap:anywhere; }
.training-export-picker__hint { margin:0; padding:8px 10px; overflow-wrap:anywhere; }
@media (max-width:960px) { .training-export-picker__list { max-height:260px; } }
</style>
