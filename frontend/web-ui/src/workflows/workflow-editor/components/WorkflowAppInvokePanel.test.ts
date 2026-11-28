import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import * as runtimeService from '../services/workflow-runtime.service'
import type { WorkflowAppRuntime, WorkflowRun } from '../types'
import WorkflowAppInvokePanel from './WorkflowAppInvokePanel.vue'

function makeRuntime(recordMode: 'none' | 'minimal' | 'full'): WorkflowAppRuntime {
  return {
    format_id: 'workflow-app-runtime-v1',
    workflow_runtime_id: `runtime-${recordMode}`,
    project_id: 'project-1',
    application_id: 'app-1',
    display_name: '工位 A',
    application_snapshot_object_key: 'app.json',
    template_snapshot_object_key: 'tpl.json',
    revision_generation: 1,
    desired_state: 'running',
    observed_state: 'running',
    request_timeout_seconds: 30,
    heartbeat_interval_seconds: 5,
    heartbeat_timeout_seconds: 20,
    created_at: '2026-11-27T00:00:00Z',
    updated_at: '2026-11-27T00:00:00Z',
    health_summary: {},
    metadata: {
      default_execution_metadata: {
        workflow_run_record_mode: recordMode,
      },
    },
  }
}

describe('WorkflowAppInvokePanel', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
    document.body.style.overflow = ''
  })

  it('不保存记录策略时禁用异步模式并显示提示横幅', async () => {
    const wrapper = mount(WorkflowAppInvokePanel, {
      global: { plugins: [i18n, createPinia()] },
      props: {
        projectId: 'project-1',
        applicationId: 'app-1',
        application: null,
        graph: null,
        runtimes: [makeRuntime('none')],
        selectedRuntimeId: 'runtime-none',
        selectedRuntimeVersionLabel: 'v1',
        contract: { format_id: 'amvision.workflow-app-contract.v1', inputs: [], outputs: [] },
        canWrite: true,
        requestExamples: null,
      },
    })

    await flushPromises()
    const asyncBtn = wrapper.get('[data-invoke-mode-async]')
    expect((asyncBtn.element as HTMLButtonElement).disabled).toBe(true)
    expect(wrapper.find('[data-invoke-async-none-banner]').text()).toContain('异步调用需要保存执行记录')
    wrapper.unmount()
  })

  it('不保存策略下同步调用断线显示结果待确认，确认准备新调用只解锁输入而不自动重发', async () => {
    const invokeSpy = vi
      .spyOn(runtimeService, 'invokeWorkflowAppRuntime')
      .mockRejectedValueOnce(new Error('Network failed to fetch'))

    const wrapper = mount(WorkflowAppInvokePanel, {
      attachTo: document.body,
      global: { plugins: [i18n, createPinia()] },
      props: {
        projectId: 'project-1',
        applicationId: 'app-1',
        application: null,
        graph: null,
        runtimes: [makeRuntime('none')],
        selectedRuntimeId: 'runtime-none',
        selectedRuntimeVersionLabel: 'v1',
        contract: { format_id: 'amvision.workflow-app-contract.v1', inputs: [], outputs: [] },
        canWrite: true,
        requestExamples: null,
      },
    })

    await flushPromises()
    await wrapper.get('[data-invoke-submit-btn]').trigger('click')
    await flushPromises()

    expect(invokeSpy).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-invoke-unknown-result]').text()).toContain('结果待确认')
    expect((wrapper.get('[data-invoke-submit-btn]').element as HTMLButtonElement).disabled).toBe(true)

    await wrapper.get('[data-invoke-prepare-new-btn]').trigger('click')
    await flushPromises()

    const dialog = document.querySelector('[role="dialog"]') as HTMLElement
    expect(dialog.textContent).toContain('准备新的调用？')
    expect(dialog.textContent).toContain('上次调用可能已执行，再次调用可能重复保存或计数')

    const confirmBtn = Array.from(dialog.querySelectorAll('button')).find((b) =>
      b.textContent?.includes('准备新调用'),
    ) as HTMLButtonElement
    confirmBtn.click()
    await flushPromises()

    expect(invokeSpy).toHaveBeenCalledTimes(1)
    expect(wrapper.find('[data-invoke-unknown-result]').exists()).toBe(true)
    expect((wrapper.get('[data-invoke-submit-btn]').element as HTMLButtonElement).disabled).toBe(false)
    wrapper.unmount()
  })

  it('业务 NG 与执行成功分层展示，不映射为执行失败', async () => {
    const ngRun: WorkflowRun = {
      format_id: 'workflow-run-v1',
      workflow_run_id: 'run-ng-1',
      workflow_runtime_id: 'runtime-minimal',
      project_id: 'project-1',
      application_id: 'app-1',
      state: 'succeeded',
      created_at: '2026-11-27T01:00:00Z',
      started_at: '2026-11-27T01:00:00Z',
      finished_at: '2026-11-27T01:00:01Z',
      requested_timeout_seconds: 30,
      input_payload: {},
      outputs: {
        http_response: {
          status_code: 200,
          body: { status: 'NG', total: 80, ok: 78, ng: 2 },
        },
      },
      template_outputs: {},
      node_records: [],
      error: null,
      metadata: { workflow_run_record_mode: 'minimal' },
    }
    vi.spyOn(runtimeService, 'invokeWorkflowAppRuntime').mockResolvedValueOnce(ngRun)

    const wrapper = mount(WorkflowAppInvokePanel, {
      global: { plugins: [i18n, createPinia()] },
      props: {
        projectId: 'project-1',
        applicationId: 'app-1',
        application: null,
        graph: null,
        runtimes: [makeRuntime('minimal')],
        selectedRuntimeId: 'runtime-minimal',
        selectedRuntimeVersionLabel: 'v1',
        contract: { format_id: 'amvision.workflow-app-contract.v1', inputs: [], outputs: [] },
        canWrite: true,
        requestExamples: null,
      },
    })

    await flushPromises()
    await wrapper.get('[data-invoke-submit-btn]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('执行成功')
    expect(wrapper.text()).not.toContain('执行失败')
    expect(wrapper.get('[data-invoke-biz-outcome]').text()).toContain('NG')
    wrapper.unmount()
  })
})
