import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { i18n } from '@/platform/i18n'
import WorkflowRequestExamplesDrawer from './WorkflowRequestExamplesDrawer.vue'

describe('WorkflowRequestExamplesDrawer', () => {
  afterEach(() => {
    vi.restoreAllMocks()
    document.body.innerHTML = ''
    document.body.style.overflow = ''
  })

  it('以紧凑右侧抽屉分页显示 HTTP 接口与请求示例并支持复制', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    Object.assign(navigator, { clipboard: { writeText } })

    const wrapper = mount(WorkflowRequestExamplesDrawer, {
      attachTo: document.body,
      global: { plugins: [i18n] },
      props: {
        open: true,
        runtimeName: '工位 A',
        versionLabel: 'v3',
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
    expect(drawer.classList.contains('side-drawer--compact')).toBe(true)
    expect(drawer.textContent).toContain('接口')
    expect(drawer.textContent).toContain('工位 A')
    expect(drawer.textContent).toContain('/runtime-1/runs')
    expect(drawer.textContent).toContain('/runtime-1/invoke')
    expect(drawer.textContent).toContain('{"input_bindings":{}}')

    const curlTab = drawer.querySelector('[data-tab-id="curl"]') as HTMLButtonElement
    curlTab.click()
    await flushPromises()
    expect(drawer.textContent).toContain('curl --request POST')

    const copyBtn = drawer.querySelector('[data-request-example-copy]') as HTMLButtonElement
    copyBtn.click()
    await flushPromises()
    expect(writeText).toHaveBeenCalledWith('curl --request POST')
    wrapper.unmount()
  })
})
