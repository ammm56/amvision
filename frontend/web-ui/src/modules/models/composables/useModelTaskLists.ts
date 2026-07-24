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
  let trainingRequestSerial = 0
  let conversionRequestSerial = 0

  async function refreshTrainingTasks(): Promise<void> {
    const requestSerial = ++trainingRequestSerial
    const taskType = selectedTaskType.value
    const projectId = selectedProjectId.value
    const tasks = await listModelTrainingTasks(taskType, projectId)
    if (
      requestSerial === trainingRequestSerial
      && selectedTaskType.value === taskType
      && selectedProjectId.value === projectId
    ) {
      trainingTasks.value = tasks
    }
  }

  async function refreshConversionTasks(): Promise<void> {
    const requestSerial = ++conversionRequestSerial
    const taskType = selectedTaskType.value
    const projectId = selectedProjectId.value
    const tasks = await listModelConversionTasks(taskType, projectId)
    if (
      requestSerial === conversionRequestSerial
      && selectedTaskType.value === taskType
      && selectedProjectId.value === projectId
    ) {
      conversionTasks.value = tasks
    }
  }

  async function refreshTaskLists(): Promise<void> {
    const trainingSerial = ++trainingRequestSerial
    const conversionSerial = ++conversionRequestSerial
    const taskType = selectedTaskType.value
    const projectId = selectedProjectId.value
    const [training, conversion] = await Promise.all([
      listModelTrainingTasks(taskType, projectId),
      listModelConversionTasks(taskType, projectId),
    ])
    const selectionStillCurrent = selectedTaskType.value === taskType
      && selectedProjectId.value === projectId
    if (selectionStillCurrent && trainingSerial === trainingRequestSerial) {
      trainingTasks.value = training
    }
    if (selectionStillCurrent && conversionSerial === conversionRequestSerial) {
      conversionTasks.value = conversion
    }
  }

  return {
    trainingTasks,
    conversionTasks,
    refreshTrainingTasks,
    refreshConversionTasks,
    refreshTaskLists,
  }
}
