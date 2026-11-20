import { ref, watch, type ComputedRef, type Ref } from 'vue'
import { ApiError } from '@/shared/api/error'

import {
  listModelConversionTasks,
  listModelTrainingTasks,
  type ModelConversionTaskSummary,
  type ModelTaskType,
  type ModelTrainingTaskSummary,
} from '../services/model.service'

export function useModelTaskLists(
  selectedTaskType: Ref<ModelTaskType>,
  selectedProjectId: ComputedRef<string>,
  principalKey?: ComputedRef<string>,
) {
  const training = taskList<ModelTrainingTaskSummary>(listModelTrainingTasks)
  const conversion = taskList<ModelConversionTaskSummary>(listModelConversionTasks)

  function taskList<T>(fetchList: (taskType: ModelTaskType, projectId: string) => Promise<T[]>) {
    const items = ref<T[]>([]) as Ref<T[]>
    const loading = ref(false)
    const error = ref(false)
    const updatedAt = ref<string>()
    let serial = 0
    watch([selectedTaskType, selectedProjectId, () => principalKey?.value], () => {
      serial++
      items.value = []
      loading.value = false
      error.value = false
      updatedAt.value = undefined
    }, { flush: 'sync' })
    async function refresh(): Promise<void> {
      const request = ++serial
      const taskType = selectedTaskType.value
      const projectId = selectedProjectId.value
      if (!projectId) return
      loading.value = true
      error.value = false
      try {
        const rows = await fetchList(taskType, projectId)
        if (request === serial) { items.value = rows; updatedAt.value = new Date().toISOString() }
      } catch (cause) {
        if (request === serial) {
          error.value = true
          if (cause instanceof ApiError && [401, 403, 404].includes(cause.status)) {
            items.value = []; updatedAt.value = undefined
          }
        }
        throw cause
      } finally { if (request === serial) loading.value = false }
    }
    return { items, loading, error, updatedAt, refresh }
  }

  async function refreshTaskLists(): Promise<void> {
    await Promise.allSettled([training.refresh(), conversion.refresh()])
  }

  return {
    training,
    conversion,
    trainingTasks: training.items,
    conversionTasks: conversion.items,
    refreshTrainingTasks: training.refresh,
    refreshConversionTasks: conversion.refresh,
    refreshTaskLists,
  }
}
