import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import type { WorkflowAppRuntime } from '../types'
import WorkflowRuntimeDetailsDrawer from './WorkflowRuntimeDetailsDrawer.vue'

const runtime: WorkflowAppRuntime = {
  format_id: 'workflow-app-runtime-v1',
  workflow_runtime_id: 'workflow-runtime-test',
  project_id: 'project-1',
  application_id: 'workflow-app-test',
  display_name: '测试运行时',
  application_snapshot_object_key: 'application.json',
  template_snapshot_object_key: 'template.json',
  revision_generation: 3,
  desired_state: 'running',
  observed_state: 'running',
  request_timeout_seconds: 30,
  heartbeat_interval_seconds: 5,
  heartbeat_timeout_seconds: 20,
  created_at: '2026-09-05T08:00:00Z',
  updated_at: '2026-09-05T08:01:00Z',
  heartbeat_at: '2026-09-05T08:01:00Z',
  health_summary: { local_buffer_broker: { state: 'healthy' } },
  metadata: {},
}

describe('WorkflowRuntimeDetailsDrawer', () => {
  afterEach(() => {
    document.body.innerHTML = ''
    document.body.style.overflow = ''
  })

  it('只在详情抽屉中显示 Runtime ID、generation 和健康详情', async () => {
    const wrapper = mount(WorkflowRuntimeDetailsDrawer, {
      attachTo: document.body,
      global: { plugins: [i18n] },
      props: {
        open: true,
        runtime,
        versionLabel: 'v2',
        triggerSourceCount: 2,
      },
    })

    await flushPromises()
    const drawer = document.querySelector('[role="dialog"]') as HTMLElement
    expect(drawer.textContent).toContain('workflow-runtime-test')
    expect(drawer.textContent).toContain('Generation')
    expect(drawer.textContent).toContain('3')
    expect(drawer.textContent).toContain('local_buffer_broker')
    expect(drawer.textContent).toContain('healthy')
    expect(drawer.textContent).toContain('2')
    wrapper.unmount()
  })
})
