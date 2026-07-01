import { apiRequest } from '@/shared/api/http-client'

export type ModelTaskType = 'detection' | 'classification' | 'segmentation' | 'pose' | 'obb'

export interface PlatformBaseModelFile {
  file_id: string
  project_id?: string | null
  scope_kind: string
  model_id: string
  model_version_id?: string | null
  model_build_id?: string | null
  file_type: string
  logical_name: string
  storage_uri: string
  metadata: Record<string, unknown>
}

export interface PlatformBaseModelVersionSummary {
  model_version_id: string
  source_kind: string
  dataset_version_id?: string | null
  training_task_id?: string | null
  parent_version_id?: string | null
  file_ids: string[]
  metadata: Record<string, unknown>
  checkpoint_file_id?: string | null
  checkpoint_storage_uri?: string | null
  catalog_manifest_object_key?: string | null
}

export interface PlatformBaseModelVersionDetail extends PlatformBaseModelVersionSummary {
  files: PlatformBaseModelFile[]
}

export interface PlatformBaseModelBuild {
  model_build_id: string
  source_model_version_id: string
  build_format: string
  runtime_backend: string
  runtime_precision: string
  runtime_profile_id?: string | null
  conversion_task_id?: string | null
  file_ids: string[]
  metadata: Record<string, unknown>
  files: PlatformBaseModelFile[]
}

export interface PlatformBaseModelSummary {
  model_id: string
  project_id?: string | null
  scope_kind: string
  model_name: string
  model_type: string
  task_type: string
  model_scale: string
  labels_file_id?: string | null
  metadata: Record<string, unknown>
  version_count: number
  build_count: number
  available_versions: PlatformBaseModelVersionSummary[]
}

export interface PlatformBaseModelDetail extends PlatformBaseModelSummary {
  versions: PlatformBaseModelVersionDetail[]
  builds: PlatformBaseModelBuild[]
}

export type DeploymentSourceModelSummary = PlatformBaseModelSummary
export type DeploymentSourceModelDetail = PlatformBaseModelDetail
export type DeploymentSourceModelBuild = PlatformBaseModelBuild
export type DeploymentSourceModelVersionDetail = PlatformBaseModelVersionDetail

export interface ModelTrainingTaskSubmissionResponse {
  task_id: string
  status: string
  queue_name: string
  queue_task_id: string
  dataset_export_id?: string | null
  dataset_export_manifest_key?: string | null
  dataset_version_id?: string | null
  format_id?: string | null
}

export interface ModelTrainingTaskSummary {
  task_id: string
  task_type?: string | null
  model_type?: string | null
  display_name: string
  project_id: string
  created_by?: string | null
  created_at: string
  worker_pool?: string | null
  state: string
  current_attempt_no: number
  started_at?: string | null
  finished_at?: string | null
  progress: Record<string, unknown>
  result: Record<string, unknown>
  error_message?: string | null
  metadata: Record<string, unknown>
  dataset_export_id?: string | null
  dataset_export_manifest_key?: string | null
  dataset_version_id?: string | null
  format_id?: string | null
  recipe_id?: string | null
  model_scale?: string | null
  evaluation_interval?: number | null
  gpu_count?: number | null
  precision?: string | null
  output_model_name?: string | null
  model_version_id?: string | null
  latest_checkpoint_model_version_id?: string | null
  output_object_prefix?: string | null
  checkpoint_object_key?: string | null
  latest_checkpoint_object_key?: string | null
  best_metric_name?: string | null
  best_metric_value?: number | null
  training_summary: Record<string, unknown>
}

export type ModelTrainingTaskActionName = 'save' | 'pause' | 'resume' | 'terminate' | 'delete'

export interface ModelTrainingTaskControlStatus {
  status: string
  pending_action?: ModelTrainingTaskActionName | null
  requested_at?: string | null
  requested_by?: string | null
  last_save_at?: string | null
  last_save_epoch?: number | null
  last_save_reason?: string | null
  last_save_by?: string | null
  last_resume_at?: string | null
  last_resume_by?: string | null
  resume_count: number
  resume_checkpoint_object_key?: string | null
}

export interface ModelTrainingTaskEvent {
  event_id: string
  task_id: string
  attempt_id?: string | null
  event_type: string
  created_at: string
  message: string
  payload: Record<string, unknown>
}

export interface ModelTrainingTaskDetail extends ModelTrainingTaskSummary {
  available_actions: ModelTrainingTaskActionName[]
  control_status: ModelTrainingTaskControlStatus
  task_spec: Record<string, unknown>
  events: ModelTrainingTaskEvent[]
}

export interface ModelTrainingOutputFileSummary {
  file_name: string
  file_kind: string
  file_status: string
  task_state: string
  object_key?: string | null
  size_bytes?: number | null
  updated_at?: string | null
}

export interface ModelTrainingOutputFileDetail extends ModelTrainingOutputFileSummary {
  payload: Record<string, unknown>
  text_content?: string | null
  lines: string[]
}

export interface ModelTrainingTaskCreateInput {
  taskType: ModelTaskType
  projectId: string
  modelType: string
  datasetExportId?: string
  datasetExportManifestKey?: string
  recipeId?: string
  modelScale: string
  outputModelName: string
  warmStartModelVersionId?: string
  evaluationInterval?: number
  maxEpochs?: number
  batchSize?: number
  gpuCount?: number
  precision?: string
  inputWidth?: number
  inputHeight?: number
  displayName?: string
  extraOptions?: Record<string, unknown>
}

export interface ModelConversionBuildSummary {
  model_build_id: string
  build_format: string
  runtime_backend: string
  runtime_precision: string
  build_file_id: string
  build_file_uri: string
  metadata: Record<string, unknown>
}

export interface ModelConversionTaskSubmissionResponse {
  task_id: string
  status: string
  queue_name: string
  queue_task_id: string
  task_type?: string
  model_type?: string
  source_model_version_id: string
  target_formats: string[]
}

export interface ModelConversionTaskSummary {
  task_id: string
  display_name: string
  project_id: string
  created_by?: string | null
  created_at: string
  worker_pool?: string | null
  state: string
  current_attempt_no: number
  started_at?: string | null
  finished_at?: string | null
  progress: Record<string, unknown>
  result: Record<string, unknown>
  error_message?: string | null
  metadata: Record<string, unknown>
  task_type?: string
  model_type?: string
  source_model_version_id: string
  target_formats: string[]
  runtime_profile_id?: string | null
  output_object_prefix?: string | null
  requested_target_formats: string[]
  produced_formats: string[]
  builds: ModelConversionBuildSummary[]
  report_summary: Record<string, unknown>
}

export type ConversionTargetKey =
  | 'onnx'
  | 'onnx-optimized'
  | 'openvino-ir-fp32'
  | 'openvino-ir-fp16'
  | 'tensorrt-engine-fp32'
  | 'tensorrt-engine-fp16'

export interface ModelConversionTaskCreateInput {
  taskType: ModelTaskType
  projectId: string
  modelType: string
  sourceModelVersionId: string
  target: ConversionTargetKey
  runtimeProfileId?: string
  displayName?: string
}

const detectionConversionTargetPath: Record<ConversionTargetKey, string> = {
  onnx: '/models/detection/conversion-tasks/onnx',
  'onnx-optimized': '/models/detection/conversion-tasks/onnx-optimized',
  'openvino-ir-fp32': '/models/detection/conversion-tasks/openvino-ir-fp32',
  'openvino-ir-fp16': '/models/detection/conversion-tasks/openvino-ir-fp16',
  'tensorrt-engine-fp32': '/models/detection/conversion-tasks/tensorrt-engine-fp32',
  'tensorrt-engine-fp16': '/models/detection/conversion-tasks/tensorrt-engine-fp16',
}

function buildTrainingTaskPath(taskType: ModelTaskType, suffix = ''): string {
  return `/models/${taskType}/training-tasks${suffix}`
}

function buildConversionTaskPath(taskType: ModelTaskType, suffix = ''): string {
  return `/models/${taskType}/conversion-tasks${suffix}`
}

function buildConversionRequestTarget(target: ConversionTargetKey): { targetFormats: string[]; extraOptions: Record<string, unknown> } {
  if (target === 'openvino-ir-fp32') return { targetFormats: ['openvino-ir'], extraOptions: { openvino_ir_precision: 'fp32' } }
  if (target === 'openvino-ir-fp16') return { targetFormats: ['openvino-ir'], extraOptions: { openvino_ir_precision: 'fp16' } }
  if (target === 'tensorrt-engine-fp32') return { targetFormats: ['tensorrt-engine'], extraOptions: { tensorrt_engine_precision: 'fp32' } }
  if (target === 'tensorrt-engine-fp16') return { targetFormats: ['tensorrt-engine'], extraOptions: { tensorrt_engine_precision: 'fp16' } }
  return { targetFormats: [target], extraOptions: {} }
}

export async function listPlatformBaseModels(taskType?: ModelTaskType): Promise<PlatformBaseModelSummary[]> {
  return apiRequest<PlatformBaseModelSummary[]>('/models/platform-base', {
    query: {
      limit: 100,
      task_type: taskType || undefined,
    },
  })
}

export async function getPlatformBaseModelDetail(modelId: string): Promise<PlatformBaseModelDetail> {
  return apiRequest<PlatformBaseModelDetail>(`/models/platform-base/${encodeURIComponent(modelId)}`)
}

export async function listDeploymentSourceModels(
  projectId: string,
  taskType?: ModelTaskType,
): Promise<DeploymentSourceModelSummary[]> {
  return apiRequest<DeploymentSourceModelSummary[]>('/models/deployment-sources', {
    query: {
      project_id: projectId,
      task_type: taskType || undefined,
      limit: 100,
    },
  })
}

export async function getDeploymentSourceModelDetail(
  projectId: string,
  modelId: string,
): Promise<DeploymentSourceModelDetail> {
  return apiRequest<DeploymentSourceModelDetail>(`/models/deployment-sources/${encodeURIComponent(modelId)}`, {
    query: { project_id: projectId },
  })
}

export async function createModelTrainingTask(input: ModelTrainingTaskCreateInput): Promise<ModelTrainingTaskSubmissionResponse> {
  const extraOptions: Record<string, unknown> = {
    ...(input.extraOptions ?? {}),
  }
  if (
    (input.taskType === 'classification' || input.taskType === 'segmentation')
    && typeof input.evaluationInterval === 'number'
    && Number.isFinite(input.evaluationInterval)
  ) {
    extraOptions.evaluation_interval = input.evaluationInterval
  }
  const body: Record<string, unknown> = {
    project_id: input.projectId,
    model_type: input.modelType,
    dataset_export_id: input.datasetExportId || null,
    dataset_export_manifest_key: input.datasetExportManifestKey || null,
    recipe_id: input.recipeId || 'default',
    model_scale: input.modelScale,
    output_model_name: input.outputModelName,
    warm_start_model_version_id: input.warmStartModelVersionId || null,
    max_epochs: input.maxEpochs,
    batch_size: input.batchSize,
    precision: input.precision || null,
    input_size: input.inputWidth && input.inputHeight ? [input.inputWidth, input.inputHeight] : null,
    extra_options: extraOptions,
    display_name: input.displayName ?? '',
  }

  if (input.taskType === 'detection') {
    body.evaluation_interval = input.evaluationInterval
    body.gpu_count = input.gpuCount
  } else if (input.taskType === 'pose' || input.taskType === 'obb') {
    body.evaluation_interval = input.evaluationInterval
  }

  return apiRequest<ModelTrainingTaskSubmissionResponse>(buildTrainingTaskPath(input.taskType), {
    method: 'POST',
    body,
  })
}

export async function listModelTrainingTasks(
  taskType: ModelTaskType,
  projectId: string,
  modelType?: string,
): Promise<ModelTrainingTaskSummary[]> {
  return apiRequest<ModelTrainingTaskSummary[]>(buildTrainingTaskPath(taskType), {
    query: { project_id: projectId, model_type: modelType || undefined, limit: 100 },
  })
}

export async function getModelTrainingTaskDetail(taskType: ModelTaskType, taskId: string): Promise<ModelTrainingTaskDetail> {
  return apiRequest<ModelTrainingTaskDetail>(buildTrainingTaskPath(taskType, `/${encodeURIComponent(taskId)}`), {
    query: { include_events: true },
  })
}

export async function requestModelTrainingTaskAction(
  taskType: ModelTaskType,
  taskId: string,
  action: Exclude<ModelTrainingTaskActionName, 'delete'>,
): Promise<ModelTrainingTaskDetail | ModelTrainingTaskSubmissionResponse> {
  return apiRequest<ModelTrainingTaskDetail | ModelTrainingTaskSubmissionResponse>(
    buildTrainingTaskPath(taskType, `/${encodeURIComponent(taskId)}/${action}`),
    { method: 'POST' },
  )
}

export async function deleteModelTrainingTask(taskType: ModelTaskType, taskId: string): Promise<void> {
  return apiRequest<void>(buildTrainingTaskPath(taskType, `/${encodeURIComponent(taskId)}`), {
    method: 'DELETE',
    responseType: 'void',
  })
}

export async function registerModelTrainingLatestCheckpoint(taskType: ModelTaskType, taskId: string): Promise<ModelTrainingTaskDetail> {
  return apiRequest<ModelTrainingTaskDetail>(
    buildTrainingTaskPath(taskType, `/${encodeURIComponent(taskId)}/register-model-version`),
    { method: 'POST' },
  )
}

export async function listModelTrainingOutputFiles(taskType: ModelTaskType, taskId: string): Promise<ModelTrainingOutputFileSummary[]> {
  return apiRequest<ModelTrainingOutputFileSummary[]>(
    buildTrainingTaskPath(taskType, `/${encodeURIComponent(taskId)}/output-files`),
  )
}

export async function getModelTrainingOutputFileDetail(
  taskType: ModelTaskType,
  taskId: string,
  fileName: string,
): Promise<ModelTrainingOutputFileDetail> {
  return apiRequest<ModelTrainingOutputFileDetail>(
    buildTrainingTaskPath(taskType, `/${encodeURIComponent(taskId)}/output-files/${encodeURIComponent(fileName)}`),
  )
}

export async function createModelConversionTask(input: ModelConversionTaskCreateInput): Promise<ModelConversionTaskSubmissionResponse> {
  const targetRequest = buildConversionRequestTarget(input.target)
  const path = input.taskType === 'detection'
    ? detectionConversionTargetPath[input.target]
    : buildConversionTaskPath(input.taskType)
  return apiRequest<ModelConversionTaskSubmissionResponse>(path, {
    method: 'POST',
    body: {
      project_id: input.projectId,
      model_type: input.modelType,
      source_model_version_id: input.sourceModelVersionId,
      target_formats: input.taskType === 'detection' ? undefined : targetRequest.targetFormats,
      runtime_profile_id: input.runtimeProfileId || null,
      extra_options: targetRequest.extraOptions,
      display_name: input.displayName ?? '',
    },
  })
}

export async function listModelConversionTasks(
  taskType: ModelTaskType,
  projectId: string,
  modelType?: string,
): Promise<ModelConversionTaskSummary[]> {
  return apiRequest<ModelConversionTaskSummary[]>(buildConversionTaskPath(taskType), {
    query: { project_id: projectId, model_type: modelType || undefined, limit: 100 },
  })
}

