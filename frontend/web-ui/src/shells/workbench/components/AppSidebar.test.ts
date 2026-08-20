import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it } from 'vitest'

import AppSidebar from './AppSidebar.vue'
import { useSessionStore } from '@/app/stores/session.store'
import { i18n, setI18nLocale } from '@/platform/i18n'

const RouteStub = { template: '<div />' }

async function mountSidebar(collapsed: boolean) {
  const pinia = createPinia()
  setActivePinia(pinia)
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/:pathMatch(.*)*', component: RouteStub }],
  })
  await router.push('/projects')
  await router.isReady()

  useSessionStore().$patch({
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

  return mount(AppSidebar, {
    props: { collapsed },
    global: { plugins: [pinia, i18n, router] },
  })
}

describe('AppSidebar', () => {
  beforeEach(() => {
    localStorage.clear()
    setI18nLocale('zh-CN')
  })

  it('shows the collapse action beside the brand when expanded', async () => {
    const wrapper = await mountSidebar(false)

    expect(wrapper.get('.app-sidebar__brand').text()).toContain('amvision')
    expect(wrapper.find('.app-sidebar__collapsed-expand').exists()).toBe(false)
    expect(wrapper.find('.app-sidebar__collapse-toggle').exists()).toBe(false)

    await wrapper.get('.app-sidebar__header-collapse').trigger('click')
    expect(wrapper.emitted('toggleCollapsed')).toHaveLength(1)
  })

  it('uses the top brand position as the expand action when collapsed', async () => {
    const wrapper = await mountSidebar(true)
    const expandButton = wrapper.get('.app-sidebar__collapsed-expand')

    expect(wrapper.find('.app-sidebar__brand').exists()).toBe(false)
    expect(expandButton.get('.app-sidebar__collapsed-brand').text()).toBe('AM')
    expect(expandButton.attributes('aria-label')).toBe('展开导航栏')

    await expandButton.trigger('click')
    expect(wrapper.emitted('toggleCollapsed')).toHaveLength(1)
  })
})
