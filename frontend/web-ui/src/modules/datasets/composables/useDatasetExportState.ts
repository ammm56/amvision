import { computed, ref, watch, type Ref } from 'vue'

import {
  createDatasetExport,
  downloadDatasetExport,
  listDatasetExports,
  packageDatasetExport,
  type DatasetExportSubmissionResponse,
  type DatasetExportSummary,
} from '../services/dataset.service'

interface UseDatasetExportStateOptions {
  selectedProjectId: Ref<string>
  datasetId: Ref<string>
  datasetVersionId: Ref<string>
  resolvedDatasetVersionId: Ref<string>
  resolvedDatasetId: Ref<string>
  exportFormatId: Ref<string>
  exports: Ref<DatasetExportSummary[]>
  errorMessage: Ref<string | null>
  t: (key: string) => string
}

export function useDatasetExportState(options: UseDatasetExportStateOptions) {
  const exportDisplayName = ref('')
  const exportCategoryNames = ref('')
  const includeTestSplit = ref(true)
  const submittingExport = ref(false)
  const packagingExportId = ref<string | null>(null)
  const lastExportSubmission = ref<DatasetExportSubmissionResponse | null>(null)
  let datasetExportsRequestId = 0

  const categoryNameList = computed(() => exportCategoryNames.value.split(',').map((item) => item.trim()).filter(Boolean))

  async function loadDatasetExports(nextDatasetId: string, nextDatasetVersionId: string): Promise<void> {
    const requestId = ++datasetExportsRequestId
    if (!nextDatasetId || !nextDatasetVersionId) {
      options.exports.value = []
      return
    }

    try {
      const nextExports = await listDatasetExports(nextDatasetId, nextDatasetVersionId)
      if (requestId !== datasetExportsRequestId) {
        return
      }
      options.exports.value = nextExports
    } catch {
      if (requestId !== datasetExportsRequestId) {
        return
      }
      options.exports.value = []
    }
  }

  async function loadCurrentDatasetExports(): Promise<void> {
    await loadDatasetExports(options.resolvedDatasetId.value, options.resolvedDatasetVersionId.value)
  }

  async function submitExportForm(): Promise<void> {
    if (!options.resolvedDatasetVersionId.value) {
      options.errorMessage.value = options.t('datasetOps.messages.selectDatasetVersion')
      return
    }

    submittingExport.value = true
    options.errorMessage.value = null
    try {
      const submission = await createDatasetExport({
        projectId: options.selectedProjectId.value,
        datasetId: options.resolvedDatasetId.value,
        datasetVersionId: options.resolvedDatasetVersionId.value,
        formatId: options.exportFormatId.value,
        displayName: exportDisplayName.value,
        categoryNames: categoryNameList.value,
        includeTestSplit: includeTestSplit.value,
      })
      lastExportSubmission.value = submission
      options.datasetVersionId.value = submission.dataset_version_id
      await loadCurrentDatasetExports()
    } catch (error) {
      options.errorMessage.value = error instanceof Error ? error.message : options.t('datasetOps.messages.submitExportFailed')
    } finally {
      submittingExport.value = false
    }
  }

  async function packageExport(datasetExportId: string): Promise<void> {
    packagingExportId.value = datasetExportId
    options.errorMessage.value = null
    try {
      await packageDatasetExport(datasetExportId)
      await loadCurrentDatasetExports()
    } catch (error) {
      options.errorMessage.value = error instanceof Error ? error.message : options.t('datasetOps.messages.packageFailed')
    } finally {
      packagingExportId.value = null
    }
  }

  async function downloadExport(datasetExport: DatasetExportSummary): Promise<void> {
    options.errorMessage.value = null
    try {
      const blob = await downloadDatasetExport(datasetExport.dataset_export_id)
      const objectUrl = window.URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = objectUrl
      anchor.download = datasetExport.package_file_name || `${datasetExport.dataset_export_id}.zip`
      anchor.click()
      window.URL.revokeObjectURL(objectUrl)
    } catch (error) {
      options.errorMessage.value = error instanceof Error ? error.message : options.t('datasetOps.messages.downloadFailed')
    }
  }

  watch(
    [options.resolvedDatasetVersionId, options.resolvedDatasetId],
    ([nextDatasetVersionId, nextDatasetId]) => {
      void loadDatasetExports(nextDatasetId, nextDatasetVersionId)
    },
    { immediate: true },
  )

  return {
    exports: options.exports,
    exportDisplayName,
    exportCategoryNames,
    includeTestSplit,
    submittingExport,
    packagingExportId,
    lastExportSubmission,
    categoryNameList,
    loadDatasetExports,
    loadCurrentDatasetExports,
    submitExportForm,
    packageExport,
    downloadExport,
  }
}
