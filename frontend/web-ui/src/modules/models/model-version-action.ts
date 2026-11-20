import type { ModelTaskType, ModelTrainingTaskSummary } from './services/model.service'

export interface ModelVersionAction {
  projectId: string
  modelId: string
  versionId: string
  taskType: ModelTaskType
  buildId?: string
}

export const modelVersionTaskTypes: readonly ModelTaskType[] = ['detection', 'classification', 'segmentation', 'pose', 'obb']

export function isModelVersionTaskType(value: unknown): value is ModelTaskType {
  return modelVersionTaskTypes.some(taskType => taskType === value)
}

export function isDeletedTrainingVersion(task: ModelTrainingTaskSummary | null, versionId: string | null | undefined): boolean {
  const ids = task?.metadata?.deleted_model_version_ids
  return !!versionId && Array.isArray(ids) && ids.includes(versionId)
}
