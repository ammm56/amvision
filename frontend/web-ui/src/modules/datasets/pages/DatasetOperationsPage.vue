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

    <div class="operation-grid">
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

      <form class="form-panel" @submit.prevent="submitExportForm">
        <div>
          <p class="page-kicker">{{ t('datasetOps.exportKicker') }}</p>
          <h2>{{ t('datasetOps.exportTitle') }}</h2>
        </div>
        <div class="form-grid">
          <label class="field">
            <span>{{ t('datasetOps.fields.datasetVersionId') }}</span>
            <input v-model="datasetVersionId" placeholder="dataset-version-id" required />
          </label>
          <label class="field">
            <span>{{ t('datasetOps.fields.exportFormat') }}</span>
            <SelectField :model-value="exportFormatId" :options="exportFormatSelectOptions" @update:model-value="setExportFormatId" />
          </label>
          <label class="field field--wide">
            <span>{{ t('datasetOps.fields.displayName') }}</span>
            <input v-model="exportDisplayName" />
          </label>
          <label class="field field--wide">
            <span>{{ t('datasetOps.fields.categoryNames') }}</span>
            <input v-model="exportCategoryNames" placeholder="person, defect" />
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
import { computed, onMounted, ref } from 'vue'
import { Download, PackageCheck, RefreshCw, UploadCloud } from '@lucide/vue'
import { RouterLink } from 'vue-router'
import { useI18n } from 'vue-i18n'

import {
  createDatasetExport,
  downloadDatasetExport,
  getDatasetExportFormats,
  listDatasetExports,
  listDatasetImports,
  packageDatasetExport,
  submitDatasetImport,
  type DatasetExportFormatCatalog,
  type DatasetExportSubmissionResponse,
  type DatasetExportSummary,
  type DatasetImportSubmissionResponse,
  type DatasetImportSummary,
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

const taskTypeOptions = [
  { label: 'detection', value: 'detection' },
  { label: 'segmentation', value: 'segmentation' },
  { label: 'semantic-segmentation', value: 'semantic-segmentation' },
  { label: 'pose', value: 'pose' },
]

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
const loading = ref(false)
const submittingImport = ref(false)
const submittingExport = ref(false)
const packagingExportId = ref<string | null>(null)
const errorMessage = ref<string | null>(null)
const lastImportSubmission = ref<DatasetImportSubmissionResponse | null>(null)
const lastExportSubmission = ref<DatasetExportSubmissionResponse | null>(null)

const canWriteDatasets = computed(() => sessionStore.hasScopes(['datasets:write']))
const selectedProjectId = computed(() => projectStore.selectedProjectId)
const resolvedDatasetVersionId = computed(() => datasetVersionId.value.trim() || imports.value.find((item) => item.dataset_version_id)?.dataset_version_id || '')
const categoryNameList = computed(() => exportCategoryNames.value.split(',').map((item) => item.trim()).filter(Boolean))
const exportFormatOptions = computed(() => {
  const catalog = exportFormats.value
  if (!catalog) return []
  return catalog.implemented_formats.length > 0 ? catalog.implemented_formats : catalog.items.map((item) => item.format_id)
})
const formatTypeOptions = computed(() => [
  { label: t('datasetOps.fields.autoDetect'), value: '' },
  { label: 'COCO', value: 'coco' },
  { label: 'VOC', value: 'voc' },
])
const exportFormatSelectOptions = computed(() => exportFormatOptions.value.map((item) => ({ label: item, value: item })))

function selectValueToString(value: SelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

function setFormatType(value: SelectValue): void {
  formatType.value = selectValueToString(value)
}

function setTaskType(value: SelectValue): void {
  taskType.value = selectValueToString(value) || 'detection'
}

function setSplitStrategy(value: SelectValue): void {
  splitStrategy.value = selectValueToString(value) || 'auto'
}

function setExportFormatId(value: SelectValue): void {
  exportFormatId.value = selectValueToString(value)
}

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
    exportFormatId.value ||= catalog.default_format
    await refreshRecords()
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
  if (!datasetVersionId.value.trim()) {
    datasetVersionId.value = nextImports.find((item) => item.dataset_version_id)?.dataset_version_id ?? ''
  }
  const versionId = resolvedDatasetVersionId.value
  if (versionId) {
    exports.value = await listDatasetExports(datasetId.value.trim(), versionId)
  } else {
    exports.value = []
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
</script>
