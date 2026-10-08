import { apiRequest } from '@/shared/api/http-client'

export interface MeasurementResourceReference {
  project_id: string
  resource_id: string
  version: number
  sha256: string
  kind: 'planar-calibration' | 'localization-template'
}
export interface MeasurementResourceDocument {
  reference: MeasurementResourceReference
  name: string
  content: {
    kind: MeasurementResourceReference['kind']
    calibration: Record<string, unknown> | null
    template: { reference_id: string; image_width: number; image_height: number; template_roi: [number, number, number, number]; anchor: [number, number]; image_sha256: string } | null
  }
  created_at: string
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
