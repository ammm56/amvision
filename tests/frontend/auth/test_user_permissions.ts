import { describe, expect, it } from 'vitest'
import type { CurrentUser } from '@/shared/contracts'
import { canAccessPage, canAccessPath, canInvokeWorkflow, canReadProjectFiles, firstAccessiblePath } from '@/platform/auth/page-access'
import { userAccessIssue, emptyUserAccess } from '@/modules/settings/user-access-form'

const user: CurrentUser = { principal_id: 'reader', principal_type: 'user', project_ids: ['p'], scopes: ['workflows:read', 'workflows:invoke', 'projects:files:read'], allowed_pages: ['settings-startup', 'workflow-app-mode'] }
describe('通用页面与操作权限', () => {
  it('只显示已授予页面，执行和文件读取分别判断', () => {
    expect(canAccessPage(user, 'workflow-app-mode')).toBe(true)
    expect(canAccessPath(user, '/settings?category=startup')).toBe(true)
    expect(canAccessPath(user, '/settings?category=security&section=accounts')).toBe(false)
    expect(canAccessPath(user, '/workflows/graph/apps/a')).toBe(false)
    expect(canAccessPath(user, '//outside.test')).toBe(false)
    expect(canInvokeWorkflow(user)).toBe(true)
    expect(canReadProjectFiles(user)).toBe(true)
    expect(firstAccessiblePath(user)).toBe('/settings?category=startup')
  })
  it('页面不隐含写权限，空数组与兼容模式不同', () => {
    const read = { ...user, scopes: ['workflows:read'] }
    expect(canInvokeWorkflow(read)).toBe(false)
    expect(canReadProjectFiles(read)).toBe(false)
    expect(canAccessPage({ ...user, allowed_pages: [] }, 'workflow-app-mode')).toBe(false)
    expect(canAccessPage({ ...user, allowed_pages: null }, 'workflow-apps')).toBe(true)
    expect(canAccessPage({ ...user, scopes: [], allowed_pages: ['workflow-app-mode'] }, 'workflow-app-mode')).toBe(false)
  })
  it('不把空项目选择当全部项目，不预设业务权限', () => {
    expect(emptyUserAccess().scopes).toEqual([])
    expect(userAccessIssue(emptyUserAccess())).toBe('selectProject')
    expect(userAccessIssue({ ...emptyUserAccess(), allProjects: true })).toBe(null)
    expect(userAccessIssue({ ...emptyUserAccess(), allProjects: true, scopes: ['workflows:invoke'] })).toBe('invokeNeedsRead')
  })
  it('无页面或仅能读取图的账号不会回退到无权新建页', () => {
    expect(firstAccessiblePath({ ...user, allowed_pages: [] })).toBe('/forbidden')
    const graphReader = { ...user, scopes: ['workflows:read'], allowed_pages: ['workflow-graph'] }
    expect(canAccessPath(graphReader, '/workflows/graph/apps/a')).toBe(true)
    expect(canAccessPath(graphReader, '/workflows/graph/new')).toBe(false)
    expect(firstAccessiblePath(graphReader)).toBe('/forbidden')
  })
})
