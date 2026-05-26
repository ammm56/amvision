import { apiRequest } from '@/shared/api/http-client'

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

export interface YoloXTrainingTaskSubmissionResponse {
  task_id: string
  status: string
  queue_name: string
  queue_task_id: string
  dataset_export_id: string
  dataset_export_manifest_key: string
  dataset_version_id: string
  format_id: string
}

export interface YoloXTrainingTaskSummary {
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

export type YoloXTrainingTaskActionName = 'save' | 'pause' | 'resume' | 'terminate' | 'delete'

export interface YoloXTrainingTaskControlStatus {
  status: string
  pending_action?: YoloXTrainingTaskActionName | null
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

export interface YoloXTrainingTaskEvent {
  event_id: string
  task_id: string
  attempt_id?: string | null
  event_type: string
  created_at: string
  message: string
  payload: Record<string, unknown>
}

export interface YoloXTrainingTaskDetail extends YoloXTrainingTaskSummary {
  available_actions: YoloXTrainingTaskActionName[]
  control_status: YoloXTrainingTaskControlStatus
  task_spec: Record<string, unknown>
  events: YoloXTrainingTaskEvent[]
}

export interface YoloXTrainingOutputFileSummary {
  file_name: string
  file_kind: string
  file_status: string
  task_state: string
  object_key?: string | null
  size_bytes?: number | null
  updated_at?: string | null
}

export interface YoloXTrainingOutputFileDetail extends YoloXTrainingOutputFileSummary {
  payload: Record<string, unknown>
  text_content?: string | null
  lines: string[]
}

export interface YoloXTrainingTaskCreateInput {
  projectId: string
  datasetExportId?: string
  datasetExportManifestKey?: string
  recipeId: string
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
}

export interface YoloXConversionBuildSummary {
  model_build_id: string
  build_format: string
  build_file_id: string
  build_file_uri: string
  metadata: Record<string, unknown>
}

export interface YoloXConversionTaskSubmissionResponse {
  task_id: string
  status: string
  queue_name: string
  queue_task_id: string
  source_model_version_id: string
  target_formats: string[]
}

export interface YoloXConversionTaskSummary {
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
  source_model_version_id: string
  target_formats: string[]
  runtime_profile_id?: string | null
  output_object_prefix?: string | null
  requested_target_formats: string[]
  produced_formats: string[]
  builds: YoloXConversionBuildSummary[]
  report_summary: Record<string, unknown>
}

export type ConversionTargetKey =
  | 'onnx'
  | 'onnx-optimized'
  | 'openvino-ir-fp32'
  | 'openvino-ir-fp16'
  | 'tensorrt-engine-fp32'
  | 'tensorrt-engine-fp16'

export interface YoloXConversionTaskCreateInput {
  projectId: string
  sourceModelVersionId: string
  target: ConversionTargetKey
  runtimeProfileId?: string
  displayName?: string
}

const conversionTargetPath: Record<ConversionTargetKey, string> = {
  onnx: '/models/yolox/conversion-tasks/onnx',
  'onnx-optimized': '/models/yolox/conversion-tasks/onnx-optimized',
  'openvino-ir-fp32': '/models/yolox/conversion-tasks/openvino-ir-fp32',
  'openvino-ir-fp16': '/models/yolox/conversion-tasks/openvino-ir-fp16',
  'tensorrt-engine-fp32': '/models/yolox/conversion-tasks/tensorrt-engine-fp32',
  'tensorrt-engine-fp16': '/models/yolox/conversion-tasks/tensorrt-engine-fp16',
}

export async function listPlatformBaseModels(): Promise<PlatformBaseModelSummary[]> {
  return apiRequest<PlatformBaseModelSummary[]>('/models/platform-base', { query: { limit: 100 } })
}

export async function getPlatformBaseModelDetail(modelId: string): Promise<PlatformBaseModelDetail> {
  return apiRequest<PlatformBaseModelDetail>(`/models/platform-base/${encodeURIComponent(modelId)}`)
}

export async function createYoloXTrainingTask(input: YoloXTrainingTaskCreateInput): Promise<YoloXTrainingTaskSubmissionResponse> {
  return apiRequest<YoloXTrainingTaskSubmissionResponse>('/models/yolox/training-tasks', {
    method: 'POST',
    body: {
      project_id: input.projectId,
      dataset_export_id: input.datasetExportId || null,
      dataset_export_manifest_key: input.datasetExportManifestKey || null,
      recipe_id: input.recipeId,
      model_scale: input.modelScale,
      output_model_name: input.outputModelName,
      warm_start_model_version_id: input.warmStartModelVersionId || null,
      evaluation_interval: input.evaluationInterval,
      max_epochs: input.maxEpochs,
      batch_size: input.batchSize,
      gpu_count: input.gpuCount,
      precision: input.precision || null,
      input_size: input.inputWidth && input.inputHeight ? [input.inputWidth, input.inputHeight] : null,
      extra_options: {},
      display_name: input.displayName ?? '',
    },
  })
}

export async function listYoloXTrainingTasks(projectId: string): Promise<YoloXTrainingTaskSummary[]> {
  return apiRequest<YoloXTrainingTaskSummary[]>('/models/yolox/training-tasks', {
    query: { project_id: projectId, limit: 100 },
  })
}

export async function getYoloXTrainingTaskDetail(taskId: string): Promise<YoloXTrainingTaskDetail> {
  return apiRequest<YoloXTrainingTaskDetail>(`/models/yolox/training-tasks/${encodeURIComponent(taskId)}`, {
    query: { include_events: true },
  })
}

export async function requestYoloXTrainingTaskAction(
  taskId: string,
  action: Exclude<YoloXTrainingTaskActionName, 'delete'>,
): Promise<YoloXTrainingTaskDetail | YoloXTrainingTaskSubmissionResponse> {
  return apiRequest<YoloXTrainingTaskDetail | YoloXTrainingTaskSubmissionResponse>(
    `/models/yolox/training-tasks/${encodeURIComponent(taskId)}/${action}`,
    { method: 'POST' },
  )
}

export async function deleteYoloXTrainingTask(taskId: string): Promise<void> {
  return apiRequest<void>(`/models/yolox/training-tasks/${encodeURIComponent(taskId)}`, {
    method: 'DELETE',
    responseType: 'void',
  })
}

export async function registerYoloXTrainingLatestCheckpoint(taskId: string): Promise<YoloXTrainingTaskDetail> {
  return apiRequest<YoloXTrainingTaskDetail>(
    `/models/yolox/training-tasks/${encodeURIComponent(taskId)}/register-model-version`,
    { method: 'POST' },
  )
}

export async function listYoloXTrainingOutputFiles(taskId: string): Promise<YoloXTrainingOutputFileSummary[]> {
  return apiRequest<YoloXTrainingOutputFileSummary[]>(
    `/models/yolox/training-tasks/${encodeURIComponent(taskId)}/output-files`,
  )
}

export async function getYoloXTrainingOutputFileDetail(
  taskId: string,
  fileName: string,
): Promise<YoloXTrainingOutputFileDetail> {
  return apiRequest<YoloXTrainingOutputFileDetail>(
    `/models/yolox/training-tasks/${encodeURIComponent(taskId)}/output-files/${encodeURIComponent(fileName)}`,
  )
}

export async function createYoloXConversionTask(input: YoloXConversionTaskCreateInput): Promise<YoloXConversionTaskSubmissionResponse> {
  return apiRequest<YoloXConversionTaskSubmissionResponse>(conversionTargetPath[input.target], {
    method: 'POST',
    body: {
      project_id: input.projectId,
      source_model_version_id: input.sourceModelVersionId,
      runtime_profile_id: input.runtimeProfileId || null,
      extra_options: {},
      display_name: input.displayName ?? '',
    },
  })
}

export async function listYoloXConversionTasks(projectId: string): Promise<YoloXConversionTaskSummary[]> {
  return apiRequest<YoloXConversionTaskSummary[]>('/models/yolox/conversion-tasks', {
    query: { project_id: projectId, limit: 100 },
  })
}