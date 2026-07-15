<template>
  <section class="page-stack">
    <header class="page-header">
      <div>
        <p class="page-kicker">{{ t('datasetOps.kicker') }}</p>
        <h1>{{ t('datasetOps.title') }}</h1>
        <p class="page-description">{{ t('datasetOps.description') }}</p>
      </div>
      <div class="page-actions">
        <Button variant="secondary" :disabled="loading" @click="refreshPage">
          <RefreshCw :size="16" />
          {{ t('common.refresh') }}
        </Button>
      </div>
    </header>

    <InlineError :message="errorMessage" />

    <div class="operation-grid dataset-ops-grid">
      <DatasetImportForm
        :selected-project-id="selectedProjectId"
        :dataset-id="importDatasetId"
        :format-type="formatType"
        :task-type="taskType"
        :split-strategy="splitStrategy"
        :class-map-json="classMapJson"
        :import-file="importFile"
        :format-type-options="formatTypeOptions"
        :task-type-options="taskTypeOptions"
        :split-strategy-options="splitStrategyOptions"
        :can-write-datasets="canWriteDatasets"
        :submitting-import="submittingImport"
        :last-import-submission="lastImportSubmission"
        @update:dataset-id="importDatasetId = $event"
        @update:format-type="setFormatType"
        @update:task-type="setTaskType"
        @update:split-strategy="setSplitStrategy"
        @update:class-map-json="classMapJson = $event"
        @update:import-file="importFile = $event"
        @submit="submitImportForm"
      />

      <DatasetExportForm
        :resolved-dataset-version-id="resolvedDatasetVersionId"
        :selected-dataset-version-import="selectedDatasetVersionImport"
        :resolved-dataset-version-task-type="resolvedDatasetVersionTaskType"
        :selected-dataset-version-format-label="selectedDatasetVersionFormatLabel"
        :selected-dataset-version-sample-count="selectedDatasetVersionSampleCount"
        :selected-dataset-version-category-count="selectedDatasetVersionCategoryCount"
        :selected-dataset-version-split-names="selectedDatasetVersionSplitNames"
        :available-dataset-version-count="availableDatasetVersions.length"
        :export-format-id="exportFormatId"
        :export-display-name="exportDisplayName"
        :export-category-names="exportCategoryNames"
        :include-test-split="includeTestSplit"
        :export-format-select-options="exportFormatSelectOptions"
        :can-write-datasets="canWriteDatasets"
        :submitting-export="submittingExport"
        :last-export-submission="lastExportSubmission"
        @open-dataset-version-picker="openDatasetVersionPicker"
        @update:export-format-id="setExportFormatId"
        @update:export-display-name="exportDisplayName = $event"
        @update:export-category-names="exportCategoryNames = $event"
        @update:include-test-split="includeTestSplit = $event"
        @submit="submitExportForm"
      />
    </div>

    <DatasetVersionPickerDialog
      v-if="datasetVersionPickerOpen"
      :search="datasetVersionSearch"
      :filtered-dataset-versions="filteredDatasetVersions"
      :resolved-dataset-version-id="resolvedDatasetVersionId"
      :status-tone="statusTone"
      @update:search="datasetVersionSearch = $event"
      @select="selectDatasetVersion"
      @close="closeDatasetVersionPicker"
    />

    <DatasetImportRecords
      :imports="imports"
      :loading="loading"
      :status-tone="statusTone"
    />

    <DatasetExportRecords
      :exports="exports"
      :loading="loading"
      :can-write-datasets="canWriteDatasets"
      :packaging-export-id="packagingExportId"
      :status-tone="statusTone"
      @package="packageExport"
      @download="downloadExport"
    />
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RefreshCw } from '@lucide/vue'
import { useI18n } from 'vue-i18n'

import DatasetExportForm from '../components/DatasetExportForm.vue'
import DatasetExportRecords from '../components/DatasetExportRecords.vue'
import DatasetImportForm from '../components/DatasetImportForm.vue'
import DatasetImportRecords from '../components/DatasetImportRecords.vue'
import DatasetVersionPickerDialog from '../components/DatasetVersionPickerDialog.vue'
import { useDatasetExportState } from '../composables/useDatasetExportState'
import { useDatasetFormatCapabilities, type DatasetSelectOption } from '../composables/useDatasetFormatCapabilities'
import { useDatasetImportState } from '../composables/useDatasetImportState'
import { useDatasetVersionSelection } from '../composables/useDatasetVersionSelection'
import type { DatasetExportSummary, DatasetImportSummary } from '../services/dataset.service'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import Button from '@/shared/ui/components/Button.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

const splitStrategyOptions: DatasetSelectOption[] = [
  { label: 'auto', value: 'auto' },
  { label: 'train', value: 'train' },
  { label: 'val', value: 'val' },
  { label: 'test', value: 'test' },
]

const importDatasetId = ref(createDefaultDatasetId())
const datasetId = ref('')
const datasetVersionId = ref('')
const imports = ref<DatasetImportSummary[]>([])
const exports = ref<DatasetExportSummary[]>([])
const loading = ref(false)
const errorMessage = ref<string | null>(null)

const canWriteDatasets = computed(() => sessionStore.hasScopes(['datasets:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)

const {
  datasetVersionPickerOpen,
  datasetVersionSearch,
  resolvedDatasetVersionId,
  resolvedDatasetId,
  availableDatasetVersions,
  filteredDatasetVersions,
  selectedDatasetVersionImport,
  selectedDatasetVersionFormatLabel,
  selectedDatasetVersionSampleCount,
  selectedDatasetVersionCategoryCount,
  selectedDatasetVersionSplitNames,
  resolvedDatasetVersionTaskType,
  openDatasetVersionPicker,
  closeDatasetVersionPicker,
  selectDatasetVersion,
} = useDatasetVersionSelection({
  datasetId,
  datasetVersionId,
  imports,
  exports,
  t,
})

const {
  formatType,
  taskType,
  exportFormatId,
  taskTypeOptions,
  formatTypeOptions,
  exportFormatSelectOptions,
  setFormatType,
  setTaskType,
  setExportFormatId,
  loadExportFormatCatalog,
} = useDatasetFormatCapabilities({
  resolvedDatasetVersionId,
  resolvedDatasetVersionTaskType,
  t,
})

const {
  importFile,
  splitStrategy,
  classMapJson,
  submittingImport,
  lastImportSubmission,
  setSplitStrategy,
  refreshImportRecords,
  submitImportForm,
} = useDatasetImportState({
  selectedProjectId,
  importDatasetId,
  datasetId,
  datasetVersionId,
  formatType,
  taskType,
  imports,
  errorMessage,
  createDatasetId: createDefaultDatasetId,
  t,
})

const {
  exportDisplayName,
  exportCategoryNames,
  includeTestSplit,
  submittingExport,
  packagingExportId,
  lastExportSubmission,
  loadCurrentDatasetExports,
  submitExportForm,
  packageExport,
  downloadExport,
} = useDatasetExportState({
  selectedProjectId,
  datasetId,
  datasetVersionId,
  resolvedDatasetVersionId,
  resolvedDatasetId,
  exportFormatId,
  exports,
  errorMessage,
  t,
})

onMounted(async () => {
  if (projectStore.projects.length === 0) {
    await projectStore.loadProjects()
  }
  await loadInitialData()
})

function statusTone(status: string | null | undefined): 'neutral' | 'success' | 'warning' | 'danger' | 'info' {
  const normalized = String(status ?? '').toLowerCase()
  if (normalized.includes('complete') || normalized.includes('success') || normalized.includes('ready')) return 'success'
  if (normalized.includes('fail') || normalized.includes('error')) return 'danger'
  if (normalized.includes('queue') || normalized.includes('received')) return 'warning'
  if (normalized.includes('run') || normalized.includes('process') || normalized.includes('valid')) return 'info'
  return 'neutral'
}

function createDefaultDatasetId(): string {
  const now = new Date()
  const pad = (value: number): string => String(value).padStart(2, '0')
  const timestamp = [
    now.getFullYear(),
    pad(now.getMonth() + 1),
    pad(now.getDate()),
    pad(now.getHours()),
    pad(now.getMinutes()),
    pad(now.getSeconds()),
  ].join('')
  return `dataset-${timestamp}`
}

async function loadInitialData(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    await loadExportFormatCatalog()
    await refreshImportRecords()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function refreshPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    await refreshImportRecords()
    await loadCurrentDatasetExports()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.dataset-ops-grid {
  align-items: start;
}
</style>
