import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DeploymentExportActions from '@/modules/deployments/components/DeploymentExportActions.vue'
import * as service from '@/modules/deployments/services/deployment-transfer.service'

vi.mock('@/modules/deployments/services/deployment-transfer.service', async () => ({
  ...await vi.importActual<typeof service>('@/modules/deployments/services/deployment-transfer.service'),
  exportDeployment: vi.fn(), downloadTransfer: vi.fn(),
}))
afterEach(() => vi.clearAllMocks())
const props = { projectId: 'project', deploymentId: 'deployment' }
const completed: service.DeploymentTransfer = { operation_id: 'op', direction: 'export', deployment_id: 'deployment', state: 'completed' }

describe('实例内导出操作', () => {
  it('下载紧随导出，只下载当前实例对应的包', async () => {
    const wrapper = mount(DeploymentExportActions, { props: { ...props, operation: completed } })
    expect(wrapper.findAll('button').map(item => item.text())).toEqual(['导出', '下载'])
    await wrapper.get('[data-deployment-action="download"]').trigger('click')
    await flushPromises()
    expect(service.downloadTransfer).toHaveBeenCalledWith('project', completed)
    wrapper.unmount()
  })
  it('提交和后台处理均有标准 loading，重复点击不再提交', async () => {
    let resolve!: (item: service.DeploymentTransfer) => void
    vi.mocked(service.exportDeployment).mockReturnValue(new Promise(done => { resolve = done }))
    const wrapper = mount(DeploymentExportActions, { props })
    const button = wrapper.get('[data-deployment-action="export"]')
    await button.trigger('click')
    await button.trigger('click')
    expect(button.attributes('aria-busy')).toBe('true')
    expect(service.exportDeployment).toHaveBeenCalledTimes(1)
    resolve({ ...completed, state: 'pending_export' })
    await flushPromises()
    await wrapper.setProps({ operation: { ...completed, state: 'exporting', progress_bytes: 1048576 } })
    expect(button.attributes('aria-busy')).toBe('true')
    expect(wrapper.get('[role="status"]').text()).toBe('1.0 MB')
    expect(wrapper.find('[data-deployment-action="download"]').exists()).toBe(false)
    wrapper.unmount()
  })
  it('导出失败就地显示，可直接重试', async () => {
    vi.mocked(service.exportDeployment).mockRejectedValue(new Error('missing model'))
    const wrapper = mount(DeploymentExportActions, { props })
    await wrapper.get('button').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toBe('missing model')
    expect(wrapper.get('button').attributes('disabled')).toBeUndefined()
    wrapper.unmount()
  })
})
