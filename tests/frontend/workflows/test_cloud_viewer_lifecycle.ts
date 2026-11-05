import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { createI18n } from 'vue-i18n'
import { nextTick } from 'vue'
import {Scene,PerspectiveCamera} from 'three'
import {createGeometryOverlay} from '@/workflows/workflow-editor/point-cloud/geometry-overlay'
import CloudViewer from '@/workflows/workflow-editor/point-cloud/CloudViewer.vue'

const mocks = vi.hoisted(() => ({ capabilities: vi.fn(), decode: vi.fn(), create: vi.fn(),debug:vi.fn(),details:vi.fn(),detailBlock:vi.fn() }))
const {readFileSync}=await vi.importActual<{readFileSync:(path:string,encoding:'utf8')=>string}>('node:fs')
const {env}=await vi.importActual<{env:Record<string,string|undefined>}>('node:process')
vi.mock('@/workflows/workflow-editor/point-cloud/boundary-debug',async importOriginal=>({...await importOriginal<object>(),decodeBoundaryDebug:mocks.debug}))
beforeEach(()=>{mocks.debug.mockResolvedValue([])})
vi.mock('@/workflows/workflow-editor/services/measurement-resource.service', () => ({readCloudCapabilities:mocks.capabilities}))
vi.mock('@/workflows/workflow-editor/point-cloud/preview-data',async importOriginal=>({...await importOriginal<object>(),decodeCloudPreview:mocks.decode}))
vi.mock('@/workflows/workflow-editor/point-cloud/renderer', () => ({createCloudRenderer:(...args:unknown[])=>Object.assign({comparison:vi.fn(),voxelCell:vi.fn(),normals:vi.fn()},mocks.create(...args))}))
vi.mock('@/workflows/workflow-editor/point-cloud/asset-details', () => ({readDetailIndex:mocks.details,loadDetailBlock:mocks.detailBlock}))
const payload = {state:'ready',spatial:{length_unit:null,frame_id:'camera'},color:{mode:'solid'},source_point_count:20,display_point_count:2}
afterEach(() => vi.resetAllMocks())
function viewer() { return mount(CloudViewer, {props:{payload,projectId:'p'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}}) }
it('requires explicit normal length, keeps settings display-only and resets on source switch',async()=>{
  const scene={dispose:vi.fn(),geometry:vi.fn(),normals:vi.fn()},data={dispose:vi.fn()}
  mocks.capabilities.mockResolvedValue({renderer:{}});mocks.decode.mockResolvedValue(data);mocks.create.mockReturnValue(scene)
  const body={...payload,normal_info:{},spatial:{frame_id:'camera',length_unit:'mm'}},before=JSON.stringify(body)
  const w=mount(CloudViewer,{props:{payload:body,projectId:'p'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await flushPromises()
    const checkbox=w.findAll('label').find(l=>l.text()==='Overview normals')!.get('input')
    expect(checkbox.attributes('disabled')).toBeDefined()
    await w.get('[aria-label="Normal vector length"]').setValue(2)
    await checkbox.setValue(true);expect(scene.normals).toHaveBeenLastCalledWith({length:2,stride:1})
    await w.get('[aria-label="Normal display stride"]').setValue(3);expect(scene.normals).toHaveBeenLastCalledWith({length:2,stride:3})
    await w.get('[aria-label="Normal vector length"]').setValue('');expect(scene.normals).toHaveBeenLastCalledWith(null)
    await w.setProps({payload:{...body,observation_id:'next'}});await flushPromises()
    expect((w.get('[aria-label="Normal vector length"]').element as HTMLInputElement).value).toBe('')
    expect((checkbox.element as HTMLInputElement).checked).toBe(false)
    expect(JSON.stringify(body)).toBe(before)
  }finally{w.unmount()}
  expect(scene.dispose).toHaveBeenCalledTimes(2);expect(data.dispose).toHaveBeenCalledTimes(2)
})
it.each(['full','evidence'] as const)('renders API failure text without translation warnings or HTML in %s',async presentation=>{
  const message='Missing index <img src=x onerror=alert(1)> {source}'
  const warn=vi.spyOn(console,'warn').mockImplementation(()=>{})
  mocks.capabilities.mockRejectedValue(new Error(message))
  const w=mount(CloudViewer,{props:{payload,projectId:'p',presentation},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await flushPromises()
    expect(w.text()).toContain(message);expect(w.find('img').exists()).toBe(false)
    expect(warn).not.toHaveBeenCalled()
  }finally{w.unmount();warn.mockRestore()}
})
it('keeps the detail retry control mounted and only reloads failed metadata on explicit action',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  const data={dispose:vi.fn(),count:2,origin:[0,0,0]}
  mocks.decode.mockResolvedValue(data)
  const scenes:any[]=[]
  mocks.create.mockImplementation(()=>{
    const scene={dispose:vi.fn(),geometry:vi.fn(),activity:vi.fn(),detailBounds:vi.fn(),detailEvents:vi.fn(),detailClear:vi.fn(),detailAdd:vi.fn(),detailComplete:vi.fn(),detailVisible:()=>true}
    scenes.push(scene);return scene
  })
  let reject!:(error:Error)=>void
  mocks.details.mockImplementationOnce(()=>new Promise((_resolve,rejected)=>{reject=rejected}))
  const source={project_id:'p',resource_id:'r',version:1,kind:'point-cloud',sha256:'a'.repeat(64)}
  const w=mount(CloudViewer,{props:{payload:{...payload,source_asset:source,asset_details:{source}},projectId:'p'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await flushPromises()
    const button=w.get('[aria-label="Reload asset details"]'),element=button.element
    expect(button.attributes('disabled')).toBeDefined()
    reject(new Error('cloud_preview_invalid'));await flushPromises()
    expect(w.get('[aria-label="Reload asset details"]').element).toBe(element)
    expect(button.attributes('disabled')).toBeUndefined()
    expect(w.get('.cloud-detail-status').text()).toContain('Invalid display data')
    await w.setProps({presentation:'hidden'});await w.setProps({presentation:'view'});await flushPromises()
    expect(mocks.details).toHaveBeenCalledOnce()
    mocks.details.mockResolvedValueOnce({bounds:{min:[0,0,0],max:[1,1,1]},blocks:[]})
    await button.trigger('click');await flushPromises()
    expect(scenes[0].dispose).toHaveBeenCalledOnce();expect(data.dispose).toHaveBeenCalledOnce()
    expect(mocks.details).toHaveBeenCalledTimes(2)
    expect(button.element).toBe(element);expect(button.attributes('disabled')).toBeDefined()
    expect(w.get('.cloud-detail-status').text()).toBe('Overview')
  }finally{w.unmount()}
})
it('ignores old asset manifests and camera callbacks after payload switch and unmount',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  mocks.decode.mockImplementation(async()=>({dispose:vi.fn(),count:2,origin:[0,0,0]}))
  const scenes:any[]=[],pending:((value:unknown)=>void)[]=[]
  mocks.create.mockImplementation(()=>{
    const scene={dispose:vi.fn(),geometry:vi.fn(),detailBounds:vi.fn(),detailEvents:vi.fn(),detailClear:vi.fn(),detailAdd:vi.fn(),detailComplete:vi.fn(),detailVisible:()=>true}
    scenes.push(scene);return scene
  })
  mocks.details.mockImplementation(()=>new Promise(resolve=>pending.push(resolve)))
  const source={project_id:'p',resource_id:'r',version:1,kind:'point-cloud',sha256:'a'.repeat(64)}
  const body={...payload,source_asset:source,asset_details:{source}},index={bounds:{min:[0,0,0],max:[1,1,1]},blocks:[]}
  const w=mount(CloudViewer,{props:{payload:body,projectId:'p'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await flushPromises();await w.setProps({payload:{...body,observation_id:'two'}});await flushPromises()
    pending[0]!(index);await flushPromises();expect(scenes[0].detailEvents).not.toHaveBeenCalled()
    pending[1]!(index);await flushPromises();const oldChanged=scenes[1].detailEvents.mock.calls[0][0]
    await w.setProps({payload:{...body,observation_id:'three'}});await flushPromises()
    pending[2]!(index);await flushPromises();const calls=scenes[2].detailClear.mock.calls.length
    oldChanged();expect(scenes[2].detailClear).toHaveBeenCalledTimes(calls)
    const latest=scenes[2].detailEvents.mock.calls[0][0]
    w.unmount();const closed=scenes[2].detailClear.mock.calls.length
    latest();expect(scenes[2].detailClear).toHaveBeenCalledTimes(closed)
    expect(mocks.details.mock.calls.every(call=>call[1].aborted)).toBe(true)
    expect(mocks.detailBlock).not.toHaveBeenCalled()
  }finally{if(w.exists())w.unmount()}
})
it('applies Z display ranges without changing the payload, isolates visibility, and ignores late scale updates',async()=>{
  const scene={dispose:vi.fn(),geometry:vi.fn(),colors:vi.fn(),evidenceVisibility:vi.fn(),axesVisible:vi.fn()}
  mocks.capabilities.mockResolvedValue({renderer:{}});mocks.decode.mockResolvedValue({dispose:vi.fn()});mocks.create.mockReturnValue(scene)
  const body={...payload,bounds:{min:[0,0,-3],max:[1,1,7]}},before=JSON.stringify(body)
  const w=mount(CloudViewer,{props:{payload:body,projectId:'p'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await flushPromises();const options=mocks.create.mock.calls[0]![7];expect(options.coordinateColor).toBe(true)
    const bounds=w.findAll('input.color-bound'),geometryCalls=scene.geometry.mock.calls.length
    await bounds[0]!.setValue(9);expect(bounds[0]!.attributes('aria-invalid')).toBe('true');expect(w.get('.cloud-color-scale').text()).toContain('-3')
    await bounds[1]!.setValue(10);expect(scene.colors).toHaveBeenLastCalledWith(null,'coordinate-z',{min:9,max:10})
    await w.get('[aria-label="Reset color range"]').trigger('click');expect(scene.colors).toHaveBeenLastCalledWith(null,'coordinate-z',{min:-3,max:7})
    const overlay=w.findAll('label').find(l=>l.text()==='Measurement overlays')!.get('input')
    await overlay.setValue(false);expect(scene.evidenceVisibility).toHaveBeenLastCalledWith(false);expect(scene.geometry).toHaveBeenCalledTimes(geometryCalls)
    options.scaleChanged({value:10,pixels:100});await nextTick();expect(w.find('.cloud-scale-bar').exists()).toBe(true)
    await w.setProps({payload:{...body,observation_id:'next'}});await flushPromises();options.scaleChanged({value:999,pixels:100});await nextTick();expect(w.find('.cloud-scale-bar').exists()).toBe(false)
    expect(JSON.stringify(body)).toBe(before)
  }finally{w.unmount()}
})
it.skipIf(!env.AMVISION_I2_DISPLAY)('switches complete captured evidence through the viewer and the actual overlay',async()=>{
  const {webcrypto}=await vi.importActual<{webcrypto:Crypto}>('node:crypto');vi.stubGlobal('crypto',webcrypto)
  const decoder=await vi.importActual<typeof import('@/workflows/workflow-editor/point-cloud/boundary-debug')>('@/workflows/workflow-editor/point-cloud/boundary-debug')
  const preview=await vi.importActual<typeof import('@/workflows/workflow-editor/point-cloud/preview-data')>('@/workflows/workflow-editor/point-cloud/preview-data')
  const body=JSON.parse(readFileSync(env.AMVISION_I2_DISPLAY!,'utf8'))
  const policy={max_points:1_000_000,max_data_bytes:32*1024**2,max_cpu_bytes:128*1024**2,max_gpu_bytes:64*1024**2,max_canvas_pixels:4_000_000,max_position_error:.001}
  mocks.capabilities.mockResolvedValue({renderer:policy});mocks.debug.mockImplementation(decoder.decodeBoundaryDebug)
  mocks.decode.mockImplementation(preview.decodeCloudPreview)
  mocks.create.mockImplementation((host,data)=>{
    const overlay=createGeometryOverlay(new Scene(),new PerspectiveCamera(),host,data.origin,policy,()=>{},()=>{},e=>{throw e})
    return {dispose:overlay.dispose,geometry:overlay.update,activity:overlay.activity,roiVisibility:overlay.visibility}
  })
  const w=mount(CloudViewer,{props:{payload:body,projectId:'full-sample',presentation:'evidence'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await vi.waitFor(()=>expect(mocks.create).toHaveBeenCalledOnce(),{timeout:30000})
    await flushPromises()
    await w.findAll('[role=tab]').find(t=>t.text()==='Extraction debug')!.trigger('click')
    const select=w.get('.debug-summary select'),options=select.findAll('option')
    for(const option of options){await select.setValue(option.attributes('value'));await flushPromises()}
    await w.setProps({presentation:'hidden'});await w.setProps({presentation:'view'});await flushPromises()
    expect(mocks.decode).toHaveBeenCalledOnce();expect(mocks.debug).toHaveBeenCalledOnce();expect(mocks.create).toHaveBeenCalledOnce()
  }finally{w.unmount()}
  expect(preview.rendererUsage()).toEqual({cpuBytes:0,gpuBytes:0})
},60000)
it('switches presentation on a single decoded scene and delays first hidden load',async()=>{
  const scene={dispose:vi.fn(),geometry:vi.fn(),activity:vi.fn()},data={dispose:vi.fn()}
  mocks.capabilities.mockResolvedValue({renderer:{}});mocks.decode.mockResolvedValue(data);mocks.create.mockReturnValue(scene)
  const w=mount(CloudViewer,{props:{payload,projectId:'p',presentation:'hidden'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  await flushPromises();expect(mocks.decode).not.toHaveBeenCalled()
  await w.setProps({presentation:'view'});await flushPromises();expect(mocks.create).toHaveBeenCalledOnce()
  const geometryCalls=scene.geometry.mock.calls.length
  for(const presentation of ['hidden','evidence','view','full'] as const){await w.setProps({presentation});await flushPromises()}
  expect(mocks.decode).toHaveBeenCalledOnce();expect(mocks.debug).toHaveBeenCalledOnce();expect(mocks.create).toHaveBeenCalledOnce()
  expect(scene.geometry).toHaveBeenCalledTimes(geometryCalls);expect(scene.activity).toHaveBeenLastCalledWith(true)
  await w.setProps({presentation:'hidden'});w.unmount();await flushPromises()
  expect(data.dispose).toHaveBeenCalledOnce();expect(scene.dispose).toHaveBeenCalledOnce()
})

it('does not retry a context failure merely by switching tabs',async()=>{
  const scene={dispose:vi.fn(),geometry:vi.fn(),activity:vi.fn()}
  mocks.capabilities.mockResolvedValue({renderer:{}});mocks.decode.mockResolvedValue({dispose:vi.fn()});mocks.create.mockReturnValue(scene)
  const w=viewer();await flushPromises();mocks.create.mock.calls[0]![4](new Error('cloud_context_lost'))
  await w.setProps({presentation:'hidden'});await w.setProps({presentation:'evidence'});await flushPromises()
  expect(mocks.create).toHaveBeenCalledOnce();expect(w.get('[role=alert]').text()).toContain('WebGL context lost');w.unmount()
})
it('selects another captured evidence through the rendered selector without decoding again',async()=>{
  const scene={dispose:vi.fn(),geometry:vi.fn(),activity:vi.fn()},record=(id:string)=>({id,featureId:id,nodeId:id,state:'ready',complete:true,grid:null,arrays:{},targets:[],dispose:vi.fn()})
  mocks.capabilities.mockResolvedValue({renderer:{}});mocks.decode.mockResolvedValue({dispose:vi.fn()});mocks.create.mockReturnValue(scene)
  const records=[record('S2'),record('A_top_L')];mocks.debug.mockResolvedValue(records)
  const w=mount(CloudViewer,{props:{payload,projectId:'evidence-test',presentation:'evidence'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await flushPromises()
    expect(mocks.capabilities.mock.calls.map(c=>c[0])).toEqual(['evidence-test'])
    expect(mocks.debug).toHaveBeenCalledOnce();expect(mocks.create).toHaveBeenCalledOnce()
    await w.get('.debug-summary select').setValue('A_top_L');await flushPromises()
    expect(scene.geometry.mock.lastCall![0].debug).toBe(records[1])
    await w.setProps({presentation:'view'});await w.setProps({presentation:'evidence'});await flushPromises()
    expect((w.get('.debug-summary select').element as HTMLSelectElement).value).toBe('A_top_L')
    expect(mocks.debug).toHaveBeenCalledOnce()
  }finally{w.unmount()}
})
it('uses only the visibility channel and rejects ROI callbacks after scope switch or unmount',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}});mocks.decode.mockResolvedValue({dispose:vi.fn()})
  const renderer={dispose:vi.fn(),geometry:vi.fn(),roiVisibility:vi.fn()};mocks.create.mockReturnValue(renderer)
  const roi={roi_id:'r',frame_id:'camera',length_unit:'mm',kind:'box',geometry:{}}
  const changed=vi.fn(),wrapper=mount(CloudViewer,{props:{payload,projectId:'p',editRois:[roi],selectedRoiId:'r',roiScope:'one',onRoiChange:changed},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}});await flushPromises()
  const before=renderer.geometry.mock.calls.length,old=renderer.geometry.mock.lastCall![0].changed
  await wrapper.setProps({hiddenRoiIds:new Set(['r'])});await flushPromises()
  expect(renderer.roiVisibility).toHaveBeenLastCalledWith(new Set(['r']));expect(renderer.geometry).toHaveBeenCalledTimes(before)
  expect(mocks.decode).toHaveBeenCalledOnce();old(roi);expect(wrapper.emitted('roi-change')).toHaveLength(1)
  await wrapper.setProps({roiScope:'two'});old(roi);expect(wrapper.emitted('roi-change')).toHaveLength(1)
  const latest=renderer.geometry.mock.lastCall![0].changed;wrapper.unmount();latest(roi);expect(changed).toHaveBeenCalledOnce()
})

it('offers shared readonly ROI controls without making results editable or changing the payload',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}});mocks.decode.mockResolvedValue({dispose:vi.fn()})
  const renderer={dispose:vi.fn(),geometry:vi.fn(),roiVisibility:vi.fn()};mocks.create.mockReturnValue(renderer)
  const roi=(id:string,kind='box',geometry={})=>({roi_id:id,kind,geometry,frame_id:'camera',length_unit:'mm'})
  const body={...payload,geometry:{format_id:'amvision.geometry-preview.v1',curves:[],planes:[],rois:[roi('a'),roi('b'),roi('all','union',{roi_ids:['a','b']})]}},before=JSON.stringify(body)
  const wrapper=viewer();await wrapper.setProps({payload:body});await flushPromises()
  await wrapper.get('[aria-label="Measurement and quality details"]').trigger('click')
  await wrapper.get('[aria-label="Hide region · a"]').trigger('click')
  expect(wrapper.get('[aria-label="Partly visible; show all · all"]').attributes('aria-pressed')).toBe('mixed')
  expect(wrapper.find('[aria-label="Move ROI"]').exists()).toBe(false)
  expect(JSON.stringify(body)).toBe(before);expect(wrapper.emitted('roi-change')).toBeUndefined()
  await wrapper.setProps({projectId:'another-project'});await flushPromises()
  expect(wrapper.find('[aria-label="Hide region · a"]').exists()).toBe(true)
  await wrapper.get('[aria-label="Hide region · a"]').trigger('click')
  await wrapper.setProps({payload:{...body,observation_id:'new'}});await flushPromises()
  expect(wrapper.find('[aria-label="Hide region · a"]').exists()).toBe(true);wrapper.unmount()
})
it('disposes late debug attachments after replacement and unmount without installing an old scene',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  mocks.decode.mockImplementation(async()=>({dispose:vi.fn()}))
  const pending:((v:unknown)=>void)[]=[]
  mocks.debug.mockImplementation(()=>new Promise(resolve=>pending.push(resolve)))
  const wrapper=viewer();await flushPromises()
  await wrapper.setProps({payload:{...payload,cloud_id:'new'}});await flushPromises()
  const first={dispose:vi.fn()},last={dispose:vi.fn()}
  pending[0]!([first]);await flushPromises();expect(first.dispose).toHaveBeenCalledOnce();expect(mocks.create).not.toHaveBeenCalled()
  wrapper.unmount();pending[1]!([last]);await flushPromises();expect(last.dispose).toHaveBeenCalledOnce();expect(mocks.create).not.toHaveBeenCalled()
})
it('keeps the main renderer when a debug attachment cannot decode',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}});mocks.decode.mockResolvedValue({dispose:vi.fn()});mocks.debug.mockRejectedValue(new Error('cloud_preview_checksum'))
  const scene={dispose:vi.fn(),geometry:vi.fn(),roiVisibility:vi.fn()};mocks.create.mockReturnValue(scene)
  const wrapper=viewer();await flushPromises();expect(mocks.create).toHaveBeenCalledOnce();expect(scene.dispose).not.toHaveBeenCalled();wrapper.unmount();expect(scene.dispose).toHaveBeenCalledOnce()
})
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
  const old={dispose:vi.fn()},current={dispose:vi.fn(),point:vi.fn()}; const renderer={dispose:vi.fn(),geometry:vi.fn(),roiVisibility:vi.fn()}
  mocks.create.mockReturnValue(renderer)
  pending[0]!(old);await flushPromises();expect(old.dispose).toHaveBeenCalledOnce();expect(mocks.create).not.toHaveBeenCalled()
  pending[1]!(current);await flushPromises();expect(mocks.create).toHaveBeenCalledOnce()
  wrapper.unmount();expect(renderer.dispose).toHaveBeenCalledOnce();expect(current.dispose).toHaveBeenCalledOnce()
})
it('reports context loss, releases CPU/GPU owners and requires explicit reopen',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  const data={dispose:vi.fn()},renderer={dispose:vi.fn(),geometry:vi.fn(),roiVisibility:vi.fn()}
  mocks.decode.mockResolvedValue(data);mocks.create.mockReturnValue(renderer)
  const wrapper=viewer();await flushPromises()
  mocks.create.mock.calls[0]![4](new Error('cloud_context_lost'));await nextTick()
  expect(wrapper.get('[role=alert]').text()).toContain('WebGL context lost')
  expect(data.dispose).toHaveBeenCalledOnce();expect(renderer.dispose).toHaveBeenCalledOnce()
  expect(mocks.create).toHaveBeenCalledOnce();wrapper.unmount()
})

it('discards an index that arrives after context loss and reopens with a new owner',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  const owners:any[]=[],scenes:any[]=[],pending:((v:unknown)=>void)[]=[]
  mocks.decode.mockImplementation(async()=>{const data={dispose:vi.fn(),count:2,origin:[0,0,0]};owners.push(data);return data})
  mocks.create.mockImplementation(()=>{const scene={dispose:vi.fn(),geometry:vi.fn(),roiVisibility:vi.fn(),detailBounds:vi.fn(),detailEvents:vi.fn(),detailClear:vi.fn()};scenes.push(scene);return scene})
  mocks.details.mockImplementation(()=>new Promise(resolve=>pending.push(resolve)))
  const source={project_id:'p',resource_id:'r',version:1,kind:'point-cloud',sha256:'a'.repeat(64)}
  const w=mount(CloudViewer,{props:{payload:{...payload,source_asset:source,asset_details:{source}},projectId:'p'},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await flushPromises();mocks.create.mock.calls[0]![4](new Error('cloud_context_lost'));await nextTick()
    pending[0]!({bounds:{min:[0,0,0],max:[1,1,1]},blocks:[]});await flushPromises()
    expect(scenes[0].detailEvents).not.toHaveBeenCalled();expect(scenes[0].dispose).toHaveBeenCalledOnce();expect(owners[0].dispose).toHaveBeenCalledOnce()
    await w.get('[title="Reopen"]').trigger('click');await flushPromises()
    pending[1]!({bounds:{min:[0,0,0],max:[1,1,1]},blocks:[]});await flushPromises()
    expect(scenes[1].detailEvents).toHaveBeenCalledOnce();expect(w.find('[role=alert]').exists()).toBe(false)
  }finally{w.unmount()}
  expect(owners[1].dispose).toHaveBeenCalledOnce();expect(scenes[1].dispose).toHaveBeenCalledOnce()
})

it('picks only explicitly and ignores callbacks from a replaced or disposed scene',async()=>{
  mocks.capabilities.mockResolvedValue({renderer:{}})
  const data={dispose:vi.fn(),point:vi.fn(()=>({sourceIndex:'4',xyz:[1,2,3],scalar:null}))}
  mocks.decode.mockResolvedValue(data);mocks.create.mockImplementation(()=>({dispose:vi.fn(),geometry:vi.fn(),roiVisibility:vi.fn()}))
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
    const scene={dispose:vi.fn(),geometry:vi.fn(),roiVisibility:vi.fn(),fit:vi.fn((axis='iso')=>changed(axis))}
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
