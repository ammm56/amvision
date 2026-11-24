<template>
  <ModelPickerDialogShell
    class="conversion-source-picker" :open="open" :loading="loading" compact
    :title="t('modelConversionSource.title')" :close-label="t('common.close')"
    :task-type-label="t('modelOps.fields.taskType')" :task-type-options="localizedTasks" :selected-task-type="selectedTaskType"
    :list-title="t('modelConversionSource.models')" :list-count="filteredModels.length"
    :detail-title="t('modelConversionSource.versions')"
    @close="$emit('close')" @change-task-type="$emit('change-task-type', $event)"
  >
    <template #list>
      <div class="model-picker__list">
        <label class="model-picker__search">
          <Search :size="16" aria-hidden="true" />
          <input v-model="search" type="search" :aria-label="t('modelConversionSource.search')" :placeholder="t('modelConversionSource.search')" />
        </label>
        <div v-if="loadError" class="model-picker__state" role="alert">
          <span>{{ loadError }}</span><Button size="sm" @click="$emit('retry')">{{ t('common.retry') }}</Button>
        </div>
        <p v-else-if="!filteredModels.length" class="model-picker__state" role="status">{{ t(loading
          ? 'common.updating' : models.length ? 'modelConversionSource.noResults' : 'modelConversionSource.empty') }}</p>
        <div v-else class="model-picker__families" role="group" :aria-label="t('modelConversionSource.models')">
          <button v-for="row in filteredModels" :key="row.model.model_id" type="button" class="model-picker__family-button"
            :aria-pressed="row.model.model_id === activeModel?.model.model_id" :disabled="loading"
            @click="$emit('select-model', row.model.model_id)">
            <Box :size="16" aria-hidden="true" />
            <strong>{{ modelDisplayName(row.model) }}</strong>
            <span v-if="row.model.scope_kind === 'platform-base' && row.model.model_scale" class="model-picker__scale">{{ row.model.model_scale }}</span>
            <small class="source-count">{{ t('modelConversionSource.usableCount', { count: row.usableCount }) }}</small>
            <ChevronRight :size="16" aria-hidden="true" class="model-picker__chevron" />
          </button>
        </div>
        <label class="source-availability"><input v-model="onlyUsable" type="checkbox" />{{ t('modelConversionSource.onlyUsable') }}</label>
      </div>
    </template>

    <template #detail>
      <div v-if="activeModel && !loading" class="model-picker__details">
        <div class="model-picker__identity">
          <Box :size="20" aria-hidden="true" />
          <strong>{{ modelDisplayName(activeModel.model) }}</strong>
          <span v-if="activeModel.model.model_scale" class="model-picker__scale">{{ activeModel.model.model_scale }}</span>
        </div>
        <div role="radiogroup" :aria-label="t('modelConversionSource.versions')" class="model-picker__versions">
          <label v-for="{ version, issue } in activeModel.versions" :key="version.model_version_id" class="model-picker__option"
            :class="{ 'is-selected': draftVersionId === version.model_version_id, 'is-disabled': issue }">
            <input v-model="draftVersionId" type="radio" :name="radioName" :value="version.model_version_id" :disabled="Boolean(issue)" />
            <span class="model-picker__option-copy">
              <span class="model-picker__option-name"><span class="model-picker__version-number">{{ modelVersionDisplayName(version, true) }}</span></span>
              <small>{{ versionSource(version.source_kind) }}<template v-if="Array.isArray(version.metadata.category_names)"> · {{ t('modelConversionSource.categoryCount', { count: version.metadata.category_names.length }) }}</template></small>
              <small v-if="issue" class="source-issue">{{ t(`modelConversionSource.${issue}`) }}</small>
            </span>
            <span class="model-picker__status" :class="issue ? 'is-missing' : 'is-present'">{{ t(issue ? 'modelConversionSource.unavailable' : 'modelConversionSource.usable') }}</span>
          </label>
        </div>
      </div>
      <p v-else class="model-picker__state">{{ t('modelConversionSource.pickModel') }}</p>
    </template>

    <template #footer>
      <Button @click="$emit('close')">{{ t('common.cancel') }}</Button>
      <Button variant="primary" :disabled="!draftVersion || loading" @click="applyVersion">{{ t('modelConversionSource.confirm') }}</Button>
    </template>
  </ModelPickerDialogShell>
</template>

<script setup lang="ts">
import { Box, ChevronRight, Search } from '@lucide/vue'
import { computed, ref, useId, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import Button from '@/shared/ui/components/Button.vue'
import ModelPickerDialogShell from '@/shared/ui/components/ModelPickerDialogShell.vue'
import { conversionSourceIssue } from '../conversion-source-support'
import { latestModelVersion, modelDisplayName, modelVersionDisplayName } from '../model-display-name'
import { evaluationTypes } from '../model-evaluation-types'
import type { DeploymentSourceModelSummary, ModelTaskType } from '../services/model.service'

const props = defineProps<{
  open: boolean
  loading: boolean
  loadError: string
  selectedTaskType: ModelTaskType
  taskTypeOptions: Array<{ label: string; value: ModelTaskType }>
  models: DeploymentSourceModelSummary[]
  selectedModel: DeploymentSourceModelSummary | null
  selectedVersionId: string
}>()
const emit = defineEmits<{
  close: []
  retry: []
  'change-task-type': [taskType: string]
  'select-model': [modelId: string]
  'select-version': [versionId: string, modelId: string]
}>()
const { t, locale } = useI18n()
const search = ref('')
const onlyUsable = ref(false)
const draftVersionId = ref('')
const radioName = useId()
const localizedTasks = computed(() => props.taskTypeOptions.map(({ value }) => ({
  value, label: evaluationTypes[value][locale.value.startsWith('zh') ? 0 : 1],
})))
const modelRows = computed(() => props.models.map(model => {
  const versions = model.available_versions.map(version => ({ version, issue: conversionSourceIssue(version) }))
  return { model, versions, usableCount: versions.filter(item => item.issue === null).length }
}))
const filteredModels = computed(() => {
  const words = search.value.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean)
  return modelRows.value.filter(({ model, usableCount }) => {
    if (onlyUsable.value && usableCount === 0) return false
    const text = [modelDisplayName(model), model.model_name, model.model_id, model.model_type, model.model_scale].join(' ').toLocaleLowerCase()
    return words.every(word => text.includes(word))
  })
})
const activeModel = computed(() => filteredModels.value.find(row => row.model.model_id === props.selectedModel?.model_id)
  ?? filteredModels.value[0])
const draftVersion = computed(() => activeModel.value?.versions
  .find(({ version, issue }) => !issue && version.model_version_id === draftVersionId.value)?.version)

watch(() => props.selectedTaskType, () => { search.value = '' })
watch(() => props.open, () => { search.value = ''; onlyUsable.value = false })
watch([activeModel, () => props.open], ([row, open]) => {
  if (!open) { draftVersionId.value = ''; return }
  if (draftVersion.value) return
  const usable = row?.versions.filter(item => item.issue === null).map(item => item.version) ?? []
  draftVersionId.value = usable.find(version => version.model_version_id === props.selectedVersionId)?.model_version_id
    ?? latestModelVersion(usable)?.model_version_id ?? usable[0]?.model_version_id ?? ''
}, { immediate: true })

function versionSource(kind: string): string {
  const keys: Record<string, string> = {
    'training-output': 'sourceTraining', 'pretrained-reference': 'sourcePretrained',
    'deployment-import': 'sourceDeployment', 'model-package-import': 'sourcePackage',
  }
  return t(`modelConversionSource.${keys[kind] ?? 'sourceUnknown'}`)
}

function applyVersion(): void {
  if (!props.loading && draftVersion.value && activeModel.value) {
    emit('select-version', draftVersion.value.model_version_id, activeModel.value.model.model_id)
  }
}
</script>

<style scoped src="./model-picker-fields.css"></style>
<style scoped>
.source-count { margin-inline-start: auto; flex: none; color: var(--am-text-muted); font-size: 12px; }
.source-count + .model-picker__chevron { margin-inline-start: 0; }
.source-availability { display: flex; align-items: center; flex-shrink: 0; gap: 8px; padding: 10px 12px; border: 1px solid var(--am-border); border-radius: 6px; color: var(--am-text-muted); font-size: 13px; }
.source-availability input { margin: 0; accent-color: var(--am-action-primary); }
.model-picker__option-copy .source-issue { color: var(--am-danger-text); }
@media (max-width: 600px) { .source-count { white-space: normal; text-align: end; } }
</style>
