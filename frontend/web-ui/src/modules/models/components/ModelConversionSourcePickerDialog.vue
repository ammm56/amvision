<template>
  <ModelPickerDialogShell
    :open="open" :loading="loading" compact
    :title="t('modelConversionSource.title')" :close-label="t('common.close')"
    :task-type-options="taskTypeOptions" :selected-task-type="selectedTaskType"
    :list-title="t('modelConversionSource.models')" :list-count="models.length"
    :detail-title="t('modelConversionSource.versions')"
    @close="$emit('close')" @change-task-type="$emit('change-task-type', $event)"
  >
    <template #list>
      <div class="conversion-source-list">
        <input v-model="search" type="search" :aria-label="t('modelConversionSource.search')" :placeholder="t('modelConversionSource.search')" />
        <EmptyState v-if="filteredModels.length === 0" :title="t(models.length > 0 ? 'modelConversionSource.noResults' : 'modelConversionSource.empty')" />
        <div v-else role="listbox" :aria-label="t('modelConversionSource.models')" class="conversion-source-list__items">
          <button
            v-for="model in filteredModels" :key="model.model_id" type="button" role="option"
            :aria-selected="model.model_id === selectedModel?.model_id" :disabled="loading"
            class="conversion-source-model" :class="{ 'is-selected': model.model_id === selectedModel?.model_id }"
            @click="$emit('select-model', model.model_id)"
          >
            <strong>{{ model.model_name }}</strong>
            <span>{{ model.model_type }} · {{ model.task_type }} · {{ model.model_scale }}</span>
            <span>{{ model.model_id }}</span>
          </button>
        </div>
      </div>
    </template>
    <template #detail>
      <div v-if="selectedModel" class="conversion-source-versions">
        <h3>{{ selectedModel.model_name }}</h3>
        <div v-for="version in selectedModel.available_versions" :key="version.model_version_id" class="conversion-source-version" :aria-current="version.model_version_id === selectedVersionId ? 'true' : undefined">
          <strong>{{ version.model_version_id }}</strong>
          <span>{{ version.source_kind }}</span>
          <span v-if="Array.isArray(version.metadata.category_names)">{{ t('modelConversionSource.categoryCount', { count: version.metadata.category_names.length }) }}</span>
          <span v-if="conversionSourceIssue(version)" role="status">{{ t(`modelConversionSource.${conversionSourceIssue(version)}`) }}</span>
          <Button
            size="sm" variant="secondary" :disabled="loading || conversionSourceIssue(version) !== null"
            @click="$emit('select-version', version.model_version_id)"
          >
            {{ t('modelOps.picker.selectConversionVersion') }}
          </Button>
        </div>
      </div>
      <EmptyState v-else :title="t('modelConversionSource.empty')" />
    </template>
  </ModelPickerDialogShell>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import type { DeploymentSourceModelSummary, ModelTaskType } from '../services/model.service'
import { conversionSourceIssue } from '../conversion-source-support'
import Button from '@/shared/ui/components/Button.vue'
import ModelPickerDialogShell from '@/shared/ui/components/ModelPickerDialogShell.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'

const props = defineProps<{
  open: boolean
  loading: boolean
  selectedTaskType: ModelTaskType
  taskTypeOptions: Array<{ label: string; value: string }>
  models: DeploymentSourceModelSummary[]
  selectedModel: DeploymentSourceModelSummary | null
  selectedVersionId: string
}>()
defineEmits<{
  close: []
  'change-task-type': [taskType: string]
  'select-model': [modelId: string]
  'select-version': [modelVersionId: string]
}>()
const { t } = useI18n()
const search = ref('')
const filteredModels = computed(() => {
  const query = search.value.trim().toLowerCase()
  return props.models.filter((model) => [model.model_name, model.model_id, model.model_type, model.model_scale].some((value) => value.toLowerCase().includes(query)))
})
watch(() => [props.open, props.selectedTaskType], () => { search.value = '' })
</script>

<style scoped>
.conversion-source-list { display: grid; grid-template-rows: auto minmax(0, 1fr); min-height: 0; gap: 10px; }
.conversion-source-list > input { width: 100%; min-width: 0; height: 36px; padding: 8px 10px; border: 1px solid var(--am-border); border-radius: 6px; color: var(--am-text); background: var(--am-surface); font-size: 13px; }
.conversion-source-list__items, .conversion-source-versions { overflow: auto; min-height: 0; }
.conversion-source-model { display: grid; width: 100%; gap: 4px; padding: 12px; border: 0; border-bottom: 1px solid var(--am-border); color: var(--am-text); background: transparent; text-align: left; cursor: pointer; }
.conversion-source-model:hover, .conversion-source-model.is-selected { background: var(--am-row-selected); }
.conversion-source-model span, .conversion-source-version span { color: var(--am-text-muted); font-size: 12px; }
.conversion-source-model strong, .conversion-source-model span, .conversion-source-version strong, h3 { overflow-wrap: anywhere; }
h3 { margin: 0 0 12px; font-size: 15px; }
.conversion-source-version { display: grid; gap: 8px; padding: 12px 0; border-top: 1px solid var(--am-border); }
.conversion-source-version button { justify-self: start; }
@media (max-width: 960px) { .conversion-source-list__items, .conversion-source-versions { overflow: visible; } }
</style>
