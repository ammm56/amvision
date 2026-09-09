import { afterEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import DeploymentTransferPanel from '@/modules/deployments/components/DeploymentTransferPanel.vue'
import * as service from '@/modules/deployments/services/deployment-transfer.service'

vi.mock('@/modules/deployments/services/deployment-transfer.service', async () => {
  const original = await vi.importActual<typeof service>('@/modules/deployments/services/deployment-transfer.service')
  return { ...original, listTransfers: vi.fn(), changeTransfer: vi.fn(), uploadDeployment: vi.fn(), cancelTransfer: vi.fn(), dismissTransfer: vi.fn(), exportDeployment: vi.fn() }
})
const operation: service.DeploymentTransfer = {
  operation_id: 'op', direction: 'import', state: 'ready', analysis_revision: 'rev',
  plan: { mapping: { deployment: 'new' }, original: { deployment: 'old' }, reused: [], issues: [], can_import: true, display_name: 'fixture', device_name: 'cpu', runtime_configuration: { execution: { instance_count: 2 }, backend_options: { kind: 'default' }, lifecycle: {} } },
}
const stubs = { ConfirmDialog: { props: ['confirmLabel', 'confirmDisabled'], template: '<div><slot/><button class="confirm" :disabled="confirmDisabled" @click="$emit(\'confirm\')">{{ confirmLabel }}</button></div>' }, Teleport: true }
afterEach(() => { vi.clearAllMocks(); vi.useRealTimers() })
describe('部署包页面流程', () => {
  it('逐条清除失败记录，并丢弃清除前已经在途的列表响应', async () => {
    vi.useFakeTimers()
    const failed = { ...operation, state: 'failed', error: 'Bad CRC-32 first', plan: undefined }
    const second = { ...failed, operation_id: 'second', error: 'Bad CRC-32 second' }
    let finishRefresh!: (items: service.DeploymentTransfer[]) => void
    vi.mocked(service.listTransfers).mockResolvedValueOnce([failed, second])
      .mockReturnValueOnce(new Promise(resolve => { finishRefresh = resolve }))
      .mockResolvedValue([second])
    vi.mocked(service.dismissTransfer).mockResolvedValue(undefined)
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    ;(wrapper.vm as unknown as { beginImport(): void }).beginImport()
    await flushPromises()
    await vi.advanceTimersByTimeAsync(1500)
    const buttons = wrapper.findAll('button').filter(button => button.text() === '清除')
    expect(buttons).toHaveLength(2)
    await buttons[0]!.trigger('click')
    await flushPromises()
    expect(service.dismissTransfer).toHaveBeenCalledWith('p', 'op')
    finishRefresh([failed, second])
    await flushPromises()
    expect(wrapper.text()).not.toContain('Bad CRC-32 first')
    expect(wrapper.text()).toContain('Bad CRC-32 second')
    await vi.advanceTimersByTimeAsync(1500)
    expect(wrapper.text()).not.toContain('Bad CRC-32 first')
    wrapper.unmount()
  })
  it('清除失败保留原记录并显示可清除的请求错误', async () => {
    vi.mocked(service.listTransfers).mockResolvedValue([{ ...operation, state: 'failed', error: 'Bad CRC-32', plan: undefined }])
    vi.mocked(service.dismissTransfer).mockRejectedValue(new Error('clear failed'))
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    ;(wrapper.vm as unknown as { beginImport(): void }).beginImport()
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '清除')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Bad CRC-32')
    expect(wrapper.text()).toContain('clear failed')
    await wrapper.get('.transfer-feedback button').trigger('click')
    expect(wrapper.text()).not.toContain('clear failed')
    expect(wrapper.text()).toContain('Bad CRC-32')
    wrapper.unmount()
  })
  it('正在处理和等待核对的导入不显示清除按钮', async () => {
    vi.mocked(service.listTransfers).mockResolvedValue(['uploading', 'analyzing', 'ready', 'needs_attention', 'pending_import', 'importing'].map(state => ({ ...operation, operation_id: state, state })))
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    ;(wrapper.vm as unknown as { beginImport(): void }).beginImport()
    await flushPromises()
    expect(wrapper.findAll('button').some(button => button.text() === '清除')).toBe(false)
    wrapper.unmount()
  })
  it('切换项目后旧清除请求不能删除新项目中的记录', async () => {
    const failed = { ...operation, state: 'failed', error: 'new project error', plan: undefined }
    vi.mocked(service.listTransfers).mockResolvedValue([failed])
    let finish!: () => void
    vi.mocked(service.dismissTransfer).mockReturnValue(new Promise(resolve => { finish = resolve }))
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'old' }, global: { stubs } })
    await flushPromises()
    const vm = wrapper.vm as unknown as { beginImport(): void }
    vm.beginImport()
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '清除')!.trigger('click')
    await wrapper.setProps({ projectId: 'new' })
    await flushPromises()
    vm.beginImport()
    finish()
    await flushPromises()
    expect(wrapper.text()).toContain('new project error')
    expect(service.dismissTransfer).toHaveBeenCalledWith('old', 'op')
    wrapper.unmount()
  })
  it('切换项目后立即允许新上传，旧上传回调不能清掉新上传状态', async () => {
    vi.mocked(service.listTransfers).mockResolvedValue([])
    let finishOld!: (value: service.DeploymentTransfer) => void
    let finishNew!: (value: service.DeploymentTransfer) => void
    vi.mocked(service.uploadDeployment)
      .mockReturnValueOnce(new Promise(resolve => { finishOld = resolve }))
      .mockReturnValueOnce(new Promise(resolve => { finishNew = resolve }))
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'old' }, global: { stubs } })
    const vm = wrapper.vm as unknown as { upload(file: File): Promise<void> }
    const oldUpload = vm.upload(new File(['old'], 'old.zip'))
    await wrapper.setProps({ projectId: 'new' })
    const newUpload = vm.upload(new File(['new'], 'new.zip'))
    await flushPromises()
    expect(service.uploadDeployment).toHaveBeenCalledTimes(2)
    finishOld({ ...operation, operation_id: 'old-upload' })
    await oldUpload
    expect(wrapper.text()).toContain('new.zip')
    expect(wrapper.text()).not.toContain('old.zip')
    finishNew({ ...operation, operation_id: 'new-upload' })
    await newUpload
    wrapper.unmount()
  })
  it.each([false, true])('切换项目后丢弃旧提交结果或错误，失败：%s', async (fails) => {
    vi.mocked(service.listTransfers).mockResolvedValueOnce([structuredClone(operation)]).mockResolvedValue([])
    let finish!: (value: service.DeploymentTransfer) => void
    let reject!: (error: Error) => void
    vi.mocked(service.changeTransfer).mockReturnValue(new Promise((resolve, fail) => { finish = resolve; reject = fail }))
    const wrapper = mount(DeploymentTransferPanel, { props: { projectId: 'p' }, global: { stubs } })
    await flushPromises()
    const vm = wrapper.vm as unknown as { beginImport(): void }
    vm.beginImport()
    await flushPromises()
    await wrapper.findAll('button').find(button => button.text() === '继续导入')!.trigger('click')
    await wrapper.find('.confirm').trigger('click')
    await wrapper.setProps({ projectId: 'other-project' })
    await flushPromises()
    if (fails) reject(new Error('old project failure'))
    else finish({ ...operation, state: 'pending_import' })
    await flushPromises()
    expect(wrapper.text()).not.toContain('old project failure')
    vm.beginImport()
    expect(wrapper.emitted('chooseFile')).toHaveLength(1)
    wrapper.unmount()
  })
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
