<template>
  <ModelPickerDialogShell
    :open="open" :loading="loading" compact :title="title" :close-label="closeLabel"
    :task-type-label="taskTypeLabel" :task-type-options="taskTypeOptions" :selected-task-type="selectedTaskType"
    :list-title="modelListTitle" :list-count="modelGroups.length" :detail-title="detailTitle"
    @close="$emit('close')" @change-task-type="$emit('change-task-type', $event)"
  >
    <template #list>
      <div class="model-picker__list">
        <label class="model-picker__search">
          <Search :size="16" aria-hidden="true" />
          <input v-model.trim="query" :aria-label="searchLabel" :placeholder="searchLabel" />
        </label>
        <p v-if="loading && !models.length" class="model-picker__state" role="status">{{ detailLoadingLabel }}</p>
        <div v-else-if="listError && !models.length" class="model-picker__state" role="alert">
          <span>{{ listError }}</span><Button size="sm" @click="$emit('retry-list')">{{ retryLabel }}</Button>
        </div>
        <p v-else-if="!modelGroups.length" class="model-picker__state">{{ query ? (zh ? '没有符合条件的模型' : 'No matching models') : emptyTitle }}</p>
        <div v-else class="model-picker__families" role="group" :aria-label="modelNameLabel">
          <button v-for="group in modelGroups" :key="group.key" type="button"
            class="model-picker__family-button" :aria-pressed="group.key === selectedGroup?.key" @click="selectFamily(group)">
            <Box :size="16" aria-hidden="true" />
            <strong>{{ group.name }}</strong>
            <ChevronRight :size="16" aria-hidden="true" class="model-picker__chevron" />
          </button>
        </div>
        <div v-if="selectedGroup" class="base-picker__scales">
          <strong>{{ scaleLabel }}</strong>
          <div class="base-picker__scale-options" role="group" :aria-label="scaleLabel">
            <button v-for="model in selectedGroup.models" :key="model.model_id" type="button" :aria-pressed="model.model_id === selectedModelId" @click="selectModel(model.model_id)">
              {{ model.model_scale || '—' }}
            </button>
          </div>
        </div>
      </div>
    </template>

    <template #detail>
      <div class="model-picker__details" :aria-busy="detailLoading">
        <p v-if="selectedSummary && detailLoading" class="model-picker__state" role="status">{{ detailLoadingLabel }}</p>
        <div v-else-if="selectedSummary && detailError" class="model-picker__state" role="alert">
          <span>{{ detailError }}</span><Button size="sm" @click="$emit('retry-detail')">{{ retryLabel }}</Button>
        </div>
        <template v-else-if="currentModel">
          <div class="model-picker__identity">
            <Box :size="20" aria-hidden="true" />
            <strong>{{ modelDisplayName(currentModel) }}</strong>
            <span v-if="currentModel.model_scale" class="model-picker__scale">{{ currentModel.model_scale }}</span>
          </div>
          <label v-if="!weightsOnly" class="model-picker__option" :class="{ 'is-selected': choice === '' }">
            <input type="radio" :name="choiceName" value="" :checked="choice === ''" @change="pendingChoice = ''" />
            <span>{{ zh ? '仅选择模型结构（从头训练）' : 'Select architecture only (train from scratch)' }}</span>
          </label>
          <div v-for="group in visibleVersionGroups" :key="group.id" class="model-picker__versions" role="group" :aria-label="group.title">
            <h3>{{ group.title }} <small v-if="group.versions.length">{{ group.versions.length }}</small></h3>
            <p v-if="!group.versions.length" class="model-picker__empty">{{ group.empty }}</p>
            <label v-for="version in group.versions" :key="version.id" class="model-picker__option"
              :class="{ 'is-selected': choice === version.id, 'is-disabled': version.state !== 'present' }">
              <input type="radio" :name="choiceName" :value="version.id" :checked="choice === version.id"
                :disabled="version.state !== 'present'" @change="pendingChoice = version.id" />
              <span class="model-picker__option-copy">
                <span class="model-picker__option-name"><strong v-if="version.name">{{ version.name }}</strong><span class="model-picker__version-number">{{ version.number }}</span></span>
                <small v-if="version.file">{{ version.file }}</small>
              </span>
              <span class="model-picker__status" :class="`is-${version.state}`">{{ stateText(version.state) }}</span>
            </label>
          </div>
        </template>
        <p v-else class="model-picker__state">{{ detailEmptyTitle }}</p>
      </div>
    </template>

    <template #footer>
      <Button @click="$emit('close')">{{ zh ? '取消' : 'Cancel' }}</Button>
      <Button variant="primary" :disabled="!canConfirm" @click="confirmSelection">{{ applyModelLabel }}</Button>
    </template>
  </ModelPickerDialogShell>
</template>

<script setup lang="ts">
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Box, ChevronRight, Search } from '@lucide/vue'
import Button from '@/shared/ui/components/Button.vue'
import ModelPickerDialogShell from '@/shared/ui/components/ModelPickerDialogShell.vue'
import type { PlatformBaseModelVersionListItem } from '../composables/usePlatformBaseModelSelection'
import type { PlatformBaseModelDetail, PlatformBaseModelSummary, PlatformBaseModelVersionSummary } from '../services/model.service'
import { modelDisplayName, modelVersionDisplayName } from '../model-display-name'

interface ModelGroup {
  key: string
  name: string
  models: PlatformBaseModelSummary[]
}

type CheckpointState = NonNullable<PlatformBaseModelVersionSummary['checkpoint_state']> | 'unknown'

const props = withDefaults(defineProps<{
  open: boolean
  loading: boolean
  listError?: string | null
  detailLoading: boolean
  detailError?: string
  weightsOnly?: boolean
  allowWeights?: boolean
  retryLabel: string
  title: string
  closeLabel: string
  taskTypeLabel: string
  taskTypeOptions: Array<{ label: string; value: string }>
  selectedTaskType: string
  modelListTitle: string
  modelNameLabel: string
  detailTitle: string
  detailLoadingLabel: string
  extraVersionsTitle: string
  scaleLabel: string
  applyModelLabel: string
  emptyTitle: string
  detailEmptyTitle: string
  models: PlatformBaseModelSummary[]
  selectedModelId: string | null
  selectedModelDetail: PlatformBaseModelDetail | null
  extraVersions?: PlatformBaseModelVersionListItem[]
  appliedModelId?: string
  selectedVersionId?: string
}>(), { allowWeights: true })

const emit = defineEmits<{
  close: []
  'change-task-type': [taskType: string]
  'select-model': [modelId: string]
  'apply-model': [model: PlatformBaseModelDetail]
  'apply-training-version': [payload: { model: PlatformBaseModelDetail; modelVersionId: string }]
  'retry-detail': []
  'retry-list': []
}>()

const { locale } = useI18n()
const zh = computed(() => locale.value.startsWith('zh'))
const searchLabel = computed(() => zh.value ? '搜索模型名称' : 'Search models')
const query = ref('')
const choiceName = useId()
const pendingChoice = ref<string | null>(null)
const scaleOrder = ['tiny', 'nano', 'n', 'xs', 'small', 's', 'medium', 'm', 'base', 'b', 'large', 'l', 'xl', 'x']
const scaleRank = new Map(scaleOrder.map((scale, index) => [scale, index]))

watch(() => props.open, open => { if (!open) query.value = '' })
watch(() => props.selectedTaskType, () => { query.value = '' })
watch([() => props.open, () => props.selectedTaskType, () => props.selectedModelId], () => { pendingChoice.value = null })

const modelGroups = computed(() => {
  const groups = new Map<string, ModelGroup>()
  const search = query.value.toLowerCase()
  for (const model of props.models) {
    const name = modelDisplayName(model)
    const key = model.model_type.trim().toLowerCase()
    if (![name, key, `${name}-${model.model_scale}`, `${key}-${model.model_scale}`].some(value => value.toLowerCase().includes(search))) continue
    const group = groups.get(key)
    if (group) group.models.push(model)
    else groups.set(key, { key, name, models: [model] })
  }
  for (const group of groups.values()) group.models.sort((left, right) => {
    const a = left.model_scale.toLowerCase()
    const b = right.model_scale.toLowerCase()
    return (scaleRank.get(a) ?? Infinity) - (scaleRank.get(b) ?? Infinity) || a.localeCompare(b, undefined, { numeric: true })
  })
  return [...groups.values()]
})
const selectedGroup = computed(() => modelGroups.value.find(group => group.models.some(model => model.model_id === props.selectedModelId)))
const selectedSummary = computed(() => selectedGroup.value?.models.find(model => model.model_id === props.selectedModelId))
const currentModel = computed(() => selectedSummary.value?.model_id === props.selectedModelDetail?.model_id ? props.selectedModelDetail : null)

function selectFamily(group: ModelGroup): void {
  if (group.key === selectedGroup.value?.key) return
  const model = group.models.find(item => item.available_versions.some(version => version.checkpoint_state === 'present')) ?? group.models[0]
  selectModel(model.model_id)
}

function selectModel(id: string): void {
  if (props.selectedModelId !== id) emit('select-model', id)
}

function fileName(uri?: string | null): string {
  return uri?.split(/[\\/]/).pop() || ''
}

function stateText(state: CheckpointState): string {
  const labels = zh.value
    ? { present: '文件存在', missing: '文件缺失', unavailable: '无法检查', unknown: '未检查' }
    : { present: 'File present', missing: 'File missing', unavailable: 'Unavailable', unknown: 'Not checked' }
  return labels[state]
}

const platformVersions = computed(() => (selectedSummary.value?.available_versions ?? []).map(version => ({
  id: version.model_version_id,
  name: '',
  number: modelVersionDisplayName(version, true),
  file: fileName(version.checkpoint_storage_uri),
  state: version.checkpoint_state ?? 'unknown' as const,
})))
const projectVersions = computed(() => (props.extraVersions ?? []).map(version => ({
  id: version.model_version_id,
  name: version.title,
  number: version.subtitle,
  file: fileName(version.checkpoint_storage_uri),
  state: version.checkpoint_state ?? 'unknown' as const,
})))
const versionGroups = computed(() => [
  { id: 'platform', title: zh.value ? '基础模型权重' : 'Base model weights', versions: platformVersions.value, empty: zh.value ? '暂无已登记的基础权重' : 'No registered base weights' },
  { id: 'project', title: props.extraVersionsTitle, versions: projectVersions.value, empty: zh.value ? '暂无匹配此模型和参数规模的项目训练版本' : 'No project versions match this model and size' },
])
const visibleVersionGroups = computed(() => props.allowWeights === false ? [] : versionGroups.value)
const versions = computed(() => visibleVersionGroups.value.flatMap(group => group.versions))
const choice = computed(() => {
  if (props.allowWeights === false) return ''
  if (pendingChoice.value !== null) return pendingChoice.value
  if (props.selectedVersionId && versions.value.some(version => version.id === props.selectedVersionId)) return props.selectedVersionId
  if (!props.weightsOnly && currentModel.value?.model_id && currentModel.value.model_id === props.appliedModelId && !props.selectedVersionId) return ''
  return platformVersions.value.find(version => version.state === 'present')?.id
})
const canConfirm = computed(() => Boolean(currentModel.value) && !props.loading && !props.detailLoading && !props.detailError
  && (choice.value === '' ? !props.weightsOnly : versions.value.some(version => version.id === choice.value && version.state === 'present')))

function confirmSelection(): void {
  if (!canConfirm.value || !currentModel.value) return
  if (choice.value === '') emit('apply-model', currentModel.value)
  else if (choice.value) emit('apply-training-version', { model: currentModel.value, modelVersionId: choice.value })
}
</script>

<style scoped src="./model-picker-fields.css"></style>
<style scoped>
.base-picker__scales { display: flex; align-items: center; flex-wrap: wrap; flex-shrink: 0; gap: 8px 12px; padding: 10px 12px; border: 1px solid var(--am-border); border-radius: 6px; color: var(--am-text-muted); font-size: 13px; }
.base-picker__scale-options { display: flex; flex-wrap: wrap; gap: 6px; }
.base-picker__scale-options button { min-width: 36px; min-height: 30px; padding: 3px 10px; border: 1px solid var(--am-border-strong); border-radius: 5px; background: var(--am-surface); color: var(--am-text); cursor: pointer; }
.base-picker__scale-options button[aria-pressed='true'] { border-color: var(--am-action-primary); background: var(--am-row-selected); color: var(--am-text); font-weight: 700; }
</style>
