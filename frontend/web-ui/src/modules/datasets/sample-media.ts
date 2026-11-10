import { apiRequest } from '@/shared/api/http-client'
import {
  datasetVersionPath,
  type DatasetSample,
} from './services/dataset-workspace.service'

export const mediaTasks = [
  'anomaly',
  'connector-reference',
  'rgbd',
  'point-cloud',
] as const
export type MediaKind = (typeof mediaTasks)[number]
export function isMediaTask(task?: string): task is MediaKind {
  return mediaTasks.some((kind) => kind === task)
}
export interface SampleMedia {
  kind: MediaKind
  id: string
  source?: string
  assets: string[]
  label?: 'normal' | 'anomaly'
  defect?: string
  pins?: { id: string; x: number; y: number }[]
  measured?: { name: string; value: number; unit: string; source: string }[]
  unit?: string
  pitch?: number
  plane?: string
  synthetic?: boolean
  calibration_name?: string
  scale?: number
  invalid?: number
  alignment?: string
  depth_size?: [number, number]
  depth_range?: [number, number]
  z_range?: [number, number]
  frame?: string
  point_count?: number
  valid_count?: number
  invalid_count?: number
  preview_count?: number
  has_color?: boolean
  origin?: [number, number, number]
}
export function sampleMedia(
  sample?: DatasetSample | null,
): SampleMedia | undefined {
  const value = sample?.metadata?.sample_media as SampleMedia | undefined
  return value && isMediaTask(value.kind) ? value : undefined
}
export function readSampleAsset(
  dataset: string,
  sample: DatasetSample,
  asset: string,
  signal: AbortSignal,
) {
  return apiRequest<Blob>(
    datasetVersionPath(dataset, sample.dataset_version_id) +
      '/samples/' +
      encodeURIComponent(sample.sample_id) +
      '/image',
    { query: { asset }, responseType: 'blob', signal },
  )
}
