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

it('picks only explicitly and ignores callbacks from a replaced or disposed scene',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  const data={dispose:vi.fn(),point:vi.fn(()=>({sourceIndex:'4',xyz:[1,2,3],scalar:null}))}
  mocks.decode.mockResolvedValue(data);mocks.create.mockImplementation(()=>({dispose:vi.fn(),geometry:vi.fn()}))
  const wrapper=viewer();await wrapper.setProps({allowPick:true});await flushPromises()
  const old=mocks.create.mock.calls[0]![3]
  old(0);expect(wrapper.emitted('candidate')).toBeUndefined()
  await wrapper.get('[aria-label="Pick candidate position"]').trigger('click')
  old(0);expect(wrapper.emitted('candidate')).toHaveLength(1)
  await wrapper.setProps({payload:{...payload,cloud_id:'new'}});await flushPromises()
  old(0);expect(wrapper.emitted('candidate')).toHaveLength(1)
  await wrapper.get('[aria-label="Pick candidate position"]').trigger('click')
  const latest=mocks.create.mock.calls.at(-1)![3]
  latest(0);expect(wrapper.emitted('candidate')).toHaveLength(2)
  const calls=data.point.mock.calls.length
  wrapper.unmount();latest(0);expect(data.point).toHaveBeenCalledTimes(calls)
})

it('uses renderer view state and rejects stale view and failure callbacks',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  const owners: {dispose:ReturnType<typeof vi.fn>}[]=[]
  const scenes: {dispose:ReturnType<typeof vi.fn>;geometry:ReturnType<typeof vi.fn>;fit:ReturnType<typeof vi.fn>}[]=[]
  mocks.decode.mockImplementation(async()=>{const owner={dispose:vi.fn()};owners.push(owner);return owner})
  mocks.create.mockImplementation((_host,_data,_policy,_pick,_failed,changed)=>{
    const scene={dispose:vi.fn(),geometry:vi.fn(),fit:vi.fn((axis='iso')=>changed(axis))}
    scenes.push(scene);changed('iso');return scene
  })
  const wrapper=viewer();await flushPromises()
  const select=wrapper.get('select option[value="free"]').element.parentElement as HTMLSelectElement
  const oldChanged=mocks.create.mock.calls[0]![5],oldFailed=mocks.create.mock.calls[0]![4]
  expect(select.value).toBe('iso')
  oldChanged('free');await nextTick();expect(select.value).toBe('free')
  select.value='z';select.dispatchEvent(new Event('change'));await nextTick()
  expect(scenes[0]!.fit).toHaveBeenLastCalledWith('z');expect(select.value).toBe('z')
  oldChanged('free');await nextTick()
  select.value='z';select.dispatchEvent(new Event('change'));await nextTick()
  expect(scenes[0]!.fit).toHaveBeenCalledTimes(2)
  await wrapper.get('[aria-label="Reset view"]').trigger('click')
  expect(select.value).toBe('iso')
  await wrapper.setProps({payload:{...payload,cloud_id:'replacement'}});await flushPromises()
  oldChanged('x');oldFailed(new Error('cloud_context_lost'));await nextTick()
  expect(select.value).toBe('iso');expect(wrapper.find('[role=alert]').exists()).toBe(false)
  expect(scenes[0]!.dispose).toHaveBeenCalledOnce();expect(owners[0]!.dispose).toHaveBeenCalledOnce()
  expect(scenes[1]!.dispose).not.toHaveBeenCalled();expect(owners[1]!.dispose).not.toHaveBeenCalled()
  const latest=mocks.create.mock.calls.at(-1)!
  wrapper.unmount();latest[5]('free');latest[4](new Error('cloud_context_lost'))
  expect(scenes[1]!.dispose).toHaveBeenCalledOnce();expect(owners[1]!.dispose).toHaveBeenCalledOnce()
})
