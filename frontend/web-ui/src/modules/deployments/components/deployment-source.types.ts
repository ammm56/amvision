import type { ModelTaskType } from '../services/deployment.service'

export type DeploymentSourceKind = 'model-version' | 'model-build'

export interface DeploymentSourceSelection {
  sourceKind: DeploymentSourceKind
  modelId: string
  modelName: string
  modelType: string
  modelScale: string
  taskType: ModelTaskType
  modelVersionId: string
  modelBuildId: string
  buildFormat: string
  runtimeProfileId: string
  runtimeBackend: string
  runtimePrecision: string
  buildMetadata: Record<string, unknown>
}
