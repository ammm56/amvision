import { readStorageValue, removeStorageValue, writeStorageValue } from '@/platform/storage/browser-storage'

export const STARTUP_PAGE_STORAGE_KEY = 'amvision.web-ui.startup-page'
export const STARTUP_PAGE_PREFERENCE_FORMAT_ID = 'amvision.web-ui.startup-page-preference.v2'

export type StartupPagePreference =
  | { mode: 'projects' }
  | { mode: 'default' }
  | {
      mode: 'workflow-runtime-app-mode'
      projectId: string
      applicationId: string
      workflowRuntimeId: string
    }

export function createDefaultStartupPagePreference(): StartupPagePreference {
  return { mode: 'default' }
}

export function parseStartupPagePreference(value: string | null): StartupPagePreference {
  if (!value) return createDefaultStartupPagePreference()
  try {
    const parsed = JSON.parse(value) as unknown
    if (!isRecord(parsed)) return createDefaultStartupPagePreference()
    if (![STARTUP_PAGE_PREFERENCE_FORMAT_ID, 'amvision.web-ui.startup-page-preference.v1'].includes(String(parsed.format_id))) return createDefaultStartupPagePreference()
    if (parsed.mode === 'projects') return { mode: 'projects' }
    if (parsed.mode === 'default') return createDefaultStartupPagePreference()
    if (
      parsed.mode === 'workflow-runtime-app-mode'
      && isNonEmptyString(parsed.projectId)
      && isNonEmptyString(parsed.applicationId)
      && isNonEmptyString(parsed.workflowRuntimeId)
    ) {
      return {
        mode: parsed.mode,
        projectId: parsed.projectId.trim(),
        applicationId: parsed.applicationId.trim(),
        workflowRuntimeId: parsed.workflowRuntimeId.trim(),
      }
    }
  } catch {
    // 本地配置损坏时使用稳定默认值，不阻断前端启动。
  }
  return createDefaultStartupPagePreference()
}

export function readStartupPagePreference(principalId?: string): StartupPagePreference {
  return parseStartupPagePreference(readStorageValue(startupStorageKey(principalId), 'localStorage'))
}

export function writeStartupPagePreference(preference: StartupPagePreference, principalId?: string): void {
  if (preference.mode === 'default') {
    removeStorageValue(startupStorageKey(principalId), 'localStorage')
    return
  }
  writeStorageValue(startupStorageKey(principalId), JSON.stringify({
    format_id: STARTUP_PAGE_PREFERENCE_FORMAT_ID,
    ...preference,
  }), 'localStorage')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value.trim().length > 0
}

export function startupStorageKey(principalId?: string): string {
  return principalId ? `${STARTUP_PAGE_STORAGE_KEY}.${encodeURIComponent(principalId)}` : STARTUP_PAGE_STORAGE_KEY
}
