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
  datasetVersions: Ref<DatasetVersionRelation[]>
  exports: Ref<DatasetExportSummary[]>
  t: (key: string) => string
}

export interface DatasetVersionSelectionItem extends DatasetVersionRelation {
  source_import_id: string
  source_format_type: string
  source_created_at: string
  source_status: string
}

export function buildDatasetVersionSelectionItems(
  datasetVersions: DatasetVersionRelation[],
  imports: DatasetImportSummary[],
): DatasetVersionSelectionItem[] {
  return datasetVersions.map((version) => {
    const sourceImportId = typeof version.metadata.source_import_id === 'string'
      ? version.metadata.source_import_id
      : ''
    const sourceImport = imports.find((item) => item.dataset_import_id === sourceImportId)
      ?? imports.find((item) => item.dataset_version_id === version.dataset_version_id)
    return {
      ...version,
      source_import_id: sourceImport?.dataset_import_id ?? sourceImportId,
      source_format_type: sourceImport?.format_type
        ?? (typeof version.metadata.format_type === 'string' ? version.metadata.format_type : ''),
      source_created_at: sourceImport?.created_at
        ?? (typeof version.metadata.created_at === 'string' ? version.metadata.created_at : ''),
      source_status: sourceImport?.processing_state || sourceImport?.status || '',
    }
  }).sort((left, right) => right.source_created_at.localeCompare(left.source_created_at))
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
      options.datasetVersions.value[0]?.dataset_version_id ||
      '',
  )

  const availableDatasetVersions = computed<DatasetVersionSelectionItem[]>(() => {
    return buildDatasetVersionSelectionItems(options.datasetVersions.value, options.imports.value)
  })

  const filteredDatasetVersions = computed(() => {
    const query = datasetVersionSearch.value.trim().toLowerCase()
    if (!query) return availableDatasetVersions.value
    return availableDatasetVersions.value.filter((item) =>
      [
        item.dataset_version_id ?? '',
        item.source_import_id,
        item.task_type,
        item.source_format_type,
        item.source_status,
      ]
        .join(' ')
        .toLowerCase()
        .includes(query),
    )
  })

  const selectedDatasetVersion = computed(
    () => availableDatasetVersions.value.find(
      (item) => item.dataset_version_id === resolvedDatasetVersionId.value,
    ) ?? null,
  )

  const resolvedDatasetId = computed(() => {
    const relation = datasetVersionRelation.value
    if (relation?.dataset_version_id === resolvedDatasetVersionId.value && relation.dataset_id.trim().length > 0) {
      return relation.dataset_id.trim()
    }
    const selectedDatasetId = selectedDatasetVersion.value?.dataset_id.trim()
    if (selectedDatasetId) {
      return selectedDatasetId
    }
    const exportDatasetId = options.exports.value.find((item) => item.dataset_version_id === resolvedDatasetVersionId.value)?.dataset_id.trim()
    if (exportDatasetId) {
      return exportDatasetId
    }
    return options.datasetId.value.trim()
  })

  const selectedDatasetVersionFormatLabel = computed(() => {
    const formatTypeValue = selectedDatasetVersion.value?.source_format_type ?? ''
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
    const matchedVersion = availableDatasetVersions.value.find((item) => item.dataset_version_id === normalizedDatasetVersionId)
    if (matchedVersion) {
      options.datasetId.value = matchedVersion.dataset_id
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
    [resolvedDatasetVersionId, () => selectedDatasetVersion.value?.dataset_id ?? options.datasetId.value.trim()],
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
    selectedDatasetVersion,
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
