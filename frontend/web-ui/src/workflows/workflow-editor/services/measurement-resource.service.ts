import { apiRequest } from '@/shared/api/http-client'

export interface MeasurementResourceReference {
  project_id: string
  resource_id: string
  version: number
  sha256: string
  kind: 'planar-calibration' | 'localization-template' | 'point-cloud'
}
export interface MeasurementResourceDocument {
  reference: MeasurementResourceReference
  name: string
  content: {
    format_id?: 'amvision.measurement-resource.v1' | 'amvision.measurement-resource.v2'
    kind: MeasurementResourceReference['kind']
    calibration: Record<string, unknown> | null
    template: { reference_id: string; image_width: number; image_height: number; template_roi: [number, number, number, number]; anchor: [number, number]; image_sha256: string } | null
    point_cloud?: { representation: string; point_count: number; spatial: { length_unit: string | null; frame_id: string }; fields: {name: string; dtype: string; components: number}[]; [key: string]: unknown } | null
  }
  created_at: string
}
export interface CloudRendererPolicy {
  max_points: number; max_data_bytes: number; max_cpu_bytes: number; max_gpu_bytes: number
  max_canvas_pixels: number; max_position_error: number
}
export function readCloudCapabilities(project: string, signal?: AbortSignal) {
  return apiRequest<{ max_archive_bytes: number | null; renderer: CloudRendererPolicy | null }>(
    `${measurementResourceRoot(project)}/cloud/capabilities`, { signal })
}
export function importCloudResource(project: string, file: File, name: string, identity: string, signal?: AbortSignal) {
  return apiRequest<MeasurementResourceDocument>(`${measurementResourceRoot(project)}/cloud/import`, {
    method: 'POST', body: file, query: { name }, signal, retryOnUnauthorized: false,
    headers: { 'Content-Type': 'application/zip', 'Idempotency-Key': identity },
  })
}
export function deleteMeasurementResource(reference: MeasurementResourceReference, signal?: AbortSignal) {
  return apiRequest<void>(resourceVersionPath(reference), { method: 'DELETE', responseType: 'void', signal })
}
export function measurementResourceRoot(project: string): string {
  return `/workflows/projects/${encodeURIComponent(project)}/measurement-resources`
}
export function resourceVersionPath(reference: MeasurementResourceReference): string {
  return `${measurementResourceRoot(reference.project_id)}/${encodeURIComponent(reference.resource_id)}/versions/${reference.version}`
}
export function listMeasurementResources(project: string, signal?: AbortSignal) {
  return apiRequest<MeasurementResourceDocument[]>(measurementResourceRoot(project), { signal })
}
export function readMeasurementResourceImage(reference: MeasurementResourceReference, signal?: AbortSignal) {
  return apiRequest<Blob>(`${resourceVersionPath(reference)}/image`, { responseType: 'blob', signal })
}
export function readMeasurementResource(reference:MeasurementResourceReference,signal?:AbortSignal){
  return apiRequest<MeasurementResourceDocument>(resourceVersionPath(reference),{signal})
}
export function saveMeasurementResource(project: string, form: FormData, signal?: AbortSignal) {
  return apiRequest<MeasurementResourceDocument>(measurementResourceRoot(project), { method: 'POST', body: form, signal })
}
export function importMeasurementResource(project: string, form: FormData, signal?: AbortSignal) {
  return apiRequest<MeasurementResourceDocument>(`${measurementResourceRoot(project)}/import`, { method: 'POST', body: form, signal })
}
