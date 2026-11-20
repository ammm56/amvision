<template>
  <SideDrawer panel-class="model-drawer" :open="open" :title="title" :close-label="closeLabel" @close="$emit('close')">
    <div class="base-picker__toolbar">
      <label class="base-picker__search"><Search :size="16" /><input v-model.trim="query" :aria-label="zh ? '搜索模型名称' : 'Search models'" :placeholder="zh ? '搜索模型名称' : 'Search models'" /></label>
      <span>{{ zh ? '任务' : 'Task' }}</span>
      <Select :model-value="selectedTaskType" :options="taskTypeOptions" :aria-label="zh ? '任务类型' : 'Task type'" @update:model-value="$emit('change-task-type', String($event))" />
    </div>
    <label class="base-picker__mode"><input v-model="structureOnly" type="checkbox" /> {{ zh ? '仅选择模型结构（从头训练）' : 'Select architecture only (train from scratch)' }}</label>
    <p v-if="loading && !models.length" role="status" class="base-picker__state">{{ detailLoadingLabel }}</p>
    <div v-else-if="listError && !models.length" role="alert" class="base-picker__state">{{ listError }} <Button size="sm" @click="$emit('retry-list')">{{ retryLabel }}</Button></div>
    <div v-else class="resource-table base-picker__table" :aria-busy="loading">
      <table><thead><tr><th></th><th>{{ zh ? '模型名称' : 'Model' }}</th><th>{{ zh ? '任务' : 'Task' }}</th><th>{{ zh ? '来源' : 'Source' }}</th><th>{{ zh ? '文件状态' : 'File status' }}</th></tr></thead>
        <tbody><tr v-for="model in filteredModels" :key="model.model_id" :class="{ 'is-selected': model.model_id === selectedModelId, 'is-unavailable': !structureOnly && modelState(model) !== 'present' }" @click="(structureOnly || modelState(model) === 'present') && $emit('select-model', model.model_id)">
          <td><input type="radio" name="base-model" :checked="model.model_id === selectedModelId" :disabled="!structureOnly && modelState(model) !== 'present'" :aria-label="modelName(model)" @click.stop="$emit('select-model', model.model_id)" /></td>
          <td>{{ modelName(model) }}</td><td>{{ model.task_type }}</td><td>{{ zh ? '本地预置' : 'Local' }}</td><td :class="`base-picker__${modelState(model)}`">{{ stateText(modelState(model)) }}</td>
        </tr><tr v-if="!filteredModels.length"><td colspan="5" class="base-picker__state">{{ query ? (zh ? '没有符合条件的模型' : 'No matching models') : emptyTitle }}</td></tr></tbody>
      </table>
    </div>
    <h3 class="base-picker__heading">{{ currentSelectionLabel }}</h3>
    <p v-if="detailLoading" role="status" class="base-picker__state">{{ detailLoadingLabel }}</p>
    <div v-else-if="detailError" role="alert" class="base-picker__state">{{ detailError }} <Button size="sm" @click="$emit('retry-detail')">{{ retryLabel }}</Button></div>
    <div v-else-if="selectedModelDetail" class="base-picker__detail">
      <div class="base-picker__identity"><Box :size="22" /><strong>{{ modelName(selectedModelDetail) }}</strong><span>{{ selectedModelDetail.task_type }}</span></div>
      <dl><div><dt>{{ zh ? '模型结构' : 'Architecture' }}</dt><dd>{{ modelName(selectedModelDetail) }}</dd></div><div><dt>{{ zh ? '文件名' : 'File' }}</dt><dd>{{ checkpointName }}</dd></div><div><dt>{{ zh ? '资源版本' : 'Resource version' }}</dt><dd>{{ selectedBaseVersion ? modelVersionDisplayName(selectedBaseVersion) : '—' }}</dd></div></dl>
      <p class="base-picker__note">{{ zh ? '文件存在性不代表内容或设备兼容性已校验。' : 'File presence does not verify contents or device compatibility.' }}</p>
    </div>
    <p v-else class="base-picker__state">{{ detailEmptyTitle }}</p>
    <details v-if="extraVersions?.length && selectedModelDetail" class="base-picker__versions"><summary>{{ extraVersionsTitle }} ({{ extraVersions.length }})</summary>
      <div v-for="version in extraVersions" :key="version.model_version_id" class="base-picker__version"><span>{{ version.title }}</span><Button size="sm" @click="$emit('apply-training-version', { model: selectedModelDetail, modelVersionId: version.model_version_id })">{{ applyTrainingVersionLabel }}</Button></div>
    </details>
    <template #footer><div class="base-picker__footer"><Button @click="$emit('close')">{{ zh ? '取消' : 'Cancel' }}</Button><Button variant="primary" :disabled="!selectedModelDetail || detailLoading || loading || (!structureOnly && (!selectedBaseVersion || selectedState !== 'present'))" @click="confirmSelection">{{ zh ? '使用所选模型' : 'Use model' }}</Button></div></template>
  </SideDrawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Box, Search } from '@lucide/vue'
import SideDrawer from '@/shared/ui/components/SideDrawer.vue'
import Button from '@/shared/ui/components/Button.vue'
import Select from '@/shared/ui/components/Select.vue'
import type { PlatformBaseModelDetail, PlatformBaseModelSummary } from '../services/model.service'
import { modelVersionDisplayName } from '../model-display-name'

interface VersionListItem { model_version_id: string; source_kind: string; title: string; subtitle: string }
const props = defineProps<{
  open: boolean; loading: boolean; listError?: string | null; detailLoading: boolean; detailError?: string; retryLabel: string
  title: string; closeLabel: string; taskTypeOptions: Array<{ label: string; value: string }>; selectedTaskType: string
  modelListTitle: string; modelNameLabel: string; detailTitle: string; detailLoadingLabel: string; currentSelectionLabel: string
  versionSelectionLabel: string; versionsTitle: string; extraVersionsTitle: string; scaleLabel: string; applyModelLabel: string
  applyTrainingVersionLabel: string; emptyTitle: string; emptyDescription: string; detailEmptyTitle: string; detailEmptyDescription: string
  emptyVersionsTitle: string; emptyVersionsDescription: string; models: PlatformBaseModelSummary[]; selectedModelId: string | null
  selectedModelDetail: PlatformBaseModelDetail | null; extraVersions?: VersionListItem[]; selectedVersionId?: string
}>()
const emit = defineEmits<{ close: []; 'change-task-type': [taskType: string]; 'select-model': [modelId: string]; 'apply-model': [model: PlatformBaseModelDetail]; 'apply-training-version': [payload: { model: PlatformBaseModelDetail; modelVersionId: string }]; 'retry-detail': []; 'retry-list': [] }>()
const { locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const query = ref('')
const structureOnly = ref(false)
watch(() => props.open, open => { if (!open) { query.value = ''; structureOnly.value = false } })
function modelName(model: PlatformBaseModelSummary): string { return [model.model_name, model.model_scale].filter(Boolean).join('-') }
const filteredModels = computed(() => props.models.filter(model => modelName(model).toLowerCase().includes(query.value.toLowerCase())))
function modelState(model: PlatformBaseModelSummary): string {
  const states = model.available_versions.map(version => version.checkpoint_state)
  if (states.includes('present')) return 'present'
  if (states.includes('unavailable')) return 'unavailable'
  if (states.length && states.every(state => state === 'missing')) return 'missing'
  return 'unknown'
}
function stateText(state: string): string {
  const labels: Record<string, string> = zh.value ? { present: '文件存在', missing: '文件缺失', unavailable: '无法检查', unknown: '未检查' } : { present: 'File present', missing: 'File missing', unavailable: 'Unavailable', unknown: 'Not checked' }
  return labels[state] || labels.unknown
}
const selectedSummary = computed(() => props.models.find(model => model.model_id === props.selectedModelId))
const selectedState = computed(() => selectedSummary.value ? modelState(selectedSummary.value) : 'unknown')
const selectedBaseVersion = computed(() => selectedSummary.value?.available_versions.find(version => version.checkpoint_state === 'present') ?? selectedSummary.value?.available_versions[0])
const checkpointName = computed(() => selectedBaseVersion.value?.checkpoint_storage_uri?.split(/[\\/]/).pop() || '—')
function confirmSelection(): void {
  if (!props.selectedModelDetail) return
  if (structureOnly.value) emit('apply-model', props.selectedModelDetail)
  else if (selectedState.value === 'present' && selectedBaseVersion.value) emit('apply-training-version', { model: props.selectedModelDetail, modelVersionId: selectedBaseVersion.value.model_version_id })
}
</script>

<style scoped>
.base-picker__toolbar { display:flex; align-items:center; gap:12px; margin-bottom:20px; }
.base-picker__toolbar :deep(.ui-select) { width:150px; flex-shrink:0; }
.base-picker__mode { display:flex; align-items:center; gap:8px; margin:-8px 0 14px; color:var(--am-text-muted); }
.base-picker__search { display:flex; align-items:center; gap:8px; flex:1; min-width:0; padding:0 12px; border:1px solid var(--am-border); border-radius:6px; }
.base-picker__search input { width:100%; min-width:0; height:40px; border:0; outline:0; background:transparent; color:var(--am-text); }
.base-picker__table { max-height:min(42vh, 340px); border:1px solid var(--am-border); border-radius:6px; overflow:auto; }
.base-picker__table table { width:100%; table-layout:fixed; }
.base-picker__table :is(td,th) { overflow-wrap:anywhere; }
.base-picker__table th:first-child { width:42px; }
.base-picker__table tbody tr { cursor:pointer; }
.base-picker__table tbody tr.is-unavailable { cursor:not-allowed; color:var(--am-text-muted); }
.base-picker__table tr.is-selected { background:var(--am-row-selected); }
.base-picker__table input { accent-color:var(--am-brand-primary); }
.base-picker__present { color:var(--am-brand-primary); }.base-picker__missing { color:var(--am-danger-text); }.base-picker__unknown,.base-picker__unavailable { color:var(--am-text-muted); }
.base-picker__heading { margin:28px 0 12px; font-size:15px; }
.base-picker__detail { padding:18px; border:1px solid var(--am-border); border-radius:6px; }
.base-picker__identity { display:flex; align-items:center; gap:12px; }.base-picker__identity span { color:var(--am-brand-primary); }
.base-picker__detail dl { margin:16px 0 0 34px; }.base-picker__detail dl div { display:grid; grid-template-columns:100px minmax(0,1fr); gap:8px; padding:6px 0; }.base-picker__detail dt { color:var(--am-text-muted); }.base-picker__detail dd { margin:0; overflow-wrap:anywhere; }
.base-picker__state,.base-picker__note { color:var(--am-text-muted); }.base-picker__state { padding:18px; text-align:center; }.base-picker__note { margin:12px 0 0; font-size:12px; }
.base-picker__versions { margin-top:20px; }.base-picker__version { display:flex; justify-content:space-between; align-items:center; gap:12px; padding:8px 0; }.base-picker__version span { overflow-wrap:anywhere; }
.base-picker__footer { display:flex; justify-content:flex-end; gap:10px; width:100%; }
@media (max-width:600px) { .base-picker__toolbar { flex-wrap:wrap; }.base-picker__search { flex-basis:100%; } }
</style>
