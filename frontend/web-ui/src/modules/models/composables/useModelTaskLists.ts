import { ref, type ComputedRef, type Ref } from 'vue'

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
) {
  const trainingTasks = ref<ModelTrainingTaskSummary[]>([])
  const conversionTasks = ref<ModelConversionTaskSummary[]>([])

  async function refreshTrainingTasks(): Promise<void> {
    trainingTasks.value = await listModelTrainingTasks(selectedTaskType.value, selectedProjectId.value)
  }

  async function refreshConversionTasks(): Promise<void> {
    conversionTasks.value = await listModelConversionTasks(selectedTaskType.value, selectedProjectId.value)
  }

  async function refreshTaskLists(): Promise<void> {
    const [training, conversion] = await Promise.all([
      listModelTrainingTasks(selectedTaskType.value, selectedProjectId.value),
      listModelConversionTasks(selectedTaskType.value, selectedProjectId.value),
    ])
    trainingTasks.value = training
    conversionTasks.value = conversion
  }

  return {
    trainingTasks,
    conversionTasks,
    refreshTrainingTasks,
    refreshConversionTasks,
    refreshTaskLists,
  }
}
