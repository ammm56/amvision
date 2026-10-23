import { afterEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { nextTick } from 'vue'
import CloudViewer from '@/workflows/workflow-editor/point-cloud/CloudViewer.vue'

const mocks = vi.hoisted(() => ({ capabilities: vi.fn(), decode: vi.fn(), create: vi.fn() }))
vi.mock('@/workflows/workflow-editor/services/measurement-resource.service', () => ({readCloudCapabilities:mocks.capabilities}))
vi.mock('@/workflows/workflow-editor/point-cloud/preview-data', () => ({decodeCloudPreview:mocks.decode,object:(v:unknown)=>v}))
vi.mock('@/workflows/workflow-editor/point-cloud/renderer', () => ({createCloudRenderer:mocks.create}))
const payload = {state:'ready',spatial:{length_unit:null,frame_id:'camera'},color:{mode:'solid'},source_point_count:20,display_point_count:2}
afterEach(() => vi.resetAllMocks())
function viewer() { return mount(CloudViewer, {props:{payload,projectId:'p'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}}) }
it('does not decode or create WebGL after unmount while capabilities are pending', async () => {
  let finish!: (value:unknown)=>void
  mocks.capabilities.mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
  const wrapper=viewer(); const signal=mocks.capabilities.mock.calls[0]![1]
  wrapper.unmount(); expect(signal.aborted).toBe(true)
  finish({renderer:{}}); await flushPromises(); expect(mocks.decode).not.toHaveBeenCalled();expect(mocks.create).not.toHaveBeenCalled()
})
it('disposes a decoded old run and does not install it after a task switch', async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  const pending: ((v:unknown)=>void)[]=[]
  mocks.decode.mockImplementation(()=>new Promise(resolve=>pending.push(resolve)))
  const wrapper=viewer();await flushPromises()
  await wrapper.setProps({payload:{...payload,cloud_id:'next'}});await flushPromises()
  const old={dispose:vi.fn()},current={dispose:vi.fn(),point:vi.fn()}; const renderer={dispose:vi.fn(),geometry:vi.fn()}
  mocks.create.mockReturnValue(renderer)
  pending[0]!(old);await flushPromises();expect(old.dispose).toHaveBeenCalledOnce();expect(mocks.create).not.toHaveBeenCalled()
  pending[1]!(current);await flushPromises();expect(mocks.create).toHaveBeenCalledOnce()
  wrapper.unmount();expect(renderer.dispose).toHaveBeenCalledOnce();expect(current.dispose).toHaveBeenCalledOnce()
})
it('reports context loss, releases CPU/GPU owners and requires explicit reopen',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  const data={dispose:vi.fn()},renderer={dispose:vi.fn(),geometry:vi.fn()}
  mocks.decode.mockResolvedValue(data);mocks.create.mockReturnValue(renderer)
  const wrapper=viewer();await flushPromises()
  mocks.create.mock.calls[0]![4](new Error('cloud_context_lost'));await nextTick()
  expect(wrapper.get('[role=alert]').text()).toContain('WebGL context lost')
  expect(data.dispose).toHaveBeenCalledOnce();expect(renderer.dispose).toHaveBeenCalledOnce()
  expect(mocks.create).toHaveBeenCalledOnce();wrapper.unmount()
})
