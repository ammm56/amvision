import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import type { WorkflowRun } from '../types'
import WorkflowRunDetailDrawer from './WorkflowRunDetailDrawer.vue'

describe('WorkflowRunDetailDrawer', () => {
  afterEach(() => {
    document.body.innerHTML = ''
    document.body.style.overflow = ''
  })

  it('执行失败时展示显式失败节点与未完成业务提示', async () => {
    const failedRun: WorkflowRun = {
      format_id: 'workflow-run-v1',
      workflow_run_id: 'run-fail-1',
      workflow_runtime_id: 'runtime-b',
      project_id: 'project-1',
      application_id: 'app-1',
      state: 'failed',
      created_at: '2026-11-27T01:00:00Z',
      started_at: '2026-11-27T01:00:00Z',
      finished_at: '2026-11-27T01:00:01Z',
      requested_timeout_seconds: 30,
      input_payload: {},
      outputs: {},
      template_outputs: {},
      node_records: [],
      error: {
        code: 'file_not_found',
        message: '输入图像不存在',
        details: {
          node_title: 'Load Local Image',
          path: 'D:\\生产\\输入\\sample-080.jpg',
        },
      },
      metadata: { workflow_run_record_mode: 'full' },
    }

    const wrapper = mount(WorkflowRunDetailDrawer, {
      attachTo: document.body,
      global: { plugins: [i18n] },
      props: {
        open: true,
        projectId: 'project-1',
        applicationName: '塑盒满盘检测',
        run: failedRun,
        runtimeName: '工位 B',
        versionLabel: 'v4',
      },
    })

    await flushPromises()
    const drawer = document.querySelector('[role="dialog"]') as HTMLElement
    expect(drawer.textContent).toContain('执行失败')
    expect(drawer.textContent).toContain('Load Local Image')
    expect(drawer.textContent).toContain('执行未完成，未生成完整结果。')
    wrapper.unmount()
  })

  it('摘要策略成功记录未包含预览图时明确提示且不伪造输入', async () => {
    const minimalRun: WorkflowRun = {
      format_id: 'workflow-run-v1',
      workflow_run_id: 'run-min-1',
      workflow_runtime_id: 'runtime-a',
      project_id: 'project-1',
      application_id: 'app-1',
      state: 'succeeded',
      created_at: '2026-11-27T01:00:00Z',
      started_at: '2026-11-27T01:00:00Z',
      finished_at: '2026-11-27T01:00:01Z',
      requested_timeout_seconds: 30,
      input_payload: {},
      outputs: {},
      template_outputs: {},
      node_records: [],
      error: null,
      metadata: { workflow_run_record_mode: 'minimal' },
    }

    const wrapper = mount(WorkflowRunDetailDrawer, {
      attachTo: document.body,
      global: { plugins: [i18n] },
      props: {
        open: true,
        projectId: 'project-1',
        applicationName: '塑盒满盘检测',
        run: minimalRun,
        runtimeName: '工位 A',
        versionLabel: 'v5',
      },
    })

    await flushPromises()
    const drawer = document.querySelector('[role="dialog"]') as HTMLElement
    expect(drawer.textContent).toContain('执行成功')
    expect(drawer.textContent).toContain('未保存预览图')
    expect(drawer.textContent).toContain('摘要记录未保留完整输入数据')
    wrapper.unmount()
  })
})
