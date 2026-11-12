import { canAccessPage } from '@/platform/auth/page-access'
import type { useSessionStore } from '@/app/stores/session.store'

/** 与后端资源响应边界一致；SDK 必须能读取运行实例和部署。 */
export function canExportProjectSdk(session: ReturnType<typeof useSessionStore>): boolean {
  return session.hasScopes(['workflows:read', 'models:read'])
    && canAccessPage(session.currentUser, 'deployments')
    && ['workflow-apps', 'workflow-monitor', 'workflow-app-mode'].some(page => canAccessPage(session.currentUser, page))
}
