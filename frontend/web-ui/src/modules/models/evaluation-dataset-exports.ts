import { datasetFormatLabel } from '@/modules/datasets/dataset-workspace'
import type { DatasetExportSummary } from '@/modules/datasets/services/dataset.service'
import { listDatasetVersionPage, type DatasetVersion } from '@/modules/datasets/services/dataset-workspace.service'
import { formatSystemDateTime } from '@/shared/formatters/date-time'

export type EvaluationDatasetVersion = Pick<DatasetVersion, 'display_name' | 'version_number'>

export async function readEvaluationDatasetVersionNames(
  projectId: string, taskType: string, ids: readonly string[], signal: AbortSignal,
): Promise<Map<string, string>> {
  const missing = new Set(ids.filter(Boolean))
  const names = new Map<string, string>()
  const limit = 100
  for (let offset = 0; missing.size && !signal.aborted; offset += limit) {
    const page = await listDatasetVersionPage({ project_id: projectId, task_type: taskType, offset, limit }, signal)
    if (signal.aborted) break
    for (const version of page.items) {
      if (missing.delete(version.dataset_version_id)) names.set(version.dataset_version_id, `${version.display_name} · v${version.version_number}`)
    }
    if (!page.items.length || offset + limit >= page.total) break
  }
  return names
}

export function isEligibleEvaluationExport(item: DatasetExportSummary, formats: readonly string[]): boolean {
  return formats.includes(item.format_id) && !item.metadata.files_cleaned_at
    && item.split_names.some(split => split === 'val' || split === 'test')
}

export function evaluationDatasetExportOptions(
  exports: readonly DatasetExportSummary[],
  versions: ReadonlyMap<string, EvaluationDatasetVersion>,
  zh: boolean,
) {
  const versionCounts = new Map<string, number>()
  for (const item of exports) versionCounts.set(item.dataset_version_id, (versionCounts.get(item.dataset_version_id) ?? 0) + 1)

  const byLabel = new Map<string, string[]>()
  const options = exports.map(item => {
    const identity = versions.get(item.dataset_version_id)
    const name = identity?.display_name.trim() || item.display_name?.trim() || (zh ? '数据集名称暂不可用' : 'Dataset name unavailable')
    const version = identity?.version_number ?? item.version_number
    const parts = [name, version != null ? `v${version}` : (zh ? '版本未记录' : 'Version not recorded'), datasetFormatLabel(item.format_id)]
    const createdAt = formatSystemDateTime(item.created_at)
    if ((versionCounts.get(item.dataset_version_id) ?? 0) > 1 && createdAt !== '-') parts.push(createdAt)
    const label = parts.join(' · ')
    if (!byLabel.has(label)) byLabel.set(label, [])
    byLabel.get(label)!.push(item.dataset_export_id)
    return { value: item.dataset_export_id, label }
  })

  for (const ids of byLabel.values()) ids.sort()
  return options.map(option => {
    const ids = byLabel.get(option.label)!
    return ids.length > 1 ? { ...option, label: `${option.label} · #${ids.indexOf(option.value) + 1}` } : option
  })
}
