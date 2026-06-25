import { computed, ref, watch, type Ref } from 'vue'

import {
  getDatasetExportFormats,
  type DatasetExportFormatCatalog,
} from '../services/dataset.service'
import { useSessionStore } from '@/app/stores/session.store'

export type DatasetSelectValue = string | number | boolean | null

export interface DatasetSelectOption {
  label: string
  value: string
}

interface UseDatasetFormatCapabilitiesOptions {
  resolvedDatasetVersionId: Ref<string>
  resolvedDatasetVersionTaskType: Ref<string>
  t: (key: string) => string
}

export function selectValueToString(value: DatasetSelectValue): string {
  return typeof value === 'string' ? value : String(value ?? '')
}

export function resolveImportFormatDisplayName(formatTypeValue: string): string {
  const normalizedFormatType = formatTypeValue.trim().toLowerCase()
  if (normalizedFormatType === 'coco') return 'COCO'
  if (normalizedFormatType === 'voc') return 'VOC'
  if (normalizedFormatType === 'yolo') return 'YOLO'
  if (normalizedFormatType === 'imagenet') return 'ImageNet'
  if (normalizedFormatType === 'dota') return 'DOTA'
  return formatTypeValue
}

function normalizeFormatTypesByTaskType(rawValue: unknown, preserveCase = false): Record<string, string[]> {
  if (!rawValue || typeof rawValue !== 'object') {
    return {}
  }

  const normalizedEntries = Object.entries(rawValue).map(([taskType, formatTypes]) => [
    taskType.trim().toLowerCase(),
    Array.isArray(formatTypes)
      ? formatTypes
          .filter((formatType): formatType is string => typeof formatType === 'string' && formatType.trim().length > 0)
          .map((formatType) => (preserveCase ? formatType.trim() : formatType.trim().toLowerCase()))
      : [],
  ])
  return Object.fromEntries(normalizedEntries)
}

export function useDatasetFormatCapabilities(options: UseDatasetFormatCapabilitiesOptions) {
  const sessionStore = useSessionStore()
  const exportFormats = ref<DatasetExportFormatCatalog | null>(null)
  const formatType = ref('')
  const taskType = ref('detection')
  const exportFormatId = ref('')

  const supportedImportTaskTypes = computed<string[]>(() => {
    const rawValue = sessionStore.bootstrap?.capabilities.dataset_import?.implemented_task_types
    if (!Array.isArray(rawValue)) {
      return []
    }
    return rawValue
      .filter((item): item is string => typeof item === 'string' && item.trim().length > 0)
      .map((item) => item.trim().toLowerCase())
  })

  const supportedImportFormatTypesByTaskType = computed<Record<string, string[]>>(() =>
    normalizeFormatTypesByTaskType(sessionStore.bootstrap?.capabilities.dataset_import?.format_types_by_task_type),
  )

  const supportedExportFormatTypesByTaskType = computed<Record<string, string[]>>(() =>
    normalizeFormatTypesByTaskType(exportFormats.value?.format_types_by_task_type, true),
  )

  const exportFormatOptions = computed(() => {
    if (!exportFormats.value || !options.resolvedDatasetVersionId.value || !options.resolvedDatasetVersionTaskType.value) {
      return []
    }
    return resolveSupportedExportFormatTypes(options.resolvedDatasetVersionTaskType.value)
  })

  const taskTypeOptions = computed<DatasetSelectOption[]>(() =>
    supportedImportTaskTypes.value.map((item) => ({ label: item, value: item })),
  )

  const formatTypeOptions = computed<DatasetSelectOption[]>(() => [
    { label: options.t('datasetOps.fields.autoDetect'), value: '' },
    ...resolveSupportedImportFormatTypes(taskType.value).map((item) => ({
      label: resolveImportFormatDisplayName(item),
      value: item,
    })),
  ])

  const exportFormatSelectOptions = computed<DatasetSelectOption[]>(() =>
    exportFormatOptions.value.map((item) => ({ label: item, value: item })),
  )

  function setFormatType(value: DatasetSelectValue): void {
    formatType.value = selectValueToString(value)
  }

  function setTaskType(value: DatasetSelectValue): void {
    taskType.value = selectValueToString(value) || taskType.value
    syncImportSelectionFromCapabilities()
  }

  function setExportFormatId(value: DatasetSelectValue): void {
    exportFormatId.value = selectValueToString(value)
  }

  function resolveSupportedImportFormatTypes(taskTypeValue: string): string[] {
    return supportedImportFormatTypesByTaskType.value[taskTypeValue.trim().toLowerCase()] ?? []
  }

  function resolveSupportedExportFormatTypes(taskTypeValue: string): string[] {
    return supportedExportFormatTypesByTaskType.value[taskTypeValue.trim().toLowerCase()] ?? []
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

  async function loadExportFormatCatalog(): Promise<void> {
    exportFormats.value = await getDatasetExportFormats()
    syncImportSelectionFromCapabilities()
    syncExportSelectionFromCapabilities()
  }

  watch(
    [supportedImportTaskTypes, supportedImportFormatTypesByTaskType],
    () => {
      syncImportSelectionFromCapabilities()
    },
    { immediate: true, deep: true },
  )

  watch(
    [exportFormats, options.resolvedDatasetVersionTaskType, options.resolvedDatasetVersionId],
    () => {
      syncExportSelectionFromCapabilities()
    },
    { immediate: true, deep: true },
  )

  return {
    exportFormats,
    formatType,
    taskType,
    exportFormatId,
    supportedImportTaskTypes,
    supportedImportFormatTypesByTaskType,
    supportedExportFormatTypesByTaskType,
    taskTypeOptions,
    formatTypeOptions,
    exportFormatOptions,
    exportFormatSelectOptions,
    setFormatType,
    setTaskType,
    setExportFormatId,
    resolveSupportedImportFormatTypes,
    resolveSupportedExportFormatTypes,
    syncImportSelectionFromCapabilities,
    syncExportSelectionFromCapabilities,
    loadExportFormatCatalog,
  }
}
