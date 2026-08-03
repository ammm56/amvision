import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import { useFeedbackStore } from './feedback.store'

describe('feedback store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('同一反馈去重并刷新为最新通知', () => {
    const store = useFeedbackStore()

    store.success('项目已删除', { message: 'project-2' })
    const firstId = store.notices[0]?.id
    store.success('项目已删除', { message: 'project-2' })

    expect(store.notices).toHaveLength(1)
    expect(store.notices[0]?.id).not.toBe(firstId)
  })

  it('最多保留三个最新通知', () => {
    const store = useFeedbackStore()

    store.info('one')
    store.info('two')
    store.info('three')
    store.info('four')

    expect(store.notices.map((notice) => notice.title)).toEqual(['two', 'three', 'four'])
  })

  it('错误通知默认不自动消失', () => {
    const store = useFeedbackStore()

    store.error('删除失败')

    expect(store.notices[0]?.durationMs).toBe(0)
  })
})
