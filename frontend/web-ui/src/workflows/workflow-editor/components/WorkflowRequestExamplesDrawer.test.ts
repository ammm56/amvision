import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import { i18n } from '@/platform/i18n'
import WorkflowRequestExamplesDrawer from './WorkflowRequestExamplesDrawer.vue'

describe('WorkflowRequestExamplesDrawer', () => {
  afterEach(() => {
    document.body.innerHTML = ''
    document.body.style.overflow = ''
  })

  it('在同一右侧抽屉中显示 HTTP 接口和公开请求示例', async () => {
    const wrapper = mount(WorkflowRequestExamplesDrawer, {
      attachTo: document.body,
      global: { plugins: [i18n] },
      props: {
        open: true,
        endpoints: [
          'POST /api/v1/workflows/app-runtimes/runtime-1/runs',
          'POST /api/v1/workflows/app-runtimes/runtime-1/invoke',
        ],
        examples: {
          json: '{"input_bindings":{}}',
          multipartCurl: 'curl --request POST',
          dotnet: 'await client.InvokeAsync();',
        },
      },
    })

    await flushPromises()
    const drawer = document.querySelector('[role="dialog"]') as HTMLElement
    expect(drawer.textContent).toContain('接口')
    expect(drawer.textContent).toContain('/runtime-1/runs')
    expect(drawer.textContent).toContain('/runtime-1/invoke')
    expect(drawer.textContent).toContain('{"input_bindings":{}}')
    wrapper.unmount()
  })
})
