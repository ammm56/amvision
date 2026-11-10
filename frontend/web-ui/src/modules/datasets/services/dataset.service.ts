import { apiRequest } from '@/shared/api/http-client'

export interface DatasetVersionRelation {
  version_number: number
  dataset_version_id: string
  dataset_id: string
  project_id: string
  task_type: string
  sample_count: number
  category_count: number
  split_names: string[]
  metadata: Record<string, unknown>
}

export interface DatasetImportSummary {
  display_name?: string
  version_number?: number | null
  source_file_name?: string | null
  sample_count?: number | null
  category_count?: number | null
  dataset_import_id: string
  task_id?: string | null
  dataset_id: string
  project_id: string
  format_type?: string | null
  task_type: string
  status: string
  created_at: string
  dataset_version_id?: string | null
  package_path: string
  staging_path: string
  version_path?: string | null
  package_size?: number | null
  upload_state?: string | null
  processing_state: string
  queue_task_id?: string | null
  validation_status?: string | null
  error_message?: string | null
}

export interface DatasetImportDetail extends DatasetImportSummary {
  image_root?: string | null
  annotation_root?: string | null
  manifest_file?: string | null
  split_strategy?: string | null
  class_map: Record<string, string>
  detected_profile: Record<string, unknown>
  validation_report: Record<string, unknown>
  metadata: Record<string, unknown>
  dataset_version?: DatasetVersionRelation | null
}

export interface DatasetImportSubmissionResponse {
  dataset_import_id: string
  task_id?: string | null
  status: string
  upload_state: string
  processing_state: string
  package_size: number
  package_path: string
  staging_path: string
  queue_name: string
  queue_task_id: string
}

export interface DatasetImportInput {
  projectId: string
  datasetId: string
  packageFile?: File
  draftId?: string
  formatType?: string
  taskType: string
  splitRatios?: number[]
  splitSeed?: number
  splitStrategy?: string
  classMapJson?: string
  displayName?: string
  description?: string
  baseVersionId?: string
  expectedContentRevision?: string
  excludeSelection?: DatasetSampleSelection
}

export interface DatasetExportFormatCatalog {
  implemented_formats: string[]
  default_format: string
  format_types_by_task_type: Record<string, string[]>
  items: Array<{ format_id: string }>
}

export interface DatasetExportSummary {
  display_name?: string
  version_number?: number | null
  dataset_export_id: string
  task_id?: string | null
  dataset_id: string
  project_id: string
  dataset_version_id: string
  format_id: string
  task_type: string
  status: string
  created_at: string
  include_test_split: boolean
  export_path?: string | null
  manifest_object_key?: string | null
  split_names: string[]
  sample_count: number
  category_names: string[]
  queue_task_id?: string | null
  package_object_key?: string | null
  package_file_name?: string | null
  package_size?: number | null
  packaged_at?: string | null
  error_message?: string | null
  metadata: Record<string, unknown>
}

export interface DatasetExportDetail extends DatasetExportSummary {}

export interface DatasetExportSubmissionResponse {
  dataset_export_id: string
  task_id: string
  status: string
  dataset_version_id: string
  format_id: string
  queue_name: string
  queue_task_id: string
}

export interface DatasetExportInput {
  projectId: string
  datasetId: string
  datasetVersionId: string
  formatId: string
  displayName?: string
  includedSplits?: string[]
  sourceCategoryIds?: number[]
  packageName?: string
  categoryNames?: string[]
  includeTestSplit: boolean
  selection?: DatasetSampleSelection
  annotationHandoff?: boolean
}

export interface DatasetSampleSelection {
  mode: 'ids' | 'filter'
  sample_ids?: string[]
  q?: string
  split?: string
  category_id?: number
  annotation_state?: string
}

export interface DatasetExportPackageResponse {
  dataset_export_id: string
  export_path: string
  manifest_object_key: string
  package_object_key: string
  package_file_name: string
  package_size: number
  packaged_at: string
}

export async function submitDatasetImport(input: DatasetImportInput): Promise<DatasetImportSubmissionResponse> {
  const formData = new FormData()
  formData.set('project_id', input.projectId)
  formData.set('dataset_id', input.datasetId)
  if (input.packageFile) formData.set('package', input.packageFile)
  if (input.draftId) formData.set('draft_id', input.draftId)
  formData.set('task_type', input.taskType)
  if (input.displayName) formData.set('dataset_display_name', input.displayName)
  if (input.description) formData.set('dataset_description', input.description)
  if (input.formatType) formData.set('format_type', input.formatType)
  input.splitRatios?.forEach(n=>formData.append('split_ratios',String(n)))
  if(input.splitSeed!==undefined) formData.set('split_seed',String(input.splitSeed))
  if (input.splitStrategy) formData.set('split_strategy', input.splitStrategy)
  if (input.classMapJson?.trim()) formData.set('class_map_json', input.classMapJson.trim())
  if (input.baseVersionId) formData.set('base_version_id', input.baseVersionId)
  if (input.expectedContentRevision !== undefined) formData.set('expected_content_revision', input.expectedContentRevision)
  if (input.excludeSelection) formData.set('exclude_selection_json', JSON.stringify(input.excludeSelection))
  return apiRequest<DatasetImportSubmissionResponse>('/datasets/imports', { method: 'POST', body: formData })
}

export async function listDatasetImports(datasetId: string): Promise<DatasetImportSummary[]> {
  return apiRequest<DatasetImportSummary[]>(`/datasets/${encodeURIComponent(datasetId)}/imports`)
}

export async function listProjectDatasetImports(projectId: string): Promise<DatasetImportSummary[]> {
  return apiRequest<DatasetImportSummary[]>('/datasets/imports', { query: { project_id: projectId } })
}

export async function getDatasetImportDetail(datasetImportId: string): Promise<DatasetImportDetail> {
  return apiRequest<DatasetImportDetail>(`/datasets/imports/${encodeURIComponent(datasetImportId)}`)
}

export async function deleteDatasetImport(datasetImportId: string): Promise<void> {
  await apiRequest<void>(`/datasets/imports/${encodeURIComponent(datasetImportId)}`, { method: 'DELETE' })
}

export async function getDatasetVersionRelation(datasetId: string, datasetVersionId: string): Promise<DatasetVersionRelation> {
  return apiRequest<DatasetVersionRelation>(
    `/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(datasetVersionId)}`,
  )
}

export async function listProjectDatasetVersions(projectId: string): Promise<DatasetVersionRelation[]> {
  return apiRequest<DatasetVersionRelation[]>('/datasets/versions', { query: { project_id: projectId } })
}

export async function getDatasetExportFormats(): Promise<DatasetExportFormatCatalog> {
  return apiRequest<DatasetExportFormatCatalog>('/datasets/export-formats')
}

export async function createDatasetExport(input: DatasetExportInput): Promise<DatasetExportSubmissionResponse> {
  return apiRequest<DatasetExportSubmissionResponse>('/datasets/exports', {
    method: 'POST',
    body: {
      project_id: input.projectId,
      dataset_id: input.datasetId,
      dataset_version_id: input.datasetVersionId,
      format_id: input.formatId,
      display_name: input.displayName ?? '',
      category_names: input.categoryNames ?? [],
      included_splits:input.includedSplits, source_category_ids:input.sourceCategoryIds, package_name:input.packageName || '',
      include_test_split: input.includeTestSplit,
      selection: input.selection,
      annotation_handoff: input.annotationHandoff ?? false,
    },
  })
}

export async function listDatasetExports(datasetId: string, datasetVersionId: string): Promise<DatasetExportSummary[]> {
  return apiRequest<DatasetExportSummary[]>(
    `/datasets/${encodeURIComponent(datasetId)}/versions/${encodeURIComponent(datasetVersionId)}/exports`,
  )
}

export async function listProjectDatasetExports(
  projectId: string,
  taskType?: string,
  status?: string,
): Promise<DatasetExportSummary[]> {
  return apiRequest<DatasetExportSummary[]>('/datasets/exports', {
    query: {
      project_id: projectId,
      task_type: taskType || undefined,
      status: status || undefined,
      limit: 200,
    },
  })
}

export async function getDatasetExportDetail(datasetExportId: string): Promise<DatasetExportDetail> {
  return apiRequest<DatasetExportDetail>(`/datasets/exports/${encodeURIComponent(datasetExportId)}`)
}

export async function packageDatasetExport(datasetExportId: string): Promise<DatasetExportPackageResponse> {
  return apiRequest<DatasetExportPackageResponse>(`/datasets/exports/${encodeURIComponent(datasetExportId)}/package`, {
    method: 'POST',
  })
}

export async function downloadDatasetExport(datasetExportId: string): Promise<Blob> {
  return apiRequest<Blob>(`/datasets/exports/${encodeURIComponent(datasetExportId)}/download`, { responseType: 'blob' })
}

export async function deleteDatasetExport(datasetExportId: string): Promise<void> {
  await apiRequest<void>(`/datasets/exports/${encodeURIComponent(datasetExportId)}`, { method: 'DELETE' })
}
