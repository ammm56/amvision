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
  explicitRedirect: unknown
  preference: StartupPagePreference
  getSnapshot?: (workflowRuntimeId: string) => Promise<RuntimePreviewSnapshot>
}

export async function resolvePostAuthenticationRoute(
  input: ResolvePostAuthenticationRouteInput,
): Promise<StartupRouteResolution> {
  if (typeof input.explicitRedirect === 'string' && input.explicitRedirect) {
    return { path: input.explicitRedirect, resetPreference: false }
  }
  if (input.preference.mode === 'projects') {
    return { path: '/projects', resetPreference: false }
  }

  const targetPath = `/workflows/runtime/${encodeURIComponent(input.preference.workflowRuntimeId)}/app-mode`
  const readSnapshot = input.getSnapshot ?? getWorkflowRuntimePreviewSnapshot
  try {
    const snapshot = await readSnapshot(input.preference.workflowRuntimeId)
    const matchesTarget = snapshot.workflow_runtime_id === input.preference.workflowRuntimeId
      && snapshot.project_id === input.preference.projectId
      && snapshot.application_id === input.preference.applicationId
      && snapshot.app_mode !== null
    return matchesTarget
      ? { path: targetPath, resetPreference: false }
      : { path: '/projects', resetPreference: true }
  } catch (error) {
    if (error instanceof ApiError && (error.status === 403 || error.status === 404)) {
      return { path: '/projects', resetPreference: true }
    }
    // 短暂网络或服务错误不删除用户选择，App Mode 自身会继续按既有策略重连。
    return { path: targetPath, resetPreference: false }
  }
}
