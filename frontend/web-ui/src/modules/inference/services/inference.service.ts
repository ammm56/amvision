import { apiRequest } from '@/shared/api/http-client'
import type { ModelTaskType } from '@/modules/deployments/services/deployment.service'

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
}

export interface TaskInferenceTaskListInput {
  taskType: ModelTaskType
  projectId: string
  deploymentInstanceId?: string
  limit?: number
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
  return apiRequest<TaskInferencePayload>(
    buildDeploymentInferencePath(input.taskType, input.deploymentInstanceId),
    { method: 'POST', body: buildInferenceFormData(input, false) },
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

