import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import InlineMessage from '@/shared/ui/feedback/InlineMessage.vue'
import TaskProgress from './TaskProgress.vue'
import TaskStateBadge from './TaskStateBadge.vue'

describe('task feedback components', () => {
  it('renders a running task with the info semantic instead of success', () => {
    const wrapper = mount(TaskStateBadge, {
      props: { state: 'running' },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find('.status-badge--info').exists()).toBe(true)
    expect(wrapper.find('.status-badge__dot').exists()).toBe(false)
    expect(wrapper.text()).toContain('运行中')
  })

  it('normalizes task stages and clamps progress to the valid range', () => {
    const status = mount(TaskStateBadge, {
      props: { state: 'validating' },
      global: { plugins: [i18n] },
    })
    const progress = mount(TaskProgress, {
      props: { percent: 125, ariaLabel: '任务进度' },
    })

    expect(status.find('.status-badge--info').exists()).toBe(true)
    expect(status.find('.status-badge__dot').exists()).toBe(false)
    expect(progress.get('[role="progressbar"]').attributes('aria-valuenow')).toBe('100')
    expect(progress.get('.task-progress__track span').attributes('style')).toContain('width: 100%')
  })

  it.each([
    ['paused', '已暂停', 'warning'],
    ['timed_out', '已超时', 'danger'],
  ])('preserves the %s task state', (state, label, tone) => {
    const wrapper = mount(TaskStateBadge, {
      props: { state },
      global: { plugins: [i18n] },
    })

    expect(wrapper.find(`.status-badge--${tone}`).exists()).toBe(true)
    expect(wrapper.text()).toContain(label)
  })

  it('uses the shared semantic message treatment for contextual errors', () => {
    const wrapper = mount(InlineMessage, {
      props: { tone: 'danger', title: '任务失败', message: '输出文件不可用' },
    })

    expect(wrapper.attributes('role')).toBe('alert')
    expect(wrapper.classes()).toContain('inline-message--danger')
    expect(wrapper.text()).toContain('输出文件不可用')
  })
})
