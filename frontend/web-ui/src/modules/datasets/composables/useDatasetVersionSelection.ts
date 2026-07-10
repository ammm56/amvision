import { computed, nextTick, ref, watch, type Ref } from 'vue'

import {
  getDatasetVersionRelation,
  type DatasetExportSummary,
  type DatasetImportSummary,
  type DatasetVersionRelation,
} from '../services/dataset.service'
import { resolveImportFormatDisplayName } from './useDatasetFormatCapabilities'

interface UseDatasetVersionSelectionOptions {
  datasetId: Ref<string>
  datasetVersionId: Ref<string>
  imports: Ref<DatasetImportSummary[]>
  exports: Ref<DatasetExportSummary[]>
  t: (key: string) => string
}

export function useDatasetVersionSelection(options: UseDatasetVersionSelectionOptions) {
  const datasetVersionRelation = ref<DatasetVersionRelation | null>(null)
  const datasetVersionPickerOpen = ref(false)
  const datasetVersionSearch = ref('')
  const datasetVersionSearchInput = ref<HTMLInputElement | null>(null)
  let datasetVersionRelationRequestId = 0

  const resolvedDatasetVersionId = computed(
    () =>
      options.datasetVersionId.value.trim() ||
      options.imports.value.find((item) => item.dataset_version_id)?.dataset_version_id ||
      '',
  )

  const availableDatasetVersions = computed(() => {
    const byVersionId = new Map<string, DatasetImportSummary>()
    for (const item of [...options.imports.value].sort((left, right) => right.created_at.localeCompare(left.created_at))) {
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

  const resolvedDatasetId = computed(() => {
    const relation = datasetVersionRelation.value
    if (relation?.dataset_version_id === resolvedDatasetVersionId.value && relation.dataset_id.trim().length > 0) {
      return relation.dataset_id.trim()
    }
    const importDatasetId = selectedDatasetVersionImport.value?.dataset_id?.trim()
    if (importDatasetId) {
      return importDatasetId
    }
    const exportDatasetId = options.exports.value.find((item) => item.dataset_version_id === resolvedDatasetVersionId.value)?.dataset_id.trim()
    if (exportDatasetId) {
      return exportDatasetId
    }
    return options.datasetId.value.trim()
  })

  const selectedDatasetVersionFormatLabel = computed(() => {
    const formatTypeValue = selectedDatasetVersionImport.value?.format_type ?? ''
    return formatTypeValue ? resolveImportFormatDisplayName(formatTypeValue) : options.t('common.noValue')
  })

  const selectedDatasetVersionSampleCount = computed(() => formatNumericSummary(datasetVersionRelation.value?.sample_count))
  const selectedDatasetVersionCategoryCount = computed(() => formatNumericSummary(datasetVersionRelation.value?.category_count))
  const selectedDatasetVersionSplitNames = computed(() => {
    const splitNames = datasetVersionRelation.value?.split_names.filter((item) => item.trim().length > 0) ?? []
    return splitNames.length > 0 ? splitNames.join(', ') : options.t('common.noValue')
  })

  const resolvedDatasetVersionTaskType = computed(() => {
    const relationTaskType = datasetVersionRelation.value?.task_type
    if (typeof relationTaskType === 'string' && relationTaskType.trim().length > 0) {
      return relationTaskType.trim().toLowerCase()
    }
    const matchedImportTaskType = options.imports.value.find((item) => item.dataset_version_id === resolvedDatasetVersionId.value)?.task_type
    if (typeof matchedImportTaskType === 'string' && matchedImportTaskType.trim().length > 0) {
      return matchedImportTaskType.trim().toLowerCase()
    }
    const matchedExportTaskType = options.exports.value.find((item) => item.dataset_version_id === resolvedDatasetVersionId.value)?.task_type
    if (typeof matchedExportTaskType === 'string' && matchedExportTaskType.trim().length > 0) {
      return matchedExportTaskType.trim().toLowerCase()
    }
    return ''
  })

  function formatNumericSummary(value: number | null | undefined): string {
    return typeof value === 'number' ? String(value) : options.t('common.noValue')
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
    const matchedImport = availableDatasetVersions.value.find((item) => item.dataset_version_id === normalizedDatasetVersionId)
    if (matchedImport) {
      options.datasetId.value = matchedImport.dataset_id
    }
    options.datasetVersionId.value = normalizedDatasetVersionId
    closeDatasetVersionPicker()
  }

  async function loadDatasetVersionRelation(nextDatasetId: string, nextDatasetVersionId: string): Promise<void> {
    const requestId = ++datasetVersionRelationRequestId
    if (!nextDatasetId || !nextDatasetVersionId) {
      datasetVersionRelation.value = null
      return
    }

    try {
      const relation = await getDatasetVersionRelation(nextDatasetId, nextDatasetVersionId)
      if (requestId !== datasetVersionRelationRequestId) {
        return
      }
      datasetVersionRelation.value = relation
      if (relation.dataset_id.trim().length > 0) {
        options.datasetId.value = relation.dataset_id.trim()
      }
    } catch {
      if (requestId !== datasetVersionRelationRequestId) {
        return
      }
      datasetVersionRelation.value = null
    }
  }

  watch(
    [resolvedDatasetVersionId, () => selectedDatasetVersionImport.value?.dataset_id ?? options.datasetId.value.trim()],
    ([nextDatasetVersionId, nextDatasetId]) => {
      const normalizedDatasetId = typeof nextDatasetId === 'string' ? nextDatasetId.trim() : ''
      void loadDatasetVersionRelation(normalizedDatasetId, nextDatasetVersionId)
    },
    { immediate: true },
  )

  return {
    datasetVersionRelation,
    datasetVersionPickerOpen,
    datasetVersionSearch,
    datasetVersionSearchInput,
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
    loadDatasetVersionRelation,
  }
}
