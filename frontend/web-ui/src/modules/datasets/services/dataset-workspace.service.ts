import { apiRequest } from '@/shared/api/http-client'
import type { DatasetSampleSelection } from './dataset.service'
export function getDatasetSelectionSummary(
  dataset: string,
  version: string,
  selection: DatasetSampleSelection,
  signal?: AbortSignal,
) {
  return apiRequest<{
    sample_count: number
    split_counts: Record<string, number>
  }>(`${datasetVersionPath(dataset, version)}/selection-summary`, {
    method: 'POST',
    body: selection,
    signal,
  })
}
export function getDatasetSample(
  dataset: string,
  version: string,
  sample: string,
) {
  return apiRequest<DatasetSample>(
    `${datasetVersionPath(dataset, version)}/samples/${encodeURIComponent(sample)}`,
  )
}
export interface DatasetJob {
  task_id: string
  operation:
    | 'quality'
    | 'derive-check'
    | 'derive'
    | 'revise'
    | 'compare'
    | 'return-check'
    | 'return-apply'
  content_revision?: string | null
  config?: Record<string, any>
  state: string
  created_at: string
  finished_at: string | null
  error_message: string | null
  progress: { percent?: number }
  result?: Record<string, any>
}
export function listDatasetJobs(
  dataset: string,
  version: string,
  offset = 0,
  options: { operation?: "quality"; limit?: number; signal?: AbortSignal } = {},
) {
  return apiRequest<DatasetPage<DatasetJob>>(
    `${datasetVersionPath(dataset, version)}/jobs`,
    { query: { offset, limit: options.limit ?? 20, operation: options.operation }, signal: options.signal },
  )
}
export function getDatasetJob(
  dataset: string,
  version: string,
  task: string,
  signal?: AbortSignal,
) {
  return apiRequest<DatasetJob>(
    `${datasetVersionPath(dataset, version)}/jobs/${encodeURIComponent(task)}`,
    { signal },
  )
}
export function findDatasetJob(
  dataset: string,
  version: string,
  request: string,
) {
  return apiRequest<DatasetJob>(
    `${datasetVersionPath(dataset, version)}/job-requests/${encodeURIComponent(request)}`,
  )
}
export function submitDatasetJob(
  dataset: string,
  version: string,
  body: Record<string, unknown>,
) {
  return apiRequest<{ task_id: string; state: string }>(
    `${datasetVersionPath(dataset, version)}/jobs`,
    { method: 'POST', body },
  )
}
export function cancelDatasetJob(
  dataset: string,
  version: string,
  task: string,
) {
  return apiRequest(
    `${datasetVersionPath(dataset, version)}/jobs/${encodeURIComponent(task)}/cancel`,
    { method: 'POST' },
  )
}
import type {
  DatasetImportSummary,
  DatasetExportSummary,
} from './dataset.service'
export interface DatasetInfo {
  project_id: string
  dataset_id: string
  display_name: string
  description: string
  task_type: string
  created_at: string
  updated_at: string
  revision: string
}
export interface DatasetVersion {
  task_references?: { training: number; evaluation: number }
  availability?: {
    state: 'available' | 'missing' | 'unavailable' | 'updating' | 'empty'
    reason: string
    checked_at: string
    scope: 'version_resources'
  }
  version_number: number
  display_name: string
  dataset_version_id: string
  dataset_id: string
  project_id: string
  task_type: string
  created_at: string | null
  sample_count: number
  category_count: number
  object_count: number
  split_counts: Record<string, number>
  metadata: Record<string, unknown>
}
export interface DatasetItem extends DatasetInfo {
  latest_version: DatasetVersion | null
}
export interface DatasetWorkspace extends DatasetVersion {
  split_object_counts?: Record<string, number>
  parent_version_number: number | null
  dataset: DatasetInfo
  categories: { category_id: number; name: string }[]
}
export interface DatasetAnnotation {
  annotation_id: string
  annotation_type: string
  category_id: number | null
  bbox_xywh: number[] | null
  segmentation: number[][] | Record<string, unknown> | null
  keypoints: number[] | null
  polygon_xy: number[] | null
  is_anomalous: boolean | null
  metadata: Record<string, unknown>
}
export interface DatasetSample {
  sample_id: string
  image_id: number
  dataset_version_id: string
  file_name: string
  width: number
  height: number
  split: string
  annotations: DatasetAnnotation[]
  metadata: Record<string, unknown>
}
export interface DatasetPage<T> {
  items: T[]
  total: number
  offset: number
  limit: number
}
export type DatasetQuery = Record<string, string | number | undefined>
export function listDatasetCatalog(
  query: DatasetQuery,
  signal?: AbortSignal,
) {
  return apiRequest<DatasetPage<DatasetItem>>('/datasets/catalog', {
    query,
    signal,
  })
}
export function listDatasetVersionPage(
  query: DatasetQuery,
  signal?: AbortSignal,
) {
  return apiRequest<DatasetPage<DatasetVersion>>(
    '/datasets/catalog/versions',
    {
      query,
      signal,
    },
  )
}
export function listDatasetRecordPage(
  kind: 'imports' | 'exports',
  query: DatasetQuery,
  signal?: AbortSignal,
) {
  return apiRequest<DatasetPage<DatasetImportSummary | DatasetExportSummary>>(
    `/datasets/catalog/records/${kind}`,
    { query, signal },
  )
}
export function getDatasetInfo(projectId: string, datasetId: string) {
  return apiRequest<DatasetInfo>(
    `/datasets/catalog/${encodeURIComponent(datasetId)}`,
    { query: { project_id: projectId } },
  )
}
export function editDatasetInfo(
  info: DatasetInfo,
  values: { display_name: string; description: string },
) {
  return apiRequest<DatasetInfo>(
    `/datasets/catalog/${encodeURIComponent(info.dataset_id)}`,
    {
      method: 'PATCH',
      query: { project_id: info.project_id },
      body: { ...values, revision: info.revision },
    },
  )
}
export function datasetVersionPath(datasetId: string, versionId: string) {
  return `/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(versionId)}`
}
export function getDatasetWorkspace(
  datasetId: string,
  versionId: string,
  signal?: AbortSignal,
) {
  return apiRequest<DatasetWorkspace>(
    `${datasetVersionPath(datasetId, versionId)}/workspace`,
    { signal },
  )
}
export function listDatasetSamples(
  datasetId: string,
  versionId: string,
  query: DatasetQuery,
  signal?: AbortSignal,
) {
  return apiRequest<DatasetPage<DatasetSample>>(
    `${datasetVersionPath(datasetId, versionId)}/samples`,
    { query, signal },
  )
}
export function getDatasetImage(
  datasetId: string,
  versionId: string,
  sampleId: string,
  thumbnail = true,
  signal?: AbortSignal,
) {
  return apiRequest<Blob>(
    `${datasetVersionPath(datasetId, versionId)}/samples/${encodeURIComponent(sampleId)}/image`,
    { query: { thumbnail }, responseType: 'blob', signal },
  )
}
export interface CategoryStatistic {
  category_id: number
  name: string
  sample_count: number
  object_count: number
  split_objects: Record<string, number>
}
export interface DatasetFile {
  has_directories?: boolean | null
  has_children?: boolean | null
  name: string
  path: string
  directory: boolean
  size: number | null
}
export interface VersionTaskReference {
  task_id: string
  task_kind: string
  display_name: string
  created_at: string
}
export function listVersionTaskReferences(datasetId:string, versionId:string, offset:number, signal?:AbortSignal) {
  return apiRequest<{ items:VersionTaskReference[]; has_more:boolean }>(
    `${datasetVersionPath(datasetId,versionId)}/task-references`, { query:{offset,limit:20},signal },
  )
}
export function getDatasetCategories(
  datasetId: string,
  versionId: string,
  signal?: AbortSignal,
) {
  return apiRequest<{ items: CategoryStatistic[] }>(
    `${datasetVersionPath(datasetId, versionId)}/category-statistics`,
    { signal },
  )
}
export function getDatasetReport(
  datasetId: string,
  versionId: string,
  signal?: AbortSignal,
) {
  return apiRequest<{
    available: boolean
    checked_at: string | null
    dataset_import_id?: string | null
    report: Record<string, unknown> | null
  }>(`${datasetVersionPath(datasetId, versionId)}/import-report`, { signal })
}
export function getDatasetFiles(
  datasetId: string,
  versionId: string,
  path: string,
  after = '',
  signal?: AbortSignal,
  directoriesOnly = false,
  limit = 50,
) {
  return apiRequest<{
    items: DatasetFile[]
    path: string
    next_cursor: string | null
  }>(`${datasetVersionPath(datasetId, versionId)}/files`, {
    query: { path, after, directories_only: directoriesOnly, limit },
    signal,
  })
}
export function getDatasetFileImage(
  datasetId: string,
  versionId: string,
  path: string,
  signal?: AbortSignal,
) {
  return apiRequest<Blob>(
    `${datasetVersionPath(datasetId, versionId)}/file-image`,
    { query: { path }, responseType: 'blob', signal },
  )
}
export function getDatasetTextFile(
  datasetId: string,
  versionId: string,
  path: string,
  signal?: AbortSignal,
) {
  return apiRequest<{ path: string; content: string; truncated: boolean }>(
    `${datasetVersionPath(datasetId, versionId)}/file-text`,
    { query: { path }, signal },
  )
}
