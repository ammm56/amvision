import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { useSessionStore } from '@/app/stores/session.store'
import { usePreferencesStore } from '@/app/stores/preferences.store'
import { apiRequest } from '@/shared/api/http-client'

vi.mock('@/shared/api/http-client', () => ({ apiRequest: vi.fn() }))
const admin = { principal_id: 'admin', scopes: ['*'], project_ids: [], allowed_pages: null }
describe('默认登录与权限刷新', () => {
  beforeEach(() => {
    localStorage.clear(); sessionStorage.clear(); vi.resetAllMocks(); setActivePinia(createPinia())
  })
  it.each([false, undefined])('许可为 %s 时不能自动使用缓存的默认 Token', async (allowed) => {
    localStorage.setItem('amvision.web-ui.user-token', 'amvision-default-user-token')
    vi.mocked(apiRequest).mockResolvedValue({ default_auto_login_allowed: allowed })
    const session = useSessionStore()
    await session.initializeSession()
    expect(session.isAuthenticated).toBe(false)
    expect(session.defaultAutoLoginAvailable).toBe(false)
    expect(apiRequest).toHaveBeenCalledTimes(1)
  })
  it('其他用户存在时仍恢复合法手动 Session', async () => {
    sessionStorage.setItem('amvision.web-ui.session-token', 'manual-session')
    vi.mocked(apiRequest).mockImplementation(async (path) => path === '/system/me' ? admin : { default_auto_login_allowed: false })
    const session = useSessionStore()
    await session.initializeSession()
    expect(session.isAuthenticated).toBe(true)
    expect(session.accessToken).toBe('manual-session')
  })
  it('权限刷新断网不清除已有身份，恢复后更新当前权限', async () => {
    const session = useSessionStore()
    session.$patch({ currentUser: admin as never, accessToken: 'session' })
    vi.mocked(apiRequest).mockRejectedValueOnce(new Error('offline'))
    await session.refreshPermissions()
    expect(session.isAuthenticated).toBe(true)
    vi.mocked(apiRequest).mockResolvedValueOnce({ ...admin, allowed_pages: [], scopes: ['workflows:read'] })
    await session.refreshPermissions()
    expect(session.currentUser?.allowed_pages).toEqual([])
  })
  it('两个账号的启动选择隔离，恢复默认不会重新迁移全局旧值', () => {
    const preferences = usePreferencesStore()
    preferences.setStartupPrincipal(admin as never)
    preferences.setStartupPage({ mode: 'projects' })
    preferences.setStartupPrincipal({ ...admin, principal_id: 'reader' } as never)
    expect(preferences.startupPage.mode).toBe('default')
    preferences.setStartupPrincipal(admin as never)
    expect(preferences.startupPage.mode).toBe('projects')
    preferences.resetStartupPage()
    preferences.setStartupPrincipal(null)
    preferences.setStartupPrincipal(admin as never)
    expect(preferences.startupPage.mode).toBe('default')
  })
  it('合并同时刷新，账号切换后忽略旧身份响应', async () => {
    const session = useSessionStore()
    session.$patch({ currentUser: admin as never, accessToken: 'old-session' })
    let resolveRequest!: (value: unknown) => void
    vi.mocked(apiRequest).mockReturnValue(new Promise(resolve => { resolveRequest = resolve }))
    const first = session.refreshPermissions()
    const second = session.refreshPermissions()
    expect(apiRequest).toHaveBeenCalledTimes(1)
    session.$patch({ currentUser: { ...admin, principal_id: 'reader', scopes: [] } as never, accessToken: 'reader-session' })
    resolveRequest(admin)
    await Promise.all([first, second])
    expect(session.currentUser?.principal_id).toBe('reader')
    expect(session.currentUser?.scopes).toEqual([])
  })
})
