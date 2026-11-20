import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { createMemoryHistory, createRouter } from 'vue-router'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { useSessionStore } from '@/app/stores/session.store'
import { i18n } from '@/platform/i18n'
import { readConversionValidationFailure } from '@/modules/models/conversion-validation-failure'
import ConversionTaskDetailPage from '@/modules/models/pages/ConversionTaskDetailPage.vue'
import ResourceMenu from '@/shared/ui/components/ResourceMenu.vue'
import { getModelConversionTaskDetail, type ModelConversionTaskDetail } from '@/modules/models/services/model.service'

vi.mock('@/modules/models/services/model.service', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/modules/models/services/model.service')>(), getModelConversionTaskDetail: vi.fn(),
}))
enableAutoUnmount(afterEach)

describe('conversion task terminal states', () => {
  it('reads numerical failures from a supervised OpenVINO worker', () => {
    const evidence = {
      source_runtime: 'ONNX Runtime (CPU)', target_runtime: 'OpenVINO INT8 (CPU)',
      input_kind: 'validation_image', rule: 'normalized_error', peak_rule: 'p99',
      sample_count: 30, check_count: 30, failed_check_count: 11, max_error_limit: 0.1, mean_error_limit: 0.02,
      failures: [{
        sample_name: 'barcode119.jpg', profile: 'static',
        input_shape: [1, 3, 320, 320], input_dtype: 'float32',
        output_name: 'predictions', output_shape: [1, 6, 2100], output_dtype: 'float32',
        index: [0, 4, 4], source_value: 0.1, target_value: 0.4, max_error: 0.3, mean_error: 0.10,
      }],
    }
    expect(readConversionValidationFailure({ child_error: { details: { numeric_validation: evidence } } })).toEqual(evidence)
  })

  it.each([['timed_out', true], ['running', false]])('handles %s without obsolete state aliases', async (state, canDelete) => {
    const pinia = createPinia()
    const session = useSessionStore(pinia)
    vi.spyOn(session, 'hasScopes').mockReturnValue(true)
    const router = createRouter({ history: createMemoryHistory(), routes: [
      { path: '/models/:taskType/conversion-tasks/:taskId', component: ConversionTaskDetailPage },
      { path: '/models', component: { template: '<p>models list</p>' } },
    ] })
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
    expect(wrapper.getComponent(ResourceMenu).props('items').find(item => item.id === 'delete')?.disabled).toBe(!canDelete)
    expect(wrapper.findAll('button').some(button => button.text() === '取消转换')).toBe(state === 'running')
    expect(wrapper.text()).toContain(state === 'running' ? '转换完成后显示产物' : '转换超时')
  })
})
