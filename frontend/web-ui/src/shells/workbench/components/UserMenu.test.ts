import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import UserMenu from './UserMenu.vue'
import { usePreferencesStore } from '@/app/stores/preferences.store'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n, setI18nLocale } from '@/platform/i18n'

const RouteStub = { template: '<div />' }

async function mountUserMenu(compact = false) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/projects', component: RouteStub },
      { path: '/login', component: RouteStub },
    ],
  })
  await router.push('/projects')
  await router.isReady()

  const sessionStore = useSessionStore()
  sessionStore.$patch({
    accessToken: 'test-token',
    currentUser: {
      principal_id: 'user-1',
      principal_type: 'user',
      project_ids: ['project-1'],
      scopes: ['*'],
      username: 'amvar',
      display_name: 'amvar',
    },
  })

  const wrapper = mount(UserMenu, {
    attachTo: document.body,
    props: { compact },
    global: { plugins: [pinia, i18n, router] },
  })

  return {
    router,
    sessionStore,
    preferencesStore: usePreferencesStore(),
    wrapper,
  }
}

function findButton(selector: string, label: string): HTMLButtonElement {
  const button = Array.from(document.body.querySelectorAll<HTMLButtonElement>(selector)).find(
    (item) => item.textContent?.trim().includes(label),
  )
  if (!button) throw new Error(`button not found: ${label}`)
  return button
}

describe('UserMenu', () => {
  beforeEach(() => {
    localStorage.clear()
    setI18nLocale('zh-CN')
    document.documentElement.dataset.theme = 'light'
  })

  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('shows the first two user-name characters in compact mode', async () => {
    const { wrapper } = await mountUserMenu(true)

    expect(wrapper.get('.user-menu__avatar').text()).toBe('am')
    expect(wrapper.get('.user-menu__trigger').attributes('title')).toBe('amvar')

    wrapper.unmount()
  })

  it('uses exclusive expandable sections and applies preferences', async () => {
    const { preferencesStore, wrapper } = await mountUserMenu()

    await wrapper.get('.user-menu__trigger').trigger('click')
    await nextTick()
    expect(document.body.querySelector('.user-menu__header small')).toBeNull()

    findButton('.user-menu__section-toggle', '语言').click()
    await nextTick()
    expect(document.body.textContent).toContain('English')

    findButton('.user-menu__section-toggle', '外观').click()
    await nextTick()
    expect(document.body.querySelector('[aria-label="语言"][role="radiogroup"]')).toBeNull()
    expect(document.body.querySelector('[aria-label="外观"][role="radiogroup"]')).not.toBeNull()

    findButton('.user-menu__option', '暗色').click()
    await nextTick()
    expect(preferencesStore.theme).toBe('dark')
    expect(document.documentElement.dataset.theme).toBe('dark')

    wrapper.unmount()
  })

  it('logs out and returns to the login page', async () => {
    const { router, sessionStore, wrapper } = await mountUserMenu()
    const logout = vi.spyOn(sessionStore, 'logout').mockResolvedValue()

    await wrapper.get('.user-menu__trigger').trigger('click')
    await nextTick()
    findButton('.user-menu__logout', '退出登录').click()
    await flushPromises()

    expect(logout).toHaveBeenCalledOnce()
    expect(router.currentRoute.value.path).toBe('/login')

    wrapper.unmount()
  })
})
