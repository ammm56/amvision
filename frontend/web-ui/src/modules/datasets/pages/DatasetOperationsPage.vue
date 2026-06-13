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
      <form class="form-panel" @submit.prevent="submitImportForm">
        <div>
          <p class="page-kicker">{{ t('datasetOps.importKicker') }}</p>
          <h2>{{ t('datasetOps.importTitle') }}</h2>
        </div>
        <div class="form-grid">
          <label class="field">
            <span>{{ t('datasetOps.fields.projectId') }}</span>
            <input :value="selectedProjectId" disabled />
          </label>
          <label class="field">
            <span>{{ t('datasetOps.fields.datasetId') }}</span>
            <input v-model="datasetId" required />
          </label>
          <label class="field">
            <span>{{ t('datasetOps.fields.formatType') }}</span>
            <SelectField :model-value="formatType" :options="formatTypeOptions" @update:model-value="setFormatType" />
          </label>
          <label class="field">
            <span>{{ t('datasetOps.fields.taskType') }}</span>
            <SelectField :model-value="taskType" :options="taskTypeOptions" @update:model-value="setTaskType" />
          </label>
          <label class="field">
            <span>{{ t('datasetOps.fields.splitStrategy') }}</span>
            <SelectField :model-value="splitStrategy" :options="splitStrategyOptions" @update:model-value="setSplitStrategy" />
          </label>
          <FilePicker
            v-model="importFile"
            class="field--wide"
            icon="archive"
            accept=".zip,application/zip"
            :label="t('datasetOps.fields.package')"
            :description="t('datasetOps.filePickerDescription')"
            :disabled="submittingImport"
          />
          <label class="field field--wide">
            <span>{{ t('datasetOps.fields.classMap') }}</span>
            <textarea v-model="classMapJson" rows="3" placeholder='{"old": "new"}' />
          </label>
        </div>
        <div class="form-actions">
          <Button variant="primary" type="submit" :disabled="!canWriteDatasets || submittingImport">
            <UploadCloud :size="16" />
            {{ submittingImport ? t('datasetOps.actions.submitting') : t('datasetOps.actions.submitImport') }}
          </Button>
        </div>
        <p v-if="lastImportSubmission" class="result-note">
          {{ t('datasetOps.messages.importSubmitted') }}
          <RouterLink v-if="lastImportSubmission.task_id" :to="`/tasks/${lastImportSubmission.task_id}`">
            {{ lastImportSubmission.task_id }}
          </RouterLink>
          <span v-else>{{ lastImportSubmission.dataset_import_id }}</span>
        </p>
      </form>

      <form class="form-panel dataset-export-panel" @submit.prevent="submitExportForm">
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
                :disabled="availableDatasetVersions.length === 0"
                @click="openDatasetVersionPicker"
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
            <SelectField :model-value="exportFormatId" :options="exportFormatSelectOptions" @update:model-value="setExportFormatId" />
          </label>
          <label class="field">
            <span>{{ t('datasetOps.fields.exportTaskDisplayName') }}</span>
            <input v-model="exportDisplayName" />
          </label>
          <label class="field">
            <span>{{ t('datasetOps.fields.exportCategoryNamesOverride') }}</span>
            <input v-model="exportCategoryNames" :placeholder="t('datasetOps.placeholders.exportCategoryNamesOverride')" />
          </label>
          <label class="checkbox-field field--wide">
            <input v-model="includeTestSplit" type="checkbox" />
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
    </div>

    <div v-if="datasetVersionPickerOpen" class="dataset-version-picker-backdrop" @click="closeDatasetVersionPicker">
      <div
        class="dataset-version-picker"
        role="dialog"
        aria-modal="true"
        :aria-label="t('datasetOps.versionPicker.title')"
        @click.stop
        @keydown.esc.prevent="closeDatasetVersionPicker"
      >
        <header class="dataset-version-picker__header">
          <div>
            <p class="page-kicker">{{ t('datasetOps.exportKicker') }}</p>
            <h2>{{ t('datasetOps.versionPicker.title') }}</h2>
            <p class="dataset-version-picker__description">{{ t('datasetOps.versionPicker.description') }}</p>
          </div>
          <button
            type="button"
            class="dataset-version-picker__close"
            :title="t('datasetOps.versionPicker.close')"
            :aria-label="t('datasetOps.versionPicker.close')"
            @click="closeDatasetVersionPicker"
          >
            <X :size="16" />
          </button>
        </header>

        <label class="dataset-version-picker__search">
          <Search :size="16" />
          <input
            ref="datasetVersionSearchInput"
            v-model="datasetVersionSearch"
            :placeholder="t('datasetOps.versionPicker.searchPlaceholder')"
          />
        </label>

        <div v-if="filteredDatasetVersions.length === 0" class="dataset-version-picker__empty">
          <strong>{{ t('datasetOps.versionPicker.noResultsTitle') }}</strong>
          <span>{{ t('datasetOps.versionPicker.noResultsDescription') }}</span>
        </div>

        <div v-else class="dataset-version-picker__list">
          <button
            v-for="item in filteredDatasetVersions"
            :key="item.dataset_version_id ?? item.dataset_import_id"
            type="button"
            class="dataset-version-picker__item"
            :class="{ 'is-selected': item.dataset_version_id === resolvedDatasetVersionId }"
            @click="selectDatasetVersion(item.dataset_version_id ?? '')"
          >
            <div class="dataset-version-picker__item-main">
              <div class="dataset-version-picker__item-title">
                <strong>{{ item.dataset_version_id }}</strong>
                <div class="dataset-version-picker__item-chips">
                  <span class="dataset-version-chip">{{ item.task_type }}</span>
                  <span class="dataset-version-chip">{{ resolveImportFormatDisplayName(item.format_type || '') || t('common.noValue') }}</span>
                </div>
              </div>
              <div class="dataset-version-picker__item-meta">
                <span>{{ t('datasetOps.versionPicker.importIdLabel') }} {{ item.dataset_import_id }}</span>
                <span>{{ t('datasetOps.versionPicker.createdAtLabel') }} {{ formatSystemDateTime(item.created_at) }}</span>
              </div>
            </div>
            <div class="dataset-version-picker__item-side">
              <StatusBadge :tone="statusTone(item.processing_state || item.status)">{{ item.processing_state || item.status }}</StatusBadge>
              <Check v-if="item.dataset_version_id === resolvedDatasetVersionId" :size="18" />
            </div>
          </button>
        </div>
      </div>
    </div>

    <section class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">{{ t('datasetOps.importHistoryKicker') }}</p>
          <h2>{{ t('datasetOps.importHistoryTitle') }}</h2>
        </div>
      </div>
      <EmptyState v-if="!loading && imports.length === 0" :title="t('datasetOps.emptyImportsTitle')" :description="t('datasetOps.emptyImportsDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('datasetOps.columns.importId') }}</th>
              <th>{{ t('datasetOps.columns.status') }}</th>
              <th>{{ t('datasetOps.columns.version') }}</th>
              <th>{{ t('datasetOps.columns.format') }}</th>
              <th>{{ t('datasetOps.columns.createdAt') }}</th>
              <th>{{ t('datasetOps.columns.task') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in imports" :key="item.dataset_import_id">
              <td>
                <RouterLink :to="`/datasets/imports/${item.dataset_import_id}`"><strong>{{ item.dataset_import_id }}</strong></RouterLink>
                <span>{{ item.package_path }}</span>
              </td>
              <td><StatusBadge :tone="statusTone(item.processing_state || item.status)">{{ item.processing_state || item.status }}</StatusBadge></td>
              <td>{{ item.dataset_version_id || '-' }}</td>
              <td>{{ item.format_type || '-' }}</td>
              <td>{{ formatSystemDateTime(item.created_at) }}</td>
              <td>
                <RouterLink v-if="item.task_id" :to="`/tasks/${item.task_id}`">{{ item.task_id }}</RouterLink>
                <span v-else>-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="resource-section">
      <div class="section-heading">
        <div>
          <p class="page-kicker">{{ t('datasetOps.exportHistoryKicker') }}</p>
          <h2>{{ t('datasetOps.exportHistoryTitle') }}</h2>
        </div>
      </div>
      <EmptyState v-if="!loading && exports.length === 0" :title="t('datasetOps.emptyExportsTitle')" :description="t('datasetOps.emptyExportsDescription')" />
      <div v-else class="resource-table">
        <table>
          <thead>
            <tr>
              <th>{{ t('datasetOps.columns.exportId') }}</th>
              <th>{{ t('datasetOps.columns.status') }}</th>
              <th>{{ t('datasetOps.columns.format') }}</th>
              <th>{{ t('datasetOps.columns.samples') }}</th>
              <th>{{ t('datasetOps.columns.package') }}</th>
              <th>{{ t('datasetOps.columns.actions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="item in exports" :key="item.dataset_export_id">
              <td>
                <strong>{{ item.dataset_export_id }}</strong>
                <span>{{ item.dataset_version_id }}</span>
              </td>
              <td><StatusBadge :tone="statusTone(item.status)">{{ item.status }}</StatusBadge></td>
              <td>{{ item.format_id }}</td>
              <td>{{ item.sample_count }}</td>
              <td>{{ item.package_file_name || item.package_object_key || '-' }}</td>
              <td>
                <div class="table-actions">
                  <Button size="sm" variant="secondary" :disabled="!canWriteDatasets || packagingExportId === item.dataset_export_id" @click="packageExport(item.dataset_export_id)">
                    <PackageCheck :size="14" />
                    {{ t('datasetOps.actions.package') }}
                  </Button>
                  <Button size="sm" variant="ghost" :disabled="!item.package_object_key" @click="downloadExport(item)">
                    <Download :size="14" />
                    {{ t('datasetOps.actions.download') }}
                  </Button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Check, Download, PackageCheck, RefreshCw, Search, UploadCloud, X } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  createDatasetExport,
  downloadDatasetExport,
  getDatasetExportFormats,
  getDatasetVersionRelation,
  listDatasetExports,
  listDatasetImports,
  packageDatasetExport,
  submitDatasetImport,
  type DatasetExportFormatCatalog,
  type DatasetExportSubmissionResponse,
  type DatasetExportSummary,
  type DatasetImportSubmissionResponse,
  type DatasetImportSummary,
  type DatasetVersionRelation,
} from '../services/dataset.service'
import { useProjectStore } from '@/app/stores/project.store'
import { useSessionStore } from '@/app/stores/session.store'
import { formatSystemDateTime } from '@/shared/formatters/date-time'
import Button from '@/shared/ui/components/Button.vue'
import FilePicker from '@/shared/ui/components/FilePicker.vue'
import SelectField from '@/shared/ui/components/Select.vue'
import EmptyState from '@/shared/ui/feedback/EmptyState.vue'
import InlineError from '@/shared/ui/feedback/InlineError.vue'
import StatusBadge from '@/shared/ui/data-display/StatusBadge.vue'

const projectStore = useProjectStore()
const sessionStore = useSessionStore()
const { t } = useI18n()

type SelectValue = string | number | boolean | null

const splitStrategyOptions = [
  { label: 'auto', value: 'auto' },
  { label: 'train', value: 'train' },
  { label: 'val', value: 'val' },
  { label: 'test', value: 'test' },
]

const datasetId = ref('dataset-1')
const datasetVersionId = ref('')
const importFile = ref<File | null>(null)
const formatType = ref('')
const taskType = ref('detection')
const splitStrategy = ref('auto')
const classMapJson = ref('')
const exportFormatId = ref('')
const exportDisplayName = ref('')
const exportCategoryNames = ref('')
const includeTestSplit = ref(true)
const imports = ref<DatasetImportSummary[]>([])
const exports = ref<DatasetExportSummary[]>([])
const exportFormats = ref<DatasetExportFormatCatalog | null>(null)
const datasetVersionRelation = ref<DatasetVersionRelation | null>(null)
const datasetVersionPickerOpen = ref(false)
const datasetVersionSearch = ref('')
const datasetVersionSearchInput = ref<HTMLInputElement | null>(null)
const loading = ref(false)
const submittingImport = ref(false)
const submittingExport = ref(false)
const packagingExportId = ref<string | null>(null)
const errorMessage = ref<string | null>(null)
const lastImportSubmission = ref<DatasetImportSubmissionResponse | null>(null)
const lastExportSubmission = ref<DatasetExportSubmissionResponse | null>(null)
let datasetVersionRelationRequestId = 0
let datasetExportsRequestId = 0

const canWriteDatasets = computed(() => sessionStore.hasScopes(['datasets:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)
const resolvedDatasetVersionId = computed(() => datasetVersionId.value.trim() || imports.value.find((item) => item.dataset_version_id)?.dataset_version_id || '')
const categoryNameList = computed(() => exportCategoryNames.value.split(',').map((item) => item.trim()).filter(Boolean))
const availableDatasetVersions = computed(() => {
  const byVersionId = new Map<string, DatasetImportSummary>()
  for (const item of [...imports.value].sort((left, right) => right.created_at.localeCompare(left.created_at))) {
    const versionId = item.dataset_version_id?.trim()
    if (!versionId || byVersionId.has(versionId)) continue
    byVersionId.set(versionId, item)
  }
  return [...byVersionId.values()]
})
const filteredDatasetVersions = computed(() => {
  const query = datasetVersionSearch.value.trim().toLowerCase()
  if (!query) return availableDatasetVersions.value
  return availableDatasetVersions.value.filter((item) =>
    [
      item.dataset_version_id ?? '',
      item.dataset_import_id,
      item.task_type,
      item.format_type ?? '',
      item.processing_state,
      item.status,
    ]
      .join(' ')
      .toLowerCase()
      .includes(query),
  )
})
const selectedDatasetVersionImport = computed(
  () => availableDatasetVersions.value.find((item) => item.dataset_version_id === resolvedDatasetVersionId.value) ?? null,
)
const selectedDatasetVersionFormatLabel = computed(() => {
  const formatTypeValue = selectedDatasetVersionImport.value?.format_type ?? ''
  return formatTypeValue ? resolveImportFormatDisplayName(formatTypeValue) : t('common.noValue')
})
const selectedDatasetVersionSampleCount = computed(() => formatNumericSummary(datasetVersionRelation.value?.sample_count))
const selectedDatasetVersionCategoryCount = computed(() => formatNumericSummary(datasetVersionRelation.value?.category_count))
const selectedDatasetVersionSplitNames = computed(() => {
  const splitNames = datasetVersionRelation.value?.split_names.filter((item) => item.trim().length > 0) ?? []
  return splitNames.length > 0 ? splitNames.join(', ') : t('common.noValue')
})
const exportFormatOptions = computed(() => {
  const catalog = exportFormats.value
  if (!catalog) return []
  if (!resolvedDatasetVersionId.value || !resolvedDatasetVersionTaskType.value) {
    return []
  }
  return resolveSupportedExportFormatTypes(resolvedDatasetVersionTaskType.value)
})
const supportedImportTaskTypes = computed<string[]>(() => {
  const rawValue = sessionStore.bootstrap?.capabilities.dataset_import?.implemented_task_types
  if (!Array.isArray(rawValue)) {
    return []
  }
  return rawValue
    .filter((taskType): taskType is string => typeof taskType === 'string' && taskType.trim().length > 0)
    .map((taskType) => taskType.trim().toLowerCase())
})
const supportedImportFormatTypesByTaskType = computed<Record<string, string[]>>(() => {
  const rawValue = sessionStore.bootstrap?.capabilities.dataset_import?.format_types_by_task_type
  if (!rawValue || typeof rawValue !== 'object') {
    return {}
  }
  const normalizedEntries = Object.entries(rawValue).map(([taskType, formatTypes]) => [
    taskType.trim().toLowerCase(),
    Array.isArray(formatTypes)
      ? formatTypes
          .filter((formatType): formatType is string => typeof formatType === 'string' && formatType.trim().length > 0)
          .map((formatType) => formatType.trim().toLowerCase())
      : [],
  ])
  return Object.fromEntries(normalizedEntries)
})
const supportedExportFormatTypesByTaskType = computed<Record<string, string[]>>(() => {
  const rawValue = exportFormats.value?.format_types_by_task_type
  if (!rawValue || typeof rawValue !== 'object') {
    return {}
  }
  const normalizedEntries = Object.entries(rawValue).map(([taskType, formatTypes]) => [
    taskType.trim().toLowerCase(),
    Array.isArray(formatTypes)
      ? formatTypes
          .filter((formatType): formatType is string => typeof formatType === 'string' && formatType.trim().length > 0)
          .map((formatType) => formatType.trim())
      : [],
  ])
  return Object.fromEntries(normalizedEntries)
})
const resolvedDatasetVersionTaskType = computed(() => {
  const relationTaskType = datasetVersionRelation.value?.task_type
  if (typeof relationTaskType === 'string' && relationTaskType.trim().length > 0) {
    return relationTaskType.trim().toLowerCase()
  }
  const matchedImportTaskType = imports.value.find((item) => item.dataset_version_id === resolvedDatasetVersionId.value)?.task_type
  if (typeof matchedImportTaskType === 'string' && matchedImportTaskType.trim().length > 0) {
    return matchedImportTaskType.trim().toLowerCase()
  }
  const matchedExportTaskType = exports.value.find((item) => item.dataset_version_id === resolvedDatasetVersionId.value)?.task_type
  if (typeof matchedExportTaskType === 'string' && matchedExportTaskType.trim().length > 0) {
    return matchedExportTaskType.trim().toLowerCase()
  }
  return ''
})
const taskTypeOptions = computed(() => supportedImportTaskTypes.value.map((taskType) => ({ label: taskType, value: taskType })))
const formatTypeOptions = computed(() => [
  { label: t('datasetOps.fields.autoDetect'), value: '' },
  ...resolveSupportedImportFormatTypes(taskType.value).map((formatType) => ({
    label: resolveImportFormatDisplayName(formatType),
    value: formatType,
  })),
])
const exportFormatSelectOptions = computed(() => exportFormatOptions.value.map((item) => ({ label: item, value: item })))

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function setFormatType(value: SelectValue): void {
  formatType.value = selectValueToString(value)
}

function setTaskType(value: SelectValue): void {
  taskType.value = selectValueToString(value) || taskType.value
  syncImportSelectionFromCapabilities()
}

function setSplitStrategy(value: SelectValue): void {
  splitStrategy.value = selectValueToString(value) || 'auto'
}

function setExportFormatId(value: SelectValue): void {
  exportFormatId.value = selectValueToString(value)
}

watch(
  [supportedImportTaskTypes, supportedImportFormatTypesByTaskType],
  () => {
    syncImportSelectionFromCapabilities()
  },
  { immediate: true, deep: true },
)

watch(
  [resolvedDatasetVersionId, () => datasetId.value.trim()],
  ([nextDatasetVersionId, nextDatasetId]) => {
    void loadDatasetVersionRelation(nextDatasetId, nextDatasetVersionId)
    void loadDatasetExports(nextDatasetId, nextDatasetVersionId)
  },
  { immediate: true },
)

watch(
  [exportFormats, resolvedDatasetVersionTaskType, resolvedDatasetVersionId],
  () => {
    syncExportSelectionFromCapabilities()
  },
  { immediate: true, deep: true },
)

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

async function loadInitialData(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    const catalog = await getDatasetExportFormats()
    exportFormats.value = catalog
    syncImportSelectionFromCapabilities()
    await refreshRecords()
    syncExportSelectionFromCapabilities()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function refreshRecords(): Promise<void> {
  if (!datasetId.value.trim()) return
  const nextImports = await listDatasetImports(datasetId.value.trim())
  imports.value = nextImports
  const currentDatasetVersionId = datasetVersionId.value.trim()
  if (!currentDatasetVersionId || !nextImports.some((item) => item.dataset_version_id === currentDatasetVersionId)) {
    datasetVersionId.value = nextImports.find((item) => item.dataset_version_id)?.dataset_version_id ?? ''
  }
}

async function refreshPage(): Promise<void> {
  loading.value = true
  errorMessage.value = null
  try {
    await refreshRecords()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetOps.messages.loadFailed')
  } finally {
    loading.value = false
  }
}

async function submitImportForm(): Promise<void> {
  if (!importFile.value) {
    errorMessage.value = t('datasetOps.messages.selectPackage')
    return
  }
  submittingImport.value = true
  errorMessage.value = null
  try {
    lastImportSubmission.value = await submitDatasetImport({
      projectId: selectedProjectId.value,
      datasetId: datasetId.value.trim(),
      packageFile: importFile.value,
      formatType: formatType.value || undefined,
      taskType: taskType.value,
      splitStrategy: splitStrategy.value || undefined,
      classMapJson: classMapJson.value,
    })
    await refreshRecords()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetOps.messages.submitImportFailed')
  } finally {
    submittingImport.value = false
  }
}

async function submitExportForm(): Promise<void> {
  if (!resolvedDatasetVersionId.value) {
    errorMessage.value = t('datasetOps.messages.selectDatasetVersion')
    return
  }
  submittingExport.value = true
  errorMessage.value = null
  try {
    const submission = await createDatasetExport({
      projectId: selectedProjectId.value,
      datasetId: datasetId.value.trim(),
      datasetVersionId: resolvedDatasetVersionId.value,
      formatId: exportFormatId.value,
      displayName: exportDisplayName.value,
      categoryNames: categoryNameList.value,
      includeTestSplit: includeTestSplit.value,
    })
    lastExportSubmission.value = submission
    datasetVersionId.value = submission.dataset_version_id
    await refreshRecords()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetOps.messages.submitExportFailed')
  } finally {
    submittingExport.value = false
  }
}

async function packageExport(datasetExportId: string): Promise<void> {
  packagingExportId.value = datasetExportId
  errorMessage.value = null
  try {
    await packageDatasetExport(datasetExportId)
    await refreshRecords()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetOps.messages.packageFailed')
  } finally {
    packagingExportId.value = null
  }
}

async function downloadExport(datasetExport: DatasetExportSummary): Promise<void> {
  errorMessage.value = null
  try {
    const blob = await downloadDatasetExport(datasetExport.dataset_export_id)
    const objectUrl = window.URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = objectUrl
    anchor.download = datasetExport.package_file_name || `${datasetExport.dataset_export_id}.zip`
    anchor.click()
    window.URL.revokeObjectURL(objectUrl)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : t('datasetOps.messages.downloadFailed')
  }
}

function syncImportSelectionFromCapabilities(): void {
  const nextSupportedTaskTypes = supportedImportTaskTypes.value
  if (nextSupportedTaskTypes.length > 0 && !nextSupportedTaskTypes.includes(taskType.value)) {
    taskType.value = nextSupportedTaskTypes[0]
  }
  const nextSupportedFormatTypes = resolveSupportedImportFormatTypes(taskType.value)
  if (formatType.value && !nextSupportedFormatTypes.includes(formatType.value)) {
    formatType.value = ''
  }
}

function syncExportSelectionFromCapabilities(): void {
  const nextSupportedFormatTypes = exportFormatOptions.value
  if (nextSupportedFormatTypes.length === 0) {
    exportFormatId.value = ''
    return
  }
  if (!exportFormatId.value || !nextSupportedFormatTypes.includes(exportFormatId.value)) {
    exportFormatId.value = nextSupportedFormatTypes[0]
  }
}

function resolveSupportedImportFormatTypes(taskTypeValue: string): string[] {
  return supportedImportFormatTypesByTaskType.value[taskTypeValue.trim().toLowerCase()] ?? []
}

function resolveSupportedExportFormatTypes(taskTypeValue: string): string[] {
  return supportedExportFormatTypesByTaskType.value[taskTypeValue.trim().toLowerCase()] ?? []
}

function resolveImportFormatDisplayName(formatTypeValue: string): string {
  const normalizedFormatType = formatTypeValue.trim().toLowerCase()
  if (normalizedFormatType === 'coco') return 'COCO'
  if (normalizedFormatType === 'voc') return 'VOC'
  if (normalizedFormatType === 'yolo') return 'YOLO'
  if (normalizedFormatType === 'imagenet') return 'ImageNet'
  if (normalizedFormatType === 'dota') return 'DOTA'
  return formatTypeValue
}

function formatNumericSummary(value: number | null | undefined): string {
  return typeof value === 'number' ? String(value) : t('common.noValue')
}

function openDatasetVersionPicker(): void {
  if (availableDatasetVersions.value.length === 0) return
  datasetVersionPickerOpen.value = true
  datasetVersionSearch.value = ''
  void nextTick(() => datasetVersionSearchInput.value?.focus())
}

function closeDatasetVersionPicker(): void {
  datasetVersionPickerOpen.value = false
  datasetVersionSearch.value = ''
}

function selectDatasetVersion(nextDatasetVersionId: string): void {
  const normalizedDatasetVersionId = nextDatasetVersionId.trim()
  if (!normalizedDatasetVersionId) return
  datasetVersionId.value = normalizedDatasetVersionId
  closeDatasetVersionPicker()
}

async function loadDatasetVersionRelation(nextDatasetId: string, nextDatasetVersionId: string): Promise<void> {
  const requestId = ++datasetVersionRelationRequestId
  if (!nextDatasetId || !nextDatasetVersionId) {
    datasetVersionRelation.value = null
    syncExportSelectionFromCapabilities()
    return
  }

  try {
    const relation = await getDatasetVersionRelation(nextDatasetId, nextDatasetVersionId)
    if (requestId !== datasetVersionRelationRequestId) {
      return
    }
    datasetVersionRelation.value = relation
  } catch {
    if (requestId !== datasetVersionRelationRequestId) {
      return
    }
    datasetVersionRelation.value = null
  } finally {
    if (requestId === datasetVersionRelationRequestId) {
      syncExportSelectionFromCapabilities()
    }
  }
}

async function loadDatasetExports(nextDatasetId: string, nextDatasetVersionId: string): Promise<void> {
  const requestId = ++datasetExportsRequestId
  if (!nextDatasetId || !nextDatasetVersionId) {
    exports.value = []
    return
  }

  try {
    const nextExports = await listDatasetExports(nextDatasetId, nextDatasetVersionId)
    if (requestId !== datasetExportsRequestId) {
      return
    }
    exports.value = nextExports
  } catch {
    if (requestId !== datasetExportsRequestId) {
      return
    }
    exports.value = []
  }
}
</script>

<style scoped>
.dataset-ops-grid {
  align-items: start;
}

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

.dataset-version-summary__chips,
.dataset-version-picker__item-chips {
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

.dataset-version-picker-backdrop {
  position: fixed;
  inset: 0;
  z-index: 80;
  display: grid;
  place-items: center;
  padding: 18px;
  background: rgb(16 20 24 / 0.38);
}

.dataset-version-picker {
  display: grid;
  grid-template-rows: auto auto minmax(0, 1fr);
  gap: 12px;
  width: min(860px, calc(100vw - 36px));
  max-height: min(640px, calc(100vh - 36px));
  padding: 16px;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: var(--surface);
  box-shadow: 0 24px 48px rgb(0 0 0 / 0.18);
}

.dataset-version-picker__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.dataset-version-picker__header h2,
.dataset-version-picker__header p {
  margin: 0;
}

.dataset-version-picker__description {
  margin-top: 8px !important;
  color: var(--muted);
}

.dataset-version-picker__close {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  color: var(--text);
  background: var(--button-secondary-bg);
  cursor: pointer;
}

.dataset-version-picker__search {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 0 12px;
  border: 1px solid var(--line-strong);
  border-radius: 8px;
  color: var(--muted);
  background: var(--input-bg);
}

.dataset-version-picker__search:focus-within {
  border-color: var(--accent);
}

.dataset-version-picker__search input {
  width: 100%;
  min-width: 0;
  border: 0;
  outline: 0;
  color: var(--input-text);
  background: transparent;
}

.dataset-version-picker__empty {
  display: grid;
  gap: 6px;
  place-items: center;
  min-height: 180px;
  padding: 24px;
  border: 1px dashed var(--line-strong);
  border-radius: 8px;
  color: var(--muted);
  text-align: center;
}

.dataset-version-picker__list {
  display: grid;
  align-content: start;
  gap: 10px;
  min-height: 0;
  overflow: auto;
  padding-right: 4px;
}

.dataset-version-picker__item {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
  width: 100%;
  padding: 14px;
  border: 1px solid var(--line);
  border-radius: 8px;
  color: var(--text);
  background: var(--summary-bg);
  text-align: left;
  cursor: pointer;
}

.dataset-version-picker__item:hover,
.dataset-version-picker__item.is-selected {
  border-color: var(--accent);
  background: var(--selected-row-bg);
}

.dataset-version-picker__item-main {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.dataset-version-picker__item-title {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.dataset-version-picker__item-title strong,
.dataset-version-picker__item-meta span {
  overflow-wrap: anywhere;
}

.dataset-version-picker__item-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  color: var(--muted);
  font-size: 12px;
}

.dataset-version-picker__item-side {
  display: grid;
  justify-items: end;
  gap: 10px;
  flex-shrink: 0;
}

@media (max-width: 900px) {
  .dataset-version-summary__grid {
    grid-template-columns: 1fr;
  }

  .dataset-version-picker {
    width: min(100%, calc(100vw - 24px));
    max-height: min(100%, calc(100vh - 24px));
  }

  .dataset-version-picker__item,
  .dataset-version-picker__item-title {
    flex-direction: column;
  }

  .dataset-version-picker__item-side {
    justify-items: start;
  }
}
</style>
