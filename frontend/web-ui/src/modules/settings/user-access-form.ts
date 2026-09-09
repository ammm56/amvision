import type { CurrentUser, LocalAuthUser } from '@/shared/contracts'
import { pageDefinitions } from '@/platform/auth/page-access'
import { hasScope } from '@/platform/auth/permissions'

export const operationDefinitions = [{"id": "workflows:read"}, {"id": "workflows:invoke"}, {"id": "workflows:write"}, {"id": "projects:files:read"}, {"id": "projects:delete"}, {"id": "models:read"}, {"id": "models:write"}, {"id": "datasets:read"}, {"id": "datasets:write"}, {"id": "tasks:read"}, {"id": "tasks:write"}, {"id": "auth:read"}, {"id": "auth:write"}, {"id": "system:read"}]
export interface UserAccessDraft { pages: string[] | null; scopes: string[]; projectIds: string[]; allProjects: boolean }
export function emptyUserAccess(): UserAccessDraft { return { pages: [], scopes: [], projectIds: [], allProjects: false } }
export function userAccessDraft(user: LocalAuthUser): UserAccessDraft {
  return { pages: user.allowed_pages == null ? null : [...user.allowed_pages], scopes: [...user.scopes], projectIds: [...user.project_ids], allProjects: user.project_ids.length === 0 }
}
export function userAccessIssue(draft: UserAccessDraft): string | null {
  if (!draft.allProjects && !draft.projectIds.length) return 'selectProject'
  const user = { scopes: draft.scopes } as CurrentUser
  if (hasScope(user, 'workflows:invoke') && !hasScope(user, 'workflows:read')) return 'invokeNeedsRead'
  if (draft.pages?.some((id) => { const page = pageDefinitions.find((p) => p.id === id); return !page || page.scopes.some((scope) => !hasScope(user, scope)) })) return 'pageNeedsRead'
  return null
}
