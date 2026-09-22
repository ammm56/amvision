import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useProjectStore } from '@/app/stores/project.store'
import { i18n } from '@/platform/i18n'
import {
  listWorkflowTriggerSources,
  refreshWorkflowTriggerSourceStatuses,
  type WorkflowTriggerSource,
} from '../services/trigger-source.service'
import TriggerSourcePage from './TriggerSourcePage.vue'

vi.mock('@/workflows/workflow-editor/services/workflow-runtime.service', () => ({
  listWorkflowAppRuntimes: vi.fn(async () => ({ items: [] })),
  refreshWorkflowAppRuntimeStatuses: vi.fn(async () => ({ items: [], failedRuntimeIds: [] })),
}))

vi.mock('../services/trigger-source.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('../services/trigger-source.service')>(),
  listWorkflowTriggerSources: vi.fn(),
  refreshWorkflowTriggerSourceStatuses: vi.fn(),
}))

afterEach(() => {
  document.body.innerHTML = ''
  vi.clearAllMocks()
})

describe('触发入口列表与详情', () => {
  it('列表隐藏技术详情，抽屉按所选入口显示；刷新空触发时间不保留旧时间', async () => {
    i18n.global.locale.value = 'zh-CN'
    const source: WorkflowTriggerSource = {
      format_id: 'amvision.workflow-trigger-source.v1',
      project_id: 'project-1',
      trigger_source_id: 'directory-watch-private-id',
      workflow_runtime_id: 'workflow-runtime-private-id',
      display_name: '结果图片变化',
      trigger_kind: 'directory-watch',
      enabled: true,
      desired_state: 'running',
      observed_state: 'running',
      submit_mode: 'async',
      transport_config: {},
      match_rule: {},
      input_binding_mapping: {},
      result_mapping: { result_bindings: [] },
      default_execution_metadata: {},
      ack_policy: 'ack-after-run-created',
      result_mode: 'event-only',
      metadata: {},
      created_at: '2026-09-22T00:00:00Z',
      updated_at: '2026-09-22T00:00:00Z',
      last_triggered_at: '2026-09-22T08:28:56+08:00',
      health_summary: { adapter_running: true, request_count: 16, success_count: 16 },
    }
    vi.mocked(listWorkflowTriggerSources).mockResolvedValue({
      items: [source], pagination: { offset: 0, limit: 50, totalCount: 1, hasMore: false, nextOffset: null },
    })
    vi.mocked(refreshWorkflowTriggerSourceStatuses).mockResolvedValue({
      items: [source], healthByTriggerSourceId: {}, failedTriggerSourceIds: [],
    })
    const pinia = createPinia()
    useProjectStore(pinia).selectedProjectId = 'project-1'
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/', component: { template: '<div />' } }] })
    await router.push('/')
    const wrapper = mount(TriggerSourcePage, { attachTo: document.body, global: { plugins: [pinia, router, i18n] } })
    try {
      await flushPromises()
      const table = wrapper.get('.resource-table')
      expect(table.text()).toContain('触发时间')
      expect(table.text()).toContain('2026-09-22')
      expect(table.text()).not.toContain('private-id')
      expect(table.text()).not.toContain('request=')
      await table.findAll('button').find((button) => button.text() === '详情')!.trigger('click')
      await flushPromises()
      const drawer = document.querySelector('[role="dialog"]')!
      expect(drawer.textContent).toContain(source.trigger_source_id)
      expect(drawer.textContent).toContain(source.workflow_runtime_id)
      expect(JSON.parse(drawer.querySelector('.json-view')!.textContent!)).toMatchObject({ request_count: 16, success_count: 16 })
      expect(drawer.querySelectorAll('.resource-details > div')).toHaveLength(10)
      // 刷新后的实例没有触发记录时，不得回退显示旧的时间。
      vi.mocked(refreshWorkflowTriggerSourceStatuses).mockResolvedValue({
        items: [{ ...source, last_triggered_at: null }], healthByTriggerSourceId: {}, failedTriggerSourceIds: [],
      })
      await wrapper.findAll('button').find((button) => button.text() === '刷新')!.trigger('click')
      await flushPromises()
      expect(document.querySelector('[role="dialog"]')!.textContent).toContain('未触发')
      expect(table.text()).toContain('未触发')
      document.querySelector('[role="dialog"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }))
      await flushPromises()
      expect(document.querySelector('[role="dialog"]')).toBeNull()
    } finally {
      wrapper.unmount()
    }
  })
})
