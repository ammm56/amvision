import { createPinia, setActivePinia } from 'pinia'
import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useFeedbackStore } from '@/app/stores/feedback.store'
import { i18n } from '@/platform/i18n'
import ToastHost from './ToastHost.vue'

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: { template: '<div />' } },
      { path: '/next', component: { template: '<div />' } },
    ],
  })
}

describe('ToastHost', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    setActivePinia(createPinia())
    document.body.innerHTML = ''
  })

  afterEach(() => {
    vi.useRealTimers()
    document.body.innerHTML = ''
  })

  it('显示成功反馈并按时自动关闭', async () => {
    const router = createTestRouter()
    await router.push('/')
    const store = useFeedbackStore()
    const wrapper = mount(ToastHost, {
      global: { plugins: [router, i18n] },
    })

    store.success('项目已删除', { message: 'project-2', durationMs: 100 })
    await nextTick()

    expect(document.body.querySelector('[role="status"]')?.textContent).toContain('项目已删除')
    vi.advanceTimersByTime(100)
    await nextTick()
    expect(document.body.querySelector('[role="status"]')).toBeNull()

    wrapper.unmount()
  })

  it('鼠标停留期间暂停自动关闭', async () => {
    const router = createTestRouter()
    await router.push('/')
    const store = useFeedbackStore()
    const wrapper = mount(ToastHost, {
      global: { plugins: [router, i18n] },
    })

    store.success('项目已创建', { durationMs: 1_000 })
    await nextTick()
    const notice = document.body.querySelector<HTMLElement>('.toast-notice')
    expect(notice).not.toBeNull()

    vi.advanceTimersByTime(400)
    notice?.dispatchEvent(new MouseEvent('mouseenter'))
    vi.advanceTimersByTime(1_000)
    await nextTick()
    expect(document.body.querySelector('.toast-notice')).not.toBeNull()

    notice?.dispatchEvent(new MouseEvent('mouseleave'))
    vi.advanceTimersByTime(600)
    await nextTick()
    expect(document.body.querySelector('.toast-notice')).toBeNull()

    wrapper.unmount()
  })

  it('切换页面时清除旧反馈', async () => {
    const router = createTestRouter()
    await router.push('/')
    const store = useFeedbackStore()
    const wrapper = mount(ToastHost, {
      global: { plugins: [router, i18n] },
    })

    store.success('项目已创建', { durationMs: 0 })
    await nextTick()
    expect(store.notices).toHaveLength(1)

    await router.push('/next')
    await nextTick()
    expect(store.notices).toHaveLength(0)

    wrapper.unmount()
  })
})
