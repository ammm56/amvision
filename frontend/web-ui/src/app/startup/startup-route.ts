import type { CurrentUser } from '@/shared/contracts'
import { canAccessPath, firstAccessiblePath } from '@/platform/auth/page-access'
import type { StartupPagePreference } from './startup-page-preference'
import { ApiError } from '@/shared/api/error'
import {
  getWorkflowRuntimePreviewSnapshot,
  type RuntimePreviewSnapshot,
} from '@/workflows/workflow-editor/services/workflow-runtime-preview.service'

export interface StartupRouteResolution {
  path: string
  resetPreference: boolean
}

interface ResolvePostAuthenticationRouteInput {
  user?: CurrentUser | null
  explicitRedirect: unknown
  preference: StartupPagePreference
  getSnapshot?: (workflowRuntimeId: string) => Promise<RuntimePreviewSnapshot>
}

export async function resolvePostAuthenticationRoute(
  input: ResolvePostAuthenticationRouteInput,
): Promise<StartupRouteResolution> {
  const fallback = input.user === undefined ? '/projects' : firstAccessiblePath(input.user)
  const permitted = (path: string) => path.startsWith('/') && !path.startsWith('//') && !path.includes('\\') && (input.user === undefined || canAccessPath(input.user, path))
  if (typeof input.explicitRedirect === 'string' && permitted(input.explicitRedirect)) {
    return { path: input.explicitRedirect, resetPreference: false }
  }
  if (input.preference.mode !== 'workflow-runtime-app-mode') {
    const projects = input.preference.mode === 'projects' && permitted('/projects')
    return { path: projects ? '/projects' : fallback, resetPreference: false }
  }

  const targetPath = `/workflows/runtime/${encodeURIComponent(input.preference.workflowRuntimeId)}/app-mode`
  if (!permitted(targetPath) || input.user?.project_ids.length && !input.user.project_ids.includes(input.preference.projectId)) return { path: fallback, resetPreference: true }
  const readSnapshot = input.getSnapshot ?? getWorkflowRuntimePreviewSnapshot
  try {
    const snapshot = await readSnapshot(input.preference.workflowRuntimeId)
    const matchesTarget = snapshot.workflow_runtime_id === input.preference.workflowRuntimeId
      && snapshot.project_id === input.preference.projectId
      && snapshot.application_id === input.preference.applicationId
      && snapshot.app_mode !== null
    return matchesTarget
      ? { path: targetPath, resetPreference: false }
      : { path: fallback, resetPreference: true }
  } catch (error) {
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
      return { path: fallback, resetPreference: true }
    }
    // 短暂网络或服务错误不删除用户选择，App Mode 自身会继续按既有策略重连。
    return { path: targetPath, resetPreference: false }
  }
}
