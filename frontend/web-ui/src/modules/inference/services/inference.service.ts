import { apiRequest } from '@/shared/api/http-client'
import { getRuntimeConfig } from '@/platform/runtime/runtime-config'
import type { ModelTaskType } from '@/modules/deployments/services/deployment.service'

export const SUPPORTED_INFERENCE_TASK_TYPES: readonly ModelTaskType[] = [
  'detection',
  'classification',
  'segmentation',
  'pose',
  'obb',
] as const

export interface TaskInferenceBoxItem {
  bbox_xyxy: [number, number, number, number]
  score: number
  class_id: number
  class_name?: string | null
}

export interface TaskInferenceCommonPayload {
  request_id: string
  inference_task_id?: string | null
  deployment_instance_id: string
  instance_id?: string | null
  model_version_id: string
  model_build_id?: string | null
  input_uri: string
  input_source_kind: string
  input_file_id?: string | null
  save_result_image: boolean
  return_preview_image_base64: boolean
  image_width: number
  image_height: number
  latency_ms?: number | null
  decode_ms?: number | null
  preprocess_ms?: number | null
  infer_ms?: number | null
  postprocess_ms?: number | null
  serialize_ms?: number | null
  labels: string[]
  runtime_session_info: Record<string, unknown>
  preview_image_uri?: string | null
  preview_image_base64?: string | null
  result_object_key?: string | null
}

export interface DetectionInferencePayload extends TaskInferenceCommonPayload {
  score_threshold: number
  detection_count: number
  detections: TaskInferenceBoxItem[]
}

export interface ClassificationInferenceCategory {
  class_id: number
  probability: number
  class_name?: string | null
  logit?: number | null
}

export interface ClassificationInferencePayload extends TaskInferenceCommonPayload {
  top_k: number
  category_count: number
  categories: ClassificationInferenceCategory[]
  top_category?: ClassificationInferenceCategory | null
}

export interface SegmentationInferenceItem extends TaskInferenceBoxItem {
  segments: [number, number][][]
  mask_area?: number | null
}

export interface SegmentationInferencePayload extends TaskInferenceCommonPayload {
  score_threshold: number
  mask_threshold: number
  instance_count: number
  instances: SegmentationInferenceItem[]
}

export interface PoseInferenceKeypoint {
  x: number
  y: number
  confidence?: number | null
}

export interface PoseInferenceItem extends TaskInferenceBoxItem {
  keypoints: PoseInferenceKeypoint[]
  kpt_shape: [number, number]
}

export interface PoseInferencePayload extends TaskInferenceCommonPayload {
  score_threshold: number
  keypoint_confidence_threshold: number
  instance_count: number
  instances: PoseInferenceItem[]
}

export interface ObbInferenceItem extends TaskInferenceBoxItem {
  bbox_xywhr: [number, number, number, number, number]
  angle?: number | null
}

export interface ObbInferencePayload extends TaskInferenceCommonPayload {
  score_threshold: number
  instance_count: number
  instances: ObbInferenceItem[]
}

export type TaskInferencePayload =
  | DetectionInferencePayload
  | ClassificationInferencePayload
  | SegmentationInferencePayload
  | PoseInferencePayload
  | ObbInferencePayload

export interface TaskInferenceTaskSubmission {
  task_id: string
  status: string
  queue_name: string
  queue_task_id: string
  deployment_instance_id: string
  input_uri: string
  input_source_kind: string
}

export interface TaskInferenceTaskSummary {
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
  deployment_instance_id: string
  instance_id?: string | null
  model_version_id?: string | null
  model_build_id?: string | null
  input_uri?: string | null
  input_source_kind?: string | null
  input_file_id?: string | null
  score_threshold?: number | null
  save_result_image: boolean
  output_object_prefix?: string | null
  result_object_key?: string | null
  preview_image_object_key?: string | null
  item_count?: number | null
  latency_ms?: number | null
  result_summary: Record<string, unknown>
}

export interface TaskInferenceTaskResult {
  file_status: 'pending' | 'ready'
  task_state: string
  object_key?: string | null
  payload: Record<string, unknown>
}

export interface TaskInferenceDebugInput {
  taskType: ModelTaskType
  projectId: string
  deploymentInstanceId: string
  inputFileId?: string
  inputUri?: string
  imageBase64?: string
  inputImage?: File | null
  inputTransportMode: 'storage' | 'memory'
  scoreThreshold?: number
  topK?: number
  maskThreshold?: number
  keypointConfidenceThreshold?: number
  saveResultImage: boolean
  returnPreviewImageBase64: boolean
  displayName?: string
  requestId?: string
  signal?: AbortSignal
}

export interface TaskInferenceTaskListInput {
  taskType: ModelTaskType
  projectId: string
  deploymentInstanceId?: string
  limit?: number
}

export interface ProjectPublicFileEntry {
  project_id: string
  file_id: string
  object_key: string
  file_name: string
  media_type: string
  size_bytes: number
  last_modified_at: string
  content_url: string
  download_url: string
}

export interface DatasetSampleFileRef {
  file_id: string
  object_key: string
  file_name: string
  sample_id: string
  split: string
  width?: number | null
  height?: number | null
}

export interface DirectInferenceRecordSummary {
  record_id: string
  project_id: string
  request_id: string
  task_type: ModelTaskType
  deployment_instance_id: string
  deployment_display_name: string
  model_version_id?: string | null
  model_build_id?: string | null
  input_source_kind: string
  input_label: string
  input_uri?: string | null
  input_file_id?: string | null
  has_input_image: boolean
  has_preview_image: boolean
  result_object_key: string
  preview_image_object_key?: string | null
  item_count: number
  latency_ms?: number | null
  image_width?: number | null
  image_height?: number | null
  parameters: Record<string, unknown>
  result_summary: Record<string, unknown>
  created_by?: string | null
  created_at: string
}

export interface DirectInferenceRecordDetail extends DirectInferenceRecordSummary {
  file_status: 'ready' | 'missing'
  result_payload: Record<string, unknown>
}

export interface SaveDirectInferenceRecordInput {
  projectId: string
  requestId: string
  taskType: ModelTaskType
  deploymentInstanceId: string
  resultPayload: Record<string, unknown>
  inputLabel?: string
  inputImageBase64?: string
  inputImageFile?: File | null
  parameters?: Record<string, unknown>
}

export interface BatchInferenceTask {
  batch_task_id: string
  project_id: string
  task_type: ModelTaskType
  display_name: string
  deployment_instance_id: string
  deployment_display_name: string
  model_version_id?: string | null
  model_build_id?: string | null
  source_kind: 'upload' | 'dataset_version' | 'project_files' | string
  source_summary: Record<string, unknown>
  parameters: Record<string, unknown>
  state: 'queued' | 'running' | 'succeeded' | 'partial_failed' | 'failed' | 'cancelled' | string
  total_items: number
  completed_items: number
  succeeded_items: number
  failed_items: number
  skipped_items: number
  output_object_prefix: string
  error_message?: string | null
  created_by?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  updated_at: string
}

export interface BatchInferenceTaskItem {
  item_id: string
  batch_task_id: string
  sequence_no: number
  input_label: string
  input_source_kind: string
  input_file_id?: string | null
  input_uri?: string | null
  has_input_image: boolean
  has_preview_image: boolean
  dataset_id?: string | null
  dataset_version_id?: string | null
  sample_id?: string | null
  state: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | string
  item_count?: number | null
  latency_ms?: number | null
  image_width?: number | null
  image_height?: number | null
  result_object_key?: string | null
  preview_image_object_key?: string | null
  result_summary: Record<string, unknown>
  error_code?: string | null
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
}

function buildInferenceTaskPath(taskType: ModelTaskType, suffix = ''): string {
  return `/models/${taskType}/inference-tasks${suffix}`
}

function buildDeploymentInferencePath(taskType: ModelTaskType, deploymentInstanceId: string): string {
  return `/models/${taskType}/deployment-instances/${encodeURIComponent(deploymentInstanceId)}/infer`
}

function buildInferenceFormData(input: TaskInferenceDebugInput, includeTaskFields: boolean): FormData {
  const formData = new FormData()
  if (includeTaskFields) {
    formData.set('project_id', input.projectId)
    formData.set('deployment_instance_id', input.deploymentInstanceId)
    formData.set('display_name', input.displayName ?? '')
  }
  if (input.inputFileId) formData.set('input_file_id', input.inputFileId)
  if (input.inputUri) formData.set('input_uri', input.inputUri)
  if (input.imageBase64) formData.set('image_base64', input.imageBase64)
  if (input.inputImage) formData.set('input_image', input.inputImage)
  formData.set('input_transport_mode', input.inputTransportMode)
  if (input.taskType === 'classification') {
    if (typeof input.topK === 'number') formData.set('top_k', String(input.topK))
  } else {
    if (typeof input.scoreThreshold === 'number') formData.set('score_threshold', String(input.scoreThreshold))
    if (input.taskType === 'segmentation' && typeof input.maskThreshold === 'number') {
      formData.set('mask_threshold', String(input.maskThreshold))
    }
    if (input.taskType === 'pose' && typeof input.keypointConfidenceThreshold === 'number') {
      formData.set('keypoint_confidence_threshold', String(input.keypointConfidenceThreshold))
    }
  }
  formData.set('save_result_image', String(input.saveResultImage))
  formData.set('return_preview_image_base64', String(input.returnPreviewImageBase64))
  formData.set('extra_options', '{}')
  return formData
}

export async function inferTaskDeployment(input: TaskInferenceDebugInput): Promise<TaskInferencePayload> {
  const headers: Record<string, string> = {}
  if (input.requestId?.trim()) {
    headers['X-Request-Id'] = input.requestId.trim()
  }
  return apiRequest<TaskInferencePayload>(
    buildDeploymentInferencePath(input.taskType, input.deploymentInstanceId),
    {
      method: 'POST',
      body: buildInferenceFormData(input, false),
      headers,
      signal: input.signal,
    },
  )
}

export async function createTaskInferenceTask(input: TaskInferenceDebugInput): Promise<TaskInferenceTaskSubmission> {
  return apiRequest<TaskInferenceTaskSubmission>(buildInferenceTaskPath(input.taskType), {
    method: 'POST',
    body: buildInferenceFormData(input, true),
  })
}

export async function listTaskInferenceTasks(input: TaskInferenceTaskListInput): Promise<TaskInferenceTaskSummary[]> {
  return apiRequest<TaskInferenceTaskSummary[]>(buildInferenceTaskPath(input.taskType), {
    query: {
      project_id: input.projectId,
      deployment_instance_id: input.deploymentInstanceId,
      limit: input.limit ?? 20,
    },
  })
}

export async function getTaskInferenceTaskResult(taskType: ModelTaskType, taskId: string): Promise<TaskInferenceTaskResult> {
  return apiRequest<TaskInferenceTaskResult>(buildInferenceTaskPath(taskType, `/${encodeURIComponent(taskId)}/result`))
}

export async function listProjectPublicFiles(
  projectId: string,
  options: { objectPrefix?: string; limit?: number } = {},
): Promise<ProjectPublicFileEntry[]> {
  return apiRequest<ProjectPublicFileEntry[]>(`/projects/${encodeURIComponent(projectId)}/files`, {
    query: {
      object_prefix: options.objectPrefix || undefined,
      limit: options.limit ?? 200,
    },
  })
}

export async function getDatasetSampleFileRef(
  datasetId: string,
  versionId: string,
  sampleId: string,
): Promise<DatasetSampleFileRef> {
  return apiRequest<DatasetSampleFileRef>(
    `/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}/samples/${encodeURIComponent(sampleId)}/file-ref`,
  )
}

export async function fetchAuthorizedProjectFileBlob(projectId: string, objectKey: string): Promise<Blob> {
  return apiRequest<Blob>(`/projects/${encodeURIComponent(projectId)}/files/content`, {
    query: { object_key: objectKey },
    responseType: 'blob',
  })
}

export async function saveDirectInferenceRecord(
  input: SaveDirectInferenceRecordInput,
): Promise<DirectInferenceRecordSummary> {
  const payload = {
    project_id: input.projectId,
    request_id: input.requestId,
    task_type: input.taskType,
    deployment_instance_id: input.deploymentInstanceId,
    result_payload: input.resultPayload,
    input_label: input.inputLabel ?? '',
    input_image_base64: input.inputImageBase64 ?? null,
    parameters: input.parameters ?? {},
  }
  if (input.inputImageFile) {
    const form = new FormData()
    form.set('payload', JSON.stringify(payload))
    form.set('input_image', input.inputImageFile)
    return apiRequest<DirectInferenceRecordSummary>('/inference-records', {
      method: 'POST',
      body: form,
    })
  }
  return apiRequest<DirectInferenceRecordSummary>('/inference-records', {
    method: 'POST',
    body: payload,
  })
}

export async function listDirectInferenceRecords(params: {
  projectId: string
  taskType?: ModelTaskType | ''
  deploymentInstanceId?: string
  requestId?: string
  q?: string
  offset?: number
  limit?: number
}): Promise<DirectInferenceRecordSummary[]> {
  return apiRequest<DirectInferenceRecordSummary[]>('/inference-records', {
    query: {
      project_id: params.projectId,
      task_type: params.taskType || undefined,
      deployment_instance_id: params.deploymentInstanceId || undefined,
      request_id: params.requestId || undefined,
      q: params.q || undefined,
      offset: params.offset ?? 0,
      limit: params.limit ?? 50,
    },
  })
}

export async function getDirectInferenceRecord(recordId: string): Promise<DirectInferenceRecordDetail> {
  return apiRequest<DirectInferenceRecordDetail>(`/inference-records/${encodeURIComponent(recordId)}`)
}

export async function deleteDirectInferenceRecord(recordId: string): Promise<void> {
  await apiRequest<void>(`/inference-records/${encodeURIComponent(recordId)}`, {
    method: 'DELETE',
  })
}

export function buildDirectInferenceRecordImageUrl(
  recordId: string,
  kind: 'input' | 'preview' = 'input',
  download = false,
): string {
  const base = getRuntimeConfig().apiBaseUrl.replace(/\/$/, '')
  const search = new URLSearchParams({ kind })
  if (download) search.set('download', 'true')
  return `${base}/inference-records/${encodeURIComponent(recordId)}/image?${search.toString()}`
}

export interface BatchInferenceTaskItemResult {
  file_status: 'pending' | 'ready' | 'missing'
  item_state: string
  object_key?: string | null
  payload: Record<string, unknown>
}

export interface CreateBatchInferenceTaskInput {
  projectId: string
  taskType: ModelTaskType
  deploymentInstanceId: string
  runtimeMode?: 'auto' | 'async' | 'sync'
  displayName?: string
  sourceKind: 'upload' | 'dataset_version' | 'project_files'
  files?: File[]
  datasetId?: string
  datasetVersionId?: string
  datasetSplit?: string
  sampleIds?: string[]
  inputFileIds?: string[]
  scoreThreshold?: number
  topK?: number
  maskThreshold?: number
  keypointConfidenceThreshold?: number
  saveResultImage?: boolean
  extraOptions?: Record<string, unknown>
}

export async function listBatchInferenceTasks(params: {
  projectId: string
  taskType?: ModelTaskType | ''
  state?: string
  q?: string
  offset?: number
  limit?: number
}): Promise<BatchInferenceTask[]> {
  return apiRequest<BatchInferenceTask[]>('/inference-batches', {
    query: {
      project_id: params.projectId,
      task_type: params.taskType || undefined,
      state: params.state || undefined,
      q: params.q || undefined,
      offset: params.offset ?? 0,
      limit: params.limit ?? 50,
    },
  })
}

export async function createBatchInferenceTask(
  input: CreateBatchInferenceTaskInput,
): Promise<BatchInferenceTask> {
  if (input.sourceKind === 'upload') {
    const form = new FormData()
    form.set('project_id', input.projectId)
    form.set('task_type', input.taskType)
    form.set('deployment_instance_id', input.deploymentInstanceId)
    form.set('runtime_mode', input.runtimeMode ?? 'auto')
    form.set('display_name', input.displayName ?? '')
    form.set('score_threshold', String(input.scoreThreshold ?? 0.3))
    form.set('top_k', String(input.topK ?? 5))
    form.set('mask_threshold', String(input.maskThreshold ?? 0.5))
    form.set('keypoint_confidence_threshold', String(input.keypointConfidenceThreshold ?? 0.3))
    form.set('save_result_image', String(input.saveResultImage ?? true))
    form.set('extra_options', JSON.stringify(input.extraOptions ?? {}))
    for (const file of input.files ?? []) {
      form.append('input_images', file)
    }
    return apiRequest<BatchInferenceTask>('/inference-batches', {
      method: 'POST',
      body: form,
    })
  }

  return apiRequest<BatchInferenceTask>('/inference-batches', {
    method: 'POST',
    body: {
      project_id: input.projectId,
      task_type: input.taskType,
      deployment_instance_id: input.deploymentInstanceId,
      runtime_mode: input.runtimeMode ?? 'auto',
      display_name: input.displayName ?? '',
      source_kind: input.sourceKind,
      dataset_id: input.datasetId ?? null,
      dataset_version_id: input.datasetVersionId ?? null,
      dataset_split: input.datasetSplit ?? '',
      sample_ids: input.sampleIds ?? [],
      input_file_ids: input.inputFileIds ?? [],
      score_threshold: input.scoreThreshold ?? 0.3,
      top_k: input.topK ?? 5,
      mask_threshold: input.maskThreshold ?? 0.5,
      keypoint_confidence_threshold: input.keypointConfidenceThreshold ?? 0.3,
      save_result_image: input.saveResultImage ?? true,
      extra_options: input.extraOptions ?? {},
    },
  })
}

export async function getBatchInferenceTask(batchTaskId: string): Promise<BatchInferenceTask> {
  return apiRequest<BatchInferenceTask>(`/inference-batches/${encodeURIComponent(batchTaskId)}`)
}

export async function listBatchInferenceTaskItems(
  batchTaskId: string,
  params: { state?: string; q?: string; offset?: number; limit?: number } = {},
): Promise<BatchInferenceTaskItem[]> {
  return apiRequest<BatchInferenceTaskItem[]>(
    `/inference-batches/${encodeURIComponent(batchTaskId)}/items`,
    {
      query: {
        state: params.state || undefined,
        q: params.q || undefined,
        offset: params.offset ?? 0,
        limit: params.limit ?? 50,
      },
    },
  )
}

export async function getBatchInferenceTaskItemResult(
  batchTaskId: string,
  itemId: string,
): Promise<BatchInferenceTaskItemResult> {
  return apiRequest<BatchInferenceTaskItemResult>(
    `/inference-batches/${encodeURIComponent(batchTaskId)}/items/${encodeURIComponent(itemId)}/result`,
  )
}

export async function fetchBatchInferenceTaskItemImageBlob(
  batchTaskId: string,
  itemId: string,
  kind: 'input' | 'preview' = 'input',
): Promise<Blob> {
  return apiRequest<Blob>(
    `/inference-batches/${encodeURIComponent(batchTaskId)}/items/${encodeURIComponent(itemId)}/image`,
    {
      query: { kind },
      responseType: 'blob',
    },
  )
}

export async function fetchDirectInferenceRecordImageBlob(
  recordId: string,
  kind: 'input' | 'preview' = 'input',
): Promise<Blob> {
  return apiRequest<Blob>(
    `/inference-records/${encodeURIComponent(recordId)}/image`,
    {
      query: { kind },
      responseType: 'blob',
    },
  )
}

export async function cancelBatchInferenceTask(batchTaskId: string): Promise<BatchInferenceTask> {
  return apiRequest<BatchInferenceTask>(
    `/inference-batches/${encodeURIComponent(batchTaskId)}/cancel`,
    { method: 'POST' },
  )
}

export async function deleteBatchInferenceTask(batchTaskId: string): Promise<void> {
  await apiRequest<void>(`/inference-batches/${encodeURIComponent(batchTaskId)}`, {
    method: 'DELETE',
  })
}
