import { ref, type Ref } from 'vue'

import {
  listDatasetImports,
  submitDatasetImport,
  type DatasetImportSubmissionResponse,
  type DatasetImportSummary,
} from '../services/dataset.service'
import { selectValueToString, type DatasetSelectValue } from './useDatasetFormatCapabilities'

interface UseDatasetImportStateOptions {
  selectedProjectId: Ref<string>
  datasetId: Ref<string>
  datasetVersionId: Ref<string>
  formatType: Ref<string>
  taskType: Ref<string>
  imports: Ref<DatasetImportSummary[]>
  errorMessage: Ref<string | null>
  t: (key: string) => string
}

export function useDatasetImportState(options: UseDatasetImportStateOptions) {
  const importFile = ref<File | null>(null)
  const splitStrategy = ref('auto')
  const classMapJson = ref('')
  const submittingImport = ref(false)
  const lastImportSubmission = ref<DatasetImportSubmissionResponse | null>(null)

  function setSplitStrategy(value: DatasetSelectValue): void {
    splitStrategy.value = selectValueToString(value) || 'auto'
  }

  async function refreshImportRecords(): Promise<void> {
    if (!options.datasetId.value.trim()) return

    const nextImports = await listDatasetImports(options.datasetId.value.trim())
    options.imports.value = nextImports
    const currentDatasetVersionId = options.datasetVersionId.value.trim()
    if (!currentDatasetVersionId || !nextImports.some((item) => item.dataset_version_id === currentDatasetVersionId)) {
      options.datasetVersionId.value = nextImports.find((item) => item.dataset_version_id)?.dataset_version_id ?? ''
    }
  }

  async function submitImportForm(): Promise<void> {
    if (!importFile.value) {
      options.errorMessage.value = options.t('datasetOps.messages.selectPackage')
      return
    }

    submittingImport.value = true
    options.errorMessage.value = null
    try {
      lastImportSubmission.value = await submitDatasetImport({
        projectId: options.selectedProjectId.value,
        datasetId: options.datasetId.value.trim(),
        packageFile: importFile.value,
        formatType: options.formatType.value || undefined,
        taskType: options.taskType.value,
        splitStrategy: splitStrategy.value || undefined,
        classMapJson: classMapJson.value,
      })
      await refreshImportRecords()
    } catch (error) {
      options.errorMessage.value = error instanceof Error ? error.message : options.t('datasetOps.messages.submitImportFailed')
    } finally {
      submittingImport.value = false
    }
  }

  return {
    importFile,
    splitStrategy,
    classMapJson,
    imports: options.imports,
    submittingImport,
    lastImportSubmission,
    setSplitStrategy,
    refreshImportRecords,
    submitImportForm,
  }
}
