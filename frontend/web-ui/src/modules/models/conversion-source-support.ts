import type { PlatformBaseModelVersionSummary } from './services/model.service'

export type ConversionSourceIssue = 'checkpointMissing' | 'labelsMissing' | 'labelsInvalid' | null

export function conversionSourceIssue(version: PlatformBaseModelVersionSummary): ConversionSourceIssue {
  if (!version.checkpoint_file_id?.trim() || !version.checkpoint_storage_uri?.trim()) return 'checkpointMissing'
  const names = version.metadata.category_names
  if (names !== undefined) {
    if (
      !Array.isArray(names) || names.length === 0
      || names.some((name) => typeof name !== 'string' || !name.trim() || /[\n\r\v\f\u001c-\u001e\u0085\u2028\u2029]/u.test(name))
      || new Set(names.map((name: string) => name.trim())).size !== names.length
    ) return 'labelsInvalid'
  }
  const hasLabelFile = Boolean(version.labels_file_id?.trim() && version.labels_storage_uri?.trim())
  if (!hasLabelFile && names === undefined) return 'labelsMissing'
  return null
}
