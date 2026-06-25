<template>
  <form class="form-panel dataset-export-panel" @submit.prevent="$emit('submit')">
    <div>
      <p class="page-kicker">{{ t('datasetOps.exportKicker') }}</p>
      <h2>{{ t('datasetOps.exportTitle') }}</h2>
    </div>
    <div class="form-grid">
      <div class="field field--wide dataset-version-field">
        <div class="dataset-version-field__header">
          <span>{{ t('datasetOps.fields.datasetVersionId') }}</span>
          <Button
            size="sm"
            variant="secondary"
            type="button"
            :disabled="availableDatasetVersionCount === 0"
            @click="$emit('openDatasetVersionPicker')"
          >
            {{ resolvedDatasetVersionId ? t('datasetOps.actions.changeDatasetVersion') : t('datasetOps.actions.chooseDatasetVersion') }}
          </Button>
        </div>
        <div class="dataset-version-summary" :class="{ 'is-empty': !resolvedDatasetVersionId }">
          <template v-if="selectedDatasetVersionImport">
            <div class="dataset-version-summary__top">
              <div class="dataset-version-summary__identity">
                <strong>{{ selectedDatasetVersionImport.dataset_version_id }}</strong>
                <span>
                  {{ t('datasetOps.versionPicker.importIdLabel') }}
                  {{ selectedDatasetVersionImport.dataset_import_id }}
                </span>
              </div>
              <div class="dataset-version-summary__chips">
                <span class="dataset-version-chip">{{ resolvedDatasetVersionTaskType || t('common.noValue') }}</span>
                <span class="dataset-version-chip">{{ selectedDatasetVersionFormatLabel }}</span>
              </div>
            </div>
            <div class="dataset-version-summary__grid">
              <div class="dataset-version-summary__item">
                <span>{{ t('datasetOps.versionPicker.createdAtLabel') }}</span>
                <strong>{{ formatSystemDateTime(selectedDatasetVersionImport.created_at) }}</strong>
              </div>
              <div class="dataset-version-summary__item">
                <span>{{ t('datasetOps.versionPicker.sampleCountLabel') }}</span>
                <strong>{{ selectedDatasetVersionSampleCount }}</strong>
              </div>
              <div class="dataset-version-summary__item">
                <span>{{ t('datasetOps.versionPicker.categoryCountLabel') }}</span>
                <strong>{{ selectedDatasetVersionCategoryCount }}</strong>
              </div>
              <div class="dataset-version-summary__item">
                <span>{{ t('datasetOps.versionPicker.splitNamesLabel') }}</span>
                <strong>{{ selectedDatasetVersionSplitNames }}</strong>
              </div>
            </div>
          </template>
          <template v-else>
            <strong>{{ t('datasetOps.versionPicker.emptyTitle') }}</strong>
            <span>{{ t('datasetOps.versionPicker.emptyDescription') }}</span>
          </template>
        </div>
      </div>
      <label class="field">
        <span>{{ t('datasetOps.fields.exportFormat') }}</span>
        <SelectField :model-value="exportFormatId" :options="exportFormatSelectOptions" @update:model-value="$emit('update:exportFormatId', $event)" />
      </label>
      <label class="field">
        <span>{{ t('datasetOps.fields.exportTaskDisplayName') }}</span>
        <input :value="exportDisplayName" @input="$emit('update:exportDisplayName', ($event.target as HTMLInputElement).value)" />
      </label>
      <label class="field">
        <span>{{ t('datasetOps.fields.exportCategoryNamesOverride') }}</span>
        <input
          :value="exportCategoryNames"
          :placeholder="t('datasetOps.placeholders.exportCategoryNamesOverride')"
          @input="$emit('update:exportCategoryNames', ($event.target as HTMLInputElement).value)"
        />
      </label>
      <label class="checkbox-field field--wide">
        <input
          :checked="includeTestSplit"
          type="checkbox"
          @change="$emit('update:includeTestSplit', ($event.target as HTMLInputElement).checked)"
        />
        <span>{{ t('datasetOps.fields.includeTestSplit') }}</span>
      </label>
    </div>
    <div class="form-actions">
      <Button variant="primary" type="submit" :disabled="!canWriteDatasets || submittingExport || !resolvedDatasetVersionId || !exportFormatId">
        <PackageCheck :size="16" />
        {{ submittingExport ? t('datasetOps.actions.submitting') : t('datasetOps.actions.submitExport') }}
      </Button>
    </div>
    <p v-if="lastExportSubmission" class="result-note">
      {{ t('datasetOps.messages.exportSubmitted') }}
      <RouterLink :to="`/tasks/${lastExportSubmission.task_id}`">{{ lastExportSubmission.task_id }}</RouterLink>
    </p>
  </form>
</template>

<script setup lang="ts">
import { PackageCheck } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import type { DatasetExportSubmissionResponse, DatasetImportSummary } from '../services/dataset.service'
import type { DatasetSelectOption, DatasetSelectValue } from '../composables/useDatasetFormatCapabilities'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import SelectField from '@/shared/ui/components/Select.vue'

defineProps<{
  resolvedDatasetVersionId: string
  selectedDatasetVersionImport: DatasetImportSummary | null
  resolvedDatasetVersionTaskType: string
  selectedDatasetVersionFormatLabel: string
  selectedDatasetVersionSampleCount: string
  selectedDatasetVersionCategoryCount: string
  selectedDatasetVersionSplitNames: string
  availableDatasetVersionCount: number
  exportFormatId: string
  exportDisplayName: string
  exportCategoryNames: string
  includeTestSplit: boolean
  exportFormatSelectOptions: DatasetSelectOption[]
  canWriteDatasets: boolean
  submittingExport: boolean
  lastExportSubmission: DatasetExportSubmissionResponse | null
}>()

defineEmits<{
  submit: []
  openDatasetVersionPicker: []
  'update:exportFormatId': [value: DatasetSelectValue]
  'update:exportDisplayName': [value: string]
  'update:exportCategoryNames': [value: string]
  'update:includeTestSplit': [value: boolean]
}>()

const { t } = useI18n()
</script>

<style scoped>
.dataset-export-panel {
  align-content: start;
}

.dataset-version-field {
  gap: 10px;
}

.dataset-version-field__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.dataset-version-field__header > span {
  color: var(--muted);
  font-weight: 600;
}

.dataset-version-summary {
  display: grid;
  gap: 12px;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--summary-bg);
}

.dataset-version-summary.is-empty {
  min-height: 120px;
  align-content: center;
}

.dataset-version-summary.is-empty strong,
.dataset-version-summary.is-empty span {
  overflow-wrap: anywhere;
}

.dataset-version-summary.is-empty span {
  color: var(--muted);
}

.dataset-version-summary__top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.dataset-version-summary__identity {
  display: grid;
  gap: 4px;
  min-width: 0;
}

.dataset-version-summary__identity strong,
.dataset-version-summary__identity span {
  overflow-wrap: anywhere;
}

.dataset-version-summary__identity span {
  color: var(--muted);
  font-size: 12px;
}

.dataset-version-summary__chips {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.dataset-version-chip {
  display: inline-flex;
  align-items: center;
  min-height: 26px;
  padding: 0 10px;
  border-radius: 999px;
  color: var(--badge-neutral-text);
  background: var(--badge-neutral-bg);
  font-size: 12px;
  font-weight: 700;
}

.dataset-version-summary__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.dataset-version-summary__item {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--surface);
}

.dataset-version-summary__item span {
  color: var(--muted);
  font-size: 12px;
  font-weight: 600;
}

.dataset-version-summary__item strong {
  overflow-wrap: anywhere;
}

@media (max-width: 900px) {
  .dataset-version-summary__grid {
    grid-template-columns: 1fr;
  }
}
</style>
