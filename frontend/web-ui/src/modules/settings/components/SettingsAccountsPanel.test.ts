import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '@/app/stores/session.store'
import { i18n, setI18nLocale } from '@/platform/i18n'
import SettingsAccountsPanel from './SettingsAccountsPanel.vue'

vi.mock('../services/local-auth-management.service', () => ({
  createLocalAuthUser: vi.fn(),
  createLocalAuthUserToken: vi.fn(),
  deleteLocalAuthUser: vi.fn(),
  listLocalAuthUserTokens: vi.fn().mockResolvedValue([]),
  listLocalAuthUsers: vi.fn().mockResolvedValue([
    {
      user_id: 'user-amvar',
      provider_kind: 'local',
      username: 'amvar',
      display_name: 'amvar',
      principal_type: 'user',
      project_ids: [],
      scopes: ['*'],
      is_active: true,
      created_at: '2026-08-02T00:00:00Z',
      updated_at: '2026-08-02T00:00:00Z',
      last_login_at: null,
    },
  ]),
  resetLocalAuthUserPassword: vi.fn(),
  revokeLocalAuthUserToken: vi.fn(),
  updateLocalAuthUser: vi.fn(),
}))

describe('SettingsAccountsPanel', () => {
  let pinia: Pinia

  beforeEach(() => {
    pinia = createPinia()
    setActivePinia(pinia)
    setI18nLocale('zh-CN')
    useSessionStore().$patch({
      accessToken: 'test-token',
      currentUser: {
        principal_id: 'user-amvar',
        principal_type: 'user',
        project_ids: [],
        scopes: ['*'],
        username: 'amvar',
        display_name: 'amvar',
      },
    })
  })

  it('keeps refresh available and protects the only amvar user', async () => {
    const wrapper = mount(SettingsAccountsPanel, { global: { plugins: [pinia, i18n] } })
    await flushPromises()

    const buttons = wrapper.findAll('button')
    const refreshButton = buttons.find((button) => button.text().trim() === '刷新')
    const disableButton = buttons.find((button) => button.text().trim() === '禁用')
    const deleteButton = buttons.find((button) => button.text().trim() === '删除')

    expect(refreshButton?.attributes('disabled')).toBeUndefined()
    expect(disableButton?.attributes('disabled')).toBeDefined()
    expect(deleteButton?.attributes('disabled')).toBeDefined()
    expect(disableButton?.attributes('title')).toBe('唯一的 amvar 用户不能禁用或删除')
    expect(deleteButton?.attributes('title')).toBe('唯一的 amvar 用户不能禁用或删除')

    wrapper.unmount()
  })
})
