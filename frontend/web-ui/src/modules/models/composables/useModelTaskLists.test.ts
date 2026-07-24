import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import type {
  ModelConversionTaskSummary,
  ModelTrainingTaskSummary,
} from '../services/model.service'

const serviceMocks = vi.hoisted(() => ({
  listModelTrainingTasks: vi.fn(),
  listModelConversionTasks: vi.fn(),
}))

vi.mock('../services/model.service', () => ({
  listModelTrainingTasks: serviceMocks.listModelTrainingTasks,
  listModelConversionTasks: serviceMocks.listModelConversionTasks,
}))

import { useModelTaskLists } from './useModelTaskLists'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

function trainingTask(taskId: string): ModelTrainingTaskSummary {
  return { task_id: taskId } as ModelTrainingTaskSummary
}

function conversionTask(taskId: string): ModelConversionTaskSummary {
  return { task_id: taskId } as ModelConversionTaskSummary
}

describe('useModelTaskLists', () => {
  beforeEach(() => {
    serviceMocks.listModelTrainingTasks.mockReset()
    serviceMocks.listModelConversionTasks.mockReset()
  })

  it('ignores stale task lists after the task type changes', async () => {
    const detectionTraining = deferred<ModelTrainingTaskSummary[]>()
    const classificationTraining = deferred<ModelTrainingTaskSummary[]>()
    const detectionConversion = deferred<ModelConversionTaskSummary[]>()
    const classificationConversion = deferred<ModelConversionTaskSummary[]>()
    serviceMocks.listModelTrainingTasks
      .mockReturnValueOnce(detectionTraining.promise)
      .mockReturnValueOnce(classificationTraining.promise)
    serviceMocks.listModelConversionTasks
      .mockReturnValueOnce(detectionConversion.promise)
      .mockReturnValueOnce(classificationConversion.promise)

    const taskType = ref<'detection' | 'classification'>('detection')
    const projectId = ref('project-1')
    const lists = useModelTaskLists(taskType, computed(() => projectId.value))

    const detectionRequest = lists.refreshTaskLists()
    taskType.value = 'classification'
    const classificationRequest = lists.refreshTaskLists()

    classificationTraining.resolve([trainingTask('classification-training')])
    classificationConversion.resolve([conversionTask('classification-conversion')])
    await classificationRequest

    detectionTraining.resolve([trainingTask('detection-training')])
    detectionConversion.resolve([conversionTask('detection-conversion')])
    await detectionRequest

    expect(lists.trainingTasks.value.map((task) => task.task_id)).toEqual(['classification-training'])
    expect(lists.conversionTasks.value.map((task) => task.task_id)).toEqual(['classification-conversion'])
  })
})
