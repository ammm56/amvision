import { listProjectModelCatalog, type PlatformBaseModelSummary, type PlatformBaseModelVersionSummary } from './services/model.service'

/** 展示名称只影响界面，不改变模型登记名称。 */
export function modelDisplayName(model: PlatformBaseModelSummary): string {
  const displayName = model.metadata?.display_name
  return typeof displayName === 'string' && displayName.trim() ? displayName.trim() : model.model_name
}

export function modelVersionDisplayName(version: PlatformBaseModelVersionSummary, withName = false): string {
  const number = version.version_number ?? version.metadata?.version_number
  const name = modelVersionCustomName(version)
  if (typeof number === 'number' && Number.isInteger(number) && number > 0 && withName && name && name !== `v${number}`) return `v${number} · ${name}`
  if (typeof number === 'number' && Number.isInteger(number) && number > 0) return `v${number}`
  return withName && name ? name : '—'
}

export function modelVersionCustomName(version: PlatformBaseModelVersionSummary): string {
  const name = version.metadata?.display_name
  return typeof name === 'string' ? name.trim() : ''
}

/** 只用已登记的顺序、时间或完整的父版本链判断最新版本。 */
export function latestModelVersion(versions: PlatformBaseModelVersionSummary[]): PlatformBaseModelVersionSummary | undefined {
  if (versions.length < 2) return versions[0]
  const numbers = versions.map(version => version.version_number ?? version.metadata?.version_number)
  if (numbers.every((number): number is number => typeof number === 'number' && Number.isInteger(number) && number > 0)
    && new Set(numbers).size === versions.length) return versions[numbers.indexOf(Math.max(...numbers))]
  const dates = versions.map(version => {
    const value = version.metadata?.registered_at
    return typeof value === 'string' ? Date.parse(value) : NaN
  })
  if (dates.every(Number.isFinite) && new Set(dates).size === versions.length) return versions[dates.indexOf(Math.max(...dates))]
  const parents = new Set(versions.map(version => version.parent_version_id))
  const candidates = versions.filter(version => !parents.has(version.model_version_id))
  if (candidates.length !== 1) return undefined
  const byId = new Map(versions.map(version => [version.model_version_id, version]))
  const visited = new Set<string>()
  for (let version: PlatformBaseModelVersionSummary | undefined = candidates[0]; version && !visited.has(version.model_version_id);) {
    visited.add(version.model_version_id)
    version = byId.get(version.parent_version_id || '')
  }
  return visited.size === versions.length ? candidates[0] : undefined
}

export async function readCatalogVersionNames(projectId: string, taskType: string, versionIds: string[], signal: AbortSignal): Promise<Map<string, string>> {
  const missing = new Set(versionIds.filter(Boolean))
  const names = new Map<string, string>()
  const limit = 100
  for (let offset = 0; missing.size; offset += limit) {
    const page = await listProjectModelCatalog({ projectId, taskType, offset, limit, signal })
    if (signal.aborted) break
    for (const model of page.items) for (const version of model.available_versions) {
      if (missing.delete(version.model_version_id)) names.set(version.model_version_id, `${modelDisplayName(model)} · ${modelVersionDisplayName(version, true)}`)
    }
    if (!page.items.length || offset + limit >= page.total) break
  }
  return names
}
