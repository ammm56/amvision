import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DeploymentTransferPanel from '@/modules/deployments/components/DeploymentTransferPanel.vue'
import * as service from '@/modules/deployments/services/deployment-transfer.service'

vi.mock('@/modules/deployments/services/deployment-transfer.service', async () => {
  const original = await vi.importActual<typeof service>('@/modules/deployments/services/deployment-transfer.service')
  return { ...original, listTransfers: vi.fn(), changeTransfer: vi.fn(), uploadDeployment: vi.fn(), cancelTransfer: vi.fn(), exportDeployment: vi.fn() }
})
const operation: service.DeploymentTransfer = {
  operation_id: 'op', direction: 'import', state: 'ready', analysis_revision: 'rev',
  plan: { mapping: { deployment: 'new' }, original: { deployment: 'old' }, reused: [], issues: [], can_import: true, display_name: 'fixture', device_name: 'cpu', runtime_configuration: { execution: { instance_count: 2 }, backend_options: { kind: 'default' }, lifecycle: {} } },
}
const stubs = { ConfirmDialog: { props: ['confirmLabel', 'confirmDisabled'], template: '<div><slot/><button class="confirm" :disabled="confirmDisabled" @click="$emit(\'confirm\')">{{ confirmLabel }}</button></div>' }, Teleport: true }
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers() })
describe('部署包页面流程', () => {
  it('完成记录不占页面顶部，导出记录按实例提供给操作行', async () => {
    const exported: service.DeploymentTransfer = { operation_id: 'export', direction: 'export', state: 'completed', deployment_id: 'd' }
    vi.mocked(service.listTransfers).mockResolvedValue([{ ...operation, state: 'completed' }, exported])
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    expect(wrapper.text()).toBe('')
    const vm = wrapper.vm as unknown as { exportFor(id: string): service.DeploymentTransfer | undefined; beginImport(): void }
    expect(vm.exportFor('d')).toEqual(exported)
    expect(vm.exportFor('other')).toBeUndefined()
    vm.beginImport()
    expect(wrapper.emitted('chooseFile')).toHaveLength(1)
    wrapper.unmount()
  })
  it('导入完成直接关闭对话框并请求刷新实例列表', async () => {
    vi.useFakeTimers()
    vi.mocked(service.listTransfers).mockResolvedValueOnce([structuredClone(operation)]).mockResolvedValue([{ ...operation, state: 'completed', deployment_id: 'new' }])
    vi.mocked(service.changeTransfer).mockResolvedValue({ ...operation, state: 'pending_import' })
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    ;(wrapper.vm as unknown as { beginImport(): void }).beginImport()
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '继续导入')!.trigger('click')
    await wrapper.get('.confirm').trigger('click')
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1500)
    await flushPromises()
    expect(wrapper.emitted('settled')).toHaveLength(1)
    expect(wrapper.text()).toBe('')
    wrapper.unmount()
  })
  it('上传中可以取消，并中止正在发送的请求', async () => {
    vi.mocked(service.listTransfers).mockResolvedValue([])
    let signal: AbortSignal | undefined
    vi.mocked(service.uploadDeployment).mockImplementation((_project, _file, value) => {
      signal = value
      return new Promise((_resolve, reject) => value!.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError'))))
    })
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    const uploading = (wrapper.vm as unknown as { upload(file: File): Promise<void> }).upload(new File(['zip'], 'model.zip'))
    await flushPromises()
    expect(wrapper.text()).toContain('model.zip')
    await wrapper.findAll('button').find(button => button.text() === '取消')!.trigger('click')
    await uploading
    await flushPromises()
    expect(signal?.aborted).toBe(true)
    expect(service.changeTransfer).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('上传已中止')
    wrapper.unmount()
  })
  it('修改配置必须重新分析，不能使用旧摘要直接导入', async () => {
    vi.mocked(service.listTransfers).mockResolvedValue([structuredClone(operation)])
    vi.mocked(service.changeTransfer).mockResolvedValue({ ...operation, state: 'pending_analysis' })
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    ;(wrapper.vm as unknown as { beginImport(): void }).beginImport()
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '继续导入')!.trigger('click')
    await wrapper.find('input[maxlength]').setValue('renamed')
    expect(wrapper.find('.confirm').text()).toBe('检查配置')
    await wrapper.find('.confirm').trigger('click')
    await flushPromises()
    expect(service.changeTransfer).toHaveBeenCalledWith('p', 'op', 'analyze', expect.objectContaining({ display_name: 'renamed' }))
    expect(wrapper.find('.confirm').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })
  it('已分析的配置提交稳定幂等键和当前分析版本', async () => {
    vi.mocked(service.listTransfers).mockResolvedValue([structuredClone(operation)])
    vi.mocked(service.changeTransfer).mockResolvedValue({ ...operation, state: 'pending_import' })
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    ;(wrapper.vm as unknown as { beginImport(): void }).beginImport()
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '继续导入')!.trigger('click')
    await wrapper.find('.confirm').trigger('click')
    await flushPromises()
    expect(service.changeTransfer).toHaveBeenCalledWith('p', 'op', 'commit', { analysis_revision: 'rev', idempotency_key: 'op' })
    wrapper.unmount()
  })
  it('空列表的失败仍然显示，不能因没有记录隐藏错误', async () => {
    vi.mocked(service.listTransfers).mockRejectedValue(new Error('Worker unavailable'))
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    expect(wrapper.text()).toContain('Worker unavailable')
    wrapper.unmount()
  })
  it('提交失败后重新分析，不能再次发送失效的提交', async () => {
    vi.mocked(service.listTransfers).mockResolvedValue([{ ...structuredClone(operation), state: 'failed' }])
    vi.mocked(service.changeTransfer).mockResolvedValue({ ...operation, state: 'pending_analysis' })
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    ;(wrapper.vm as unknown as { beginImport(): void }).beginImport()
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '继续导入')!.trigger('click')
    expect(wrapper.find('.confirm').text()).toBe('检查配置')
    await wrapper.find('.confirm').trigger('click')
    await flushPromises()
    expect(service.changeTransfer).toHaveBeenCalledWith('p', 'op', 'analyze', expect.any(Object))
    wrapper.unmount()
  })
})
