import { ref, type Ref } from 'vue'

import {
  listProjectDatasetImports,
  listProjectDatasetVersions,
  submitDatasetImport,
  type DatasetImportSubmissionResponse,
  type DatasetImportSummary,
  type DatasetVersionRelation,
} from '../services/dataset.service'
import { selectValueToString, type DatasetSelectValue } from './useDatasetFormatCapabilities'

interface UseDatasetImportStateOptions {
  selectedProjectId: Ref<string>
  importDatasetId: Ref<string>
  datasetId: Ref<string>
  datasetVersionId: Ref<string>
  formatType: Ref<string>
  taskType: Ref<string>
  imports: Ref<DatasetImportSummary[]>
  datasetVersions: Ref<DatasetVersionRelation[]>
  errorMessage: Ref<string | null>
  createDatasetId: () => string
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
    if (!options.selectedProjectId.value.trim()) return

    const [nextImports, nextDatasetVersions] = await Promise.all([
      listProjectDatasetImports(options.selectedProjectId.value.trim()),
      listProjectDatasetVersions(options.selectedProjectId.value.trim()),
    ])
    options.imports.value = nextImports
    options.datasetVersions.value = nextDatasetVersions
    const currentDatasetVersionId = options.datasetVersionId.value.trim()
    const selectedVersion = nextDatasetVersions.find(
      (item) => item.dataset_version_id === currentDatasetVersionId,
    )
    if (selectedVersion) {
      options.datasetId.value = selectedVersion.dataset_id
      return
    }

    const latestImportedVersionId = nextImports.find((item) => item.dataset_version_id)?.dataset_version_id
    const latestDatasetVersion = nextDatasetVersions.find(
      (item) => item.dataset_version_id === latestImportedVersionId,
    ) ?? nextDatasetVersions[0]
    options.datasetVersionId.value = latestDatasetVersion?.dataset_version_id ?? ''
    if (latestDatasetVersion) {
      options.datasetId.value = latestDatasetVersion.dataset_id
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
        datasetId: options.importDatasetId.value.trim(),
        packageFile: importFile.value,
        formatType: options.formatType.value || undefined,
        taskType: options.taskType.value,
        splitStrategy: splitStrategy.value || undefined,
        classMapJson: classMapJson.value,
      })
      await refreshImportRecords()
      options.importDatasetId.value = options.createDatasetId()
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
