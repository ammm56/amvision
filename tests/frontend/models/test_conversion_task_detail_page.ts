import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '@/app/stores/session.store'
import { i18n } from '@/platform/i18n'
import ConversionTaskDetailPage from '@/modules/models/pages/ConversionTaskDetailPage.vue'
import { getModelConversionTaskDetail, type ModelConversionTaskDetail } from '@/modules/models/services/model.service'

vi.mock('@/modules/models/services/model.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/models/services/model.service')>(), getModelConversionTaskDetail: vi.fn(),
}))
enableAutoUnmount(afterEach)

describe('conversion task terminal states', () => {
  it.each([['timed_out', true], ['running', false]])('handles %s without obsolete state aliases', async (state, canDelete) => {
    const pinia = createPinia()
    const session = useSessionStore(pinia)
    vi.spyOn(session, 'hasScopes').mockReturnValue(true)
    const router = createRouter({ history: createMemoryHistory(), routes: [{ path: '/models/:taskType/conversion-tasks/:taskId', component: ConversionTaskDetailPage }] })
    await router.push('/models/classification/conversion-tasks/task-1')
    await router.isReady()
    const task: ModelConversionTaskDetail = {
      task_id: 'task-1', display_name: 'classification conversion', project_id: 'project-1', created_at: '2026-10-12T00:00:00Z',
      state: String(state), current_attempt_no: 1, progress: {}, result: {}, metadata: {}, source_model_version_id: 'source-1',
      target_formats: ['onnx'], requested_target_formats: ['onnx'], produced_formats: [], builds: [], report_summary: {}, task_spec: {}, events: [],
    }
    vi.mocked(getModelConversionTaskDetail).mockResolvedValue(task)
    const wrapper = mount(ConversionTaskDetailPage, { global: { plugins: [pinia, i18n, router] } })
    await flushPromises()
    expect(wrapper.find('button.ui-button--danger').attributes('disabled') === undefined).toBe(canDelete)
  })
})
