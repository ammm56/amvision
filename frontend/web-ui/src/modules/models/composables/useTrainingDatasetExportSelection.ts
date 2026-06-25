import { computed, ref, type Ref } from 'vue'

import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'

export function useTrainingDatasetExportSelection(trainingDatasetExports: Ref<DatasetExportSummary[]>) {
  const trainingDatasetExportPickerOpen = ref(false)
  const trainingDatasetExportSearch = ref('')
  const trainingDatasetExportBrowseId = ref('')
  const trainingDatasetExportId = ref('')

  const selectedTrainingDatasetExport = computed(
    () => trainingDatasetExports.value.find((item) => item.dataset_export_id === trainingDatasetExportId.value) ?? null,
  )

  function openTrainingDatasetExportPicker(): void {
    if (trainingDatasetExports.value.length === 0) {
      return
    }
    trainingDatasetExportPickerOpen.value = true
    trainingDatasetExportSearch.value = ''
    trainingDatasetExportBrowseId.value =
      trainingDatasetExportId.value || trainingDatasetExports.value[0]?.dataset_export_id || ''
  }

  function closeTrainingDatasetExportPicker(): void {
    trainingDatasetExportPickerOpen.value = false
    trainingDatasetExportSearch.value = ''
  }

  function selectTrainingDatasetExportBrowse(datasetExportId: string): void {
    trainingDatasetExportBrowseId.value = datasetExportId.trim()
  }

  function applyTrainingDatasetExport(datasetExport: DatasetExportSummary): void {
    trainingDatasetExportId.value = datasetExport.dataset_export_id
    trainingDatasetExportBrowseId.value = datasetExport.dataset_export_id
    closeTrainingDatasetExportPicker()
  }

  function resetTrainingDatasetExportSelection(): void {
    trainingDatasetExportPickerOpen.value = false
    trainingDatasetExportSearch.value = ''
    trainingDatasetExportBrowseId.value = ''
    trainingDatasetExportId.value = ''
  }

  function ensureTrainingDatasetExportSelectionVisible(): void {
    if (!trainingDatasetExports.value.some((item) => item.dataset_export_id === trainingDatasetExportId.value)) {
      trainingDatasetExportId.value = ''
    }
    if (!trainingDatasetExports.value.some((item) => item.dataset_export_id === trainingDatasetExportBrowseId.value)) {
      trainingDatasetExportBrowseId.value = trainingDatasetExports.value[0]?.dataset_export_id ?? ''
    }
  }

  return {
    trainingDatasetExportPickerOpen,
    trainingDatasetExportSearch,
    trainingDatasetExportBrowseId,
    trainingDatasetExportId,
    selectedTrainingDatasetExport,
    openTrainingDatasetExportPicker,
    closeTrainingDatasetExportPicker,
    selectTrainingDatasetExportBrowse,
    applyTrainingDatasetExport,
    resetTrainingDatasetExportSelection,
    ensureTrainingDatasetExportSelectionVisible,
  }
}
