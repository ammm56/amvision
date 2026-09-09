import { describe, expect, it, vi } from 'vitest'
import { resolvePostAuthenticationRoute } from '@/app/startup/startup-route'
import { parseStartupPagePreference, startupStorageKey } from '@/app/startup/startup-page-preference'
import type { CurrentUser } from '@/shared/contracts'

const user: CurrentUser = { principal_id: 'u', principal_type: 'user', scopes: ['workflows:read'], project_ids: ['p'], allowed_pages: ['settings-startup', 'workflow-app-mode'] }
describe('账号自行选择启动目标', () => {
  it('无目标时进入现有启动设置，不自动选择应用', async () => {
    expect(await resolvePostAuthenticationRoute({ user, explicitRedirect: '//outside', preference: { mode: 'default' } })).toEqual({ path: '/settings?category=startup', resetPreference: false })
    expect(await resolvePostAuthenticationRoute({ user, explicitRedirect: '/projects', preference: { mode: 'projects' } })).toEqual({ path: '/settings?category=startup', resetPreference: false })
  })
  it('跨项目目标在请求前拒绝', async () => {
    const getSnapshot = vi.fn()
    const result = await resolvePostAuthenticationRoute({ user, explicitRedirect: null, preference: { mode: 'workflow-runtime-app-mode', projectId: 'other', applicationId: 'a', workflowRuntimeId: 'r' }, getSnapshot })
    expect(getSnapshot).not.toHaveBeenCalled()
    expect(result.resetPreference).toBe(true)
  })
  it('v1 兼容且 default 与 projects 分开，存储按主体隔离', () => {
    expect(parseStartupPagePreference(null)).toEqual({ mode: 'default' })
    expect(parseStartupPagePreference(JSON.stringify({ format_id: 'amvision.web-ui.startup-page-preference.v1', mode: 'projects' }))).toEqual({ mode: 'projects' })
    expect(startupStorageKey('a')).not.toBe(startupStorageKey('b'))
  })
})
