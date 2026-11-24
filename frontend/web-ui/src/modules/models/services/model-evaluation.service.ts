import { apiRequest } from '@/shared/api/http-client'

export interface EvaluationCoverage {
  requested: number
  succeeded: number
  failed: number
  unprocessed: number
}

export interface FailedDetectionSample {
  image_index: number
  name: string
  reason: 'missing_image' | 'unreadable_image' | 'invalid_annotation'
  classes: string[]
}

export interface ProcessedDetectionSample {
  image_index: number
  name: string
  classes: string[]
  status: 'succeeded' | 'failed'
  processed_at: string
}

export interface DetectionEvaluationTask {
  task_id: string
  display_name: string
  project_id: string
  model_type: string
  model_version_id: string
  dataset_export_id?: string
  dataset_version_id?: string
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  state: string
  error_message?: string
  map50?: number | null
  map50_95?: number | null
  split_name?: string | null
  report_object_key?: string
  dataset_export_manifest_key?: string
  progress: {
    percent?: number; stage?: string; split_name?: string; coverage?: EvaluationCoverage | null
    recent_samples?: ProcessedDetectionSample[]; runtime_backend?: string; runtime_precision?: string
  }
  report_summary: { split_name?: string; sample_count?: number; coverage?: EvaluationCoverage }
  score_threshold?: number | null
  nms_threshold?: number | null
  save_result_package?: boolean
  task_spec?: { extra_options?: { split?: string } }
  events?: Array<{ event_id: string; message: string; created_at: string }>
}

export interface DetectionEvaluationReport {
  file_status: 'pending' | 'ready'
  payload: {
    split_name?: string
    sample_count?: number
    coverage?: EvaluationCoverage
    failed_samples?: FailedDetectionSample[]
    ground_truth_count?: number
    prediction_count?: number
    samples_with_false_negatives?: number
    samples_with_false_positives?: number
    map50?: number
    map50_95?: number
    mean_precision?: number
    mean_recall?: number
    mean_f1?: number
    duration_seconds?: number
    score_threshold?: number
    nms_threshold?: number | null
    execution?: {
      model_name?: string
      runtime_backend?: string
      runtime_precision?: string
      device_name?: string
      batch_size?: number
      runtime_artifact_file_id?: string
      input_size?: { width: number; height: number }
      model_input_spec?: Record<string, unknown> | null
    }
    curves?: DetectionEvaluationCurves
    per_class_metrics?: Array<{
      class_id: number; class_name: string; gt_count: number; pred_count: number
      ap50: number; ap50_95: number; precision: number; recall: number; f1: number
    }>
  }
}

export interface DetectionEvaluationCurves {
  iou_threshold: number
  working_point: number
  score_floor: number
  confidence: number[]
  series: Array<{ class_id: number; class_name: string; precision_recall: number[]; f1_confidence: number[] }>
  labels: Array<{ id: number; name: string }>
  confusion: Array<{ actual: number | null; predicted: number | null; count: number }>
}

export function downloadEvaluationJson(fileName: string, content: object): void {
  const url = URL.createObjectURL(new Blob([JSON.stringify(content, null, 2)], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export interface EvaluationBox {
  class_name: string
  bbox_xyxy: [number, number, number, number]
  score?: number
  matched: boolean
}

export interface DetectionEvaluationSample {
  image_index: number
  name: string
  gt_count: number
  pred_count: number
  ground_truth?: EvaluationBox[]
  predictions?: EvaluationBox[]
  false_negatives?: number
  false_positives?: number
  localization_pair?: { ground_truth_index: number; prediction_index: number; iou: number }
}

export type EvaluationIssue = 'all' | 'errors' | 'false_negatives' | 'false_positives' | 'localization'
const path = '/models/detection/evaluation-tasks'
const taskPath = (id: string) => `${path}/${encodeURIComponent(id)}`

export async function listDetectionEvaluations(projectId: string, signal?: AbortSignal): Promise<DetectionEvaluationTask[]> {
  const tasks: DetectionEvaluationTask[] = []
  const limit = 100
  for (let offset = 0; ; offset += limit) {
    const page = await apiRequest<DetectionEvaluationTask[]>(path, { query: { project_id: projectId, limit, offset }, signal })
    tasks.push(...page)
    if (page.length < limit) return tasks
  }
}

export interface DetectionEvaluationInput {
  project_id: string; model_type: string; model_version_id: string; dataset_export_id: string;
  score_threshold: number; nms_threshold?: number; extra_options: { split: 'val' | 'test' }; display_name: string
  save_result_package?: boolean
}

export interface DetectionEvaluationPreview {
  dataset_version_id: string
  split: string
  sample_count: number | null
  annotation_count?: number | null
  category_names: string[]
  input_size: [number, number]
  runtime_backend: string
  runtime_precision?: string
  device_name: string
}

export function previewDetectionEvaluation(body: DetectionEvaluationInput, signal?: AbortSignal): Promise<DetectionEvaluationPreview> {
  return apiRequest(`${path}/preview`, { method: 'POST', body, signal })
}

export function createDetectionEvaluation(body: DetectionEvaluationInput): Promise<{ task_id: string }> {
  return apiRequest(path, { method: 'POST', body })
}

export function getDetectionEvaluation(id: string, signal?: AbortSignal): Promise<DetectionEvaluationTask> {
  return apiRequest(taskPath(id), { query: { include_events: true }, signal })
}

export function getDetectionEvaluationReport(id: string, signal?: AbortSignal): Promise<DetectionEvaluationReport> {
  return apiRequest(`${taskPath(id)}/report`, { signal })
}

export const detectionEvaluationSamplePageSize = 12

export function listDetectionEvaluationSamples(
  id: string,
  filter: { issue: EvaluationIssue; offset: number; q: string; class_name: string; limit?: number },
  signal?: AbortSignal,
): Promise<{ items: DetectionEvaluationSample[]; total: number; diagnostics_available: boolean }> {
  return apiRequest(`${taskPath(id)}/samples`, { query: { limit: detectionEvaluationSamplePageSize, ...filter }, signal })
}

export function fetchDetectionEvaluationImage(id: string, index: number, signal?: AbortSignal): Promise<Blob> {
  return apiRequest(`${taskPath(id)}/samples/${index}/image`, { responseType: 'blob', signal })
}

export const additionalEvaluationKinds = ['classification', 'segmentation', 'pose', 'obb', 'semantic', 'anomaly'] as const
export type AdditionalEvaluationKind = typeof additionalEvaluationKinds[number]
export type DenseEvaluationKind = 'semantic' | 'anomaly'
export function isDenseEvaluation(kind: AdditionalEvaluationKind): kind is DenseEvaluationKind {
  return kind === 'semantic' || kind === 'anomaly'
}

export interface ModelEvaluationRecord {
  task_id: string
  display_name: string
  project_id: string
  state: string
  created_at: string
  finished_at?: string
  error_message?: string
  progress?: { percent?: number }
  sample_count?: number | null
  model_version_id?: string | null
  dataset_export_id?: string | null
  uses_default_name?: boolean | null
  metadata?: { model_version_id?: string; dataset_version_id?: string; dataset_export_id?: string }
  result?: { report_summary?: { split_name?: string }; report_object_key?: string; model_version_id?: string; dataset_export_id?: string; dataset_version_id?: string }
  top1_accuracy?: number | null
  map50_95?: number | null
  mask_map50_95?: number | null
  oks_ap50_95?: number | null
  miou?: number | null
  image_auroc?: number | null
}

export interface ModelEvaluationReport {
  sample_count?: number
  split_name?: string
  duration_seconds?: number
  top1_accuracy?: number
  top5_accuracy?: number
  bbox_map50?: number
  bbox_map50_95?: number
  map50?: number
  map50_95?: number
  mask_map50?: number
  mask_map50_95?: number
  oks_ap50?: number
  oks_ap50_95?: number
  keypoint_count?: number
  keypoint_definitions?: Array<{ id: number; name: string; keypoints: string[]; skeleton: [number, number][] }>
  iou_thresholds?: number[]
  evaluation_policy?: { version?: string; oks_sigmas?: number[]; score_threshold?: number; nms_threshold?: number }
  confusion_matrix?: { labels: Array<string | null>; rows: number[][] }
  per_class_metrics?: Array<{
    class_id?: number
    category_id?: number
    class_name?: string
    category_name?: string
    sample_count?: number
    correct_count?: number
    accuracy?: number
    ap50?: number
    ap50_95?: number
    bbox_ap50_95?: number
    mask_ap50_95?: number
  }>
}

export interface EvaluationGeometry {
  category_id?: number
  keypoints?: number[]
  polygon?: number[] | number[][]
}

export interface ModelEvaluationSample {
  index: number
  name: string
  ground_truth_class_name?: string
  predicted_top_k?: Array<{ class_name: string; probability: number }>
  top1_correct?: boolean
  mask_available?: boolean
  ground_truth?: EvaluationGeometry[]
  predictions?: EvaluationGeometry[]
  errors?: Partial<Record<GeometryIssue, number>>
}

export type GeometryIssue = 'all' | 'errors' | 'keypoints' | 'angle' | 'localization' | 'missed' | 'extra'

const additionalPath = (kind: AdditionalEvaluationKind) => `/models/${kind}/evaluation-tasks`
const additionalTaskPath = (kind: AdditionalEvaluationKind, id: string) => `${additionalPath(kind)}/${encodeURIComponent(id)}`

export function createDenseEvaluation(kind: DenseEvaluationKind, projectId: string, name: string, threshold: number, file: File): Promise<{ task_id: string }> {
  const body = new FormData()
  body.append('project_id', projectId)
  body.append('display_name', name)
  body.append('threshold', String(threshold))
  body.append('file', file)
  return apiRequest(additionalPath(kind), { method: 'POST', body })
}

export interface DenseEvaluationReport {
  source_model: string
  source_dataset: string
  split_name: string
  sample_count: number
  duration_seconds: number
  input_sha256: string
  miou?: number | null
  background_index?: number
  ignore_index?: number
  valid_pixels?: number
  classes?: { name: string; iou: number | null; included: boolean; color: [number, number, number] }[]
  image_auroc?: number | null
  pixel_auroc?: number | null
  normal_count?: number
  anomaly_count?: number
  pixel_sample_count?: number
  pixel_normal_count?: number
  pixel_anomaly_count?: number
  threshold?: number
  score_distribution?: number[][]
}

export interface DenseEvaluationSample {
  index: number
  name: string
  has_truth: boolean
  has_prediction: boolean
  label?: 'normal' | 'anomaly'
  label_index?: number
  predicted_label?: 'normal' | 'anomaly'
  score?: number
  different_pixels?: number
  valid_pixels?: number
  pixel_annotated?: boolean
}

export type DenseSampleFilter = 'all' | 'normal' | 'anomaly' | 'errors'
export type DenseSampleLayer = 'original' | 'truth' | 'prediction'

export function getDenseReport(kind: DenseEvaluationKind, id: string, signal: AbortSignal): Promise<{ file_status: string; payload: DenseEvaluationReport }> {
  return apiRequest(`${additionalTaskPath(kind, id)}/report`, { signal })
}

export function listDenseSamples(kind: DenseEvaluationKind, id: string, offset: number, filter: DenseSampleFilter, signal: AbortSignal, limit = 1): Promise<{ items: DenseEvaluationSample[]; total: number }> {
  return apiRequest(`${additionalTaskPath(kind, id)}/samples`, { query: { offset, limit, sample_filter: filter }, signal })
}

export function fetchDenseLayer(kind: DenseEvaluationKind, id: string, index: number, layer: DenseSampleLayer, signal: AbortSignal): Promise<Blob> {
  return apiRequest(`${additionalTaskPath(kind, id)}/samples/${index}/image`, { query: { layer }, responseType: 'blob', signal })
}

export function listModelEvaluations(kind: AdditionalEvaluationKind, projectId: string, signal: AbortSignal): Promise<ModelEvaluationRecord[]> {
  return apiRequest(additionalPath(kind), { query: { project_id: projectId, limit: 100 }, signal })
}

export function createModelEvaluation(kind: AdditionalEvaluationKind, body: {
  project_id: string; model_version_id: string; dataset_export_id: string; display_name: string
}): Promise<{ task_id: string }> {
  return apiRequest(additionalPath(kind), { method: 'POST', body })
}

export function getModelEvaluation(kind: AdditionalEvaluationKind, id: string, signal: AbortSignal): Promise<ModelEvaluationRecord> {
  return apiRequest(additionalTaskPath(kind, id), { signal })
}

export function getModelEvaluationReport(kind: AdditionalEvaluationKind, id: string, signal: AbortSignal): Promise<{ file_status: string; payload: ModelEvaluationReport }> {
  return apiRequest(`${additionalTaskPath(kind, id)}/report`, { signal })
}

export function listModelEvaluationSamples(kind: AdditionalEvaluationKind, id: string, offset: number, limit: number, issue: GeometryIssue, signal: AbortSignal): Promise<{ items: ModelEvaluationSample[]; total: number; available: boolean; issue_counts?: Partial<Record<GeometryIssue, number>> }> {
  return apiRequest(`${additionalTaskPath(kind, id)}/samples`, { query: { offset, limit, issue, errors_only: kind === 'classification' }, signal })
}

export function fetchModelEvaluationImage(kind: AdditionalEvaluationKind, id: string, index: number, signal: AbortSignal): Promise<Blob> {
  return apiRequest(`${additionalTaskPath(kind, id)}/samples/${index}/image`, { responseType: 'blob', signal })
}

export function fetchSegmentationEvaluationOverlay(id: string, index: number, layer: 'combined' | 'difference', signal: AbortSignal): Promise<Blob | undefined> {
  return apiRequest(`${additionalTaskPath('segmentation', id)}/samples/${index}/mask-overlay`, { query: { layer }, responseType: 'blob', signal })
}
