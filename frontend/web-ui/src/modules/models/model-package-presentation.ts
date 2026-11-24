import type { ModelPackageRecord } from './services/model-package.service'

export function formatPackageBytes(bytes?: number | null): string {
  if (bytes == null) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 ** 2).toFixed(1)} MB`
}

export function packageSourceVersionLabel(record: ModelPackageRecord): string {
  const label = record.source?.source_version_label
  return label && /^v[1-9]\d*$/.test(label) ? label : ''
}
