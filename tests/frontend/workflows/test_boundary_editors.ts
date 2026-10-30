import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {ref} from 'vue'
import BoundarySettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/BoundarySettingsEditor.vue'
import {newBoundarySettings,newBoundaryMethod,boundaryIssues} from '../../../custom_nodes/metrology3d_nodes/frontend/boundary-form'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({__esModule:true,default:{name:'CloudViewer',props:['payload','editArc'],emits:['feature-selection','arc-change'],template:'<div data-test="cloud"></div>'}}))
afterEach(()=>{document.body.innerHTML='';vi.clearAllMocks()})
it.each(['extract-boundary','fit-line','fit-circle'])('registers %s without inventing thresholds',kind=>{
  expect(trustedParameterEditor('custom.metrology3d.'+kind,'settings')).toBe(BoundarySettingsEditor)
  expect(boundaryIssues(kind,newBoundarySettings(kind))).not.toEqual([])
})
it('clears inactive method fields and keeps unknown numeric values blank',()=>{
  expect(newBoundaryMethod('projection')).toEqual({kind:'projection'})
  expect(newBoundaryMethod('section').numeric_tolerance).toBeNull()
  expect(newBoundaryMethod('contour').height).toBeNull()
})
it('closes on task/source changes and clears previous-run preview before accepting picks',async()=>{
  const state=ref({runId:'one',succeeded:true}),views=ref([{id:'v',label:'Cloud',projectId:'p',payload:{state:'ready'}}])
  const w=mount(BoundarySettingsEditor,{props:{modelValue:null,nodeType:'custom.metrology3d.fit-line'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterCloudPreviewsKey as symbol]:()=>views.value,[parameterPreviewStateKey as symbol]:()=>state.value}}})
  try{
    await w.get('button').trigger('click');await flushPromises()
    expect(document.querySelector('[data-test=cloud]')).toBeNull()
    const select=[...document.querySelectorAll('select')].find(s=>s.textContent?.includes('Cloud'))!
    select.value='v';select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    expect(document.querySelector('[data-test=cloud]')).not.toBeNull()
    state.value={runId:'two',succeeded:false};await flushPromises();expect(document.querySelector('[data-test=cloud]')).toBeNull()
    await w.setProps({inputSources:{features:[{nodeId:'read',nodeTypeId:'custom.metrology3d.read-cloud',parameters:{},outputPort:'features'}]}})
    expect(document.querySelector('[role=dialog]')).toBeNull()
    await w.get('button').trigger('click');await flushPromises()
    await w.setProps({nodeType:'custom.metrology3d.fit-circle'})
    expect(document.querySelector('[role=dialog]')).toBeNull();expect(w.emitted('update:modelValue')).toBeUndefined()
  }finally{w.unmount()}
  expect(document.querySelector('[role=dialog]')).toBeNull()
})
it('does not mark an unchanged fragment selection dirty just by opening the editor',async()=>{
  const model={...newBoundarySettings('fit-circle'),selection:{group_ids:['g'],feature_id:'b'}}
  const w=mount(BoundarySettingsEditor,{props:{modelValue:model,nodeType:'custom.metrology3d.fit-circle',inputSources:{features:[{nodeId:'b-node',nodeTypeId:'custom.metrology3d.extract-boundary',parameters:{settings:{feature_id:'b',targets:[{group_id:'g'}]}},outputPort:'features'}]}},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{await w.get('button').trigger('click');await flushPromises();expect(document.body.textContent).not.toContain('Parameters changed');expect(document.body.textContent).not.toContain('3D handle');expect(w.emitted('update:modelValue')).toBeUndefined()}finally{w.unmount()}
})

it('isolates late arc events across target, run and dialog changes without applying a draft',async()=>{
  const state=ref({runId:'run',succeeded:true}),spatial={frame_id:'fixture',length_unit:'mm'}
  const payload={state:'ready',observation_id:'obs',spatial}
  const views=ref([{id:'v',label:'Cloud',projectId:'p',payload}])
  const arc={center:[1,2],radius_range:[2,3],start_angle:0,sweep:Math.PI,max_overlap_angle:.01}
  const model={...newBoundarySettings('extract-boundary'),feature_id:'boundary',method:{kind:'projection'},evaluation:{...spatial,origin:[0,0,0],rotation:[[1,0,0],[0,1,0],[0,0,1]]},targets:[{group_id:'first',arc},{group_id:'second',arc:{...arc,center:[4,5]}}]}
  const w=mount(BoundarySettingsEditor,{props:{modelValue:model,nodeType:'custom.metrology3d.extract-boundary',inputSources:{cloud:[{nodeId:'cloud',nodeTypeId:'custom.metrology3d.read-cloud',parameters:{},outputPort:'cloud',previewOutput:{...payload,run_id:'run'}}]}},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterCloudPreviewsKey as symbol]:()=>views.value,[parameterPreviewStateKey as symbol]:()=>state.value}}})
  async function select(text:string,value:string){const input=[...document.querySelectorAll('select')].find(s=>s.parentElement?.textContent?.startsWith(text))!;input.value=value;input.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()}
  const center=()=>[...document.querySelectorAll('input')].find(i=>i.getAttribute('aria-label')==='Center 1')!.value
  try{
    await w.get('button').trigger('click');await flushPromises()
    await select('Point cloud view','v');await select('3D handle','center')
    const viewer=w.findComponent({name:'CloudViewer'}),edit=viewer.props('editArc')
    expect(edit.values.center).toEqual([1,2])
    const event={payload:viewer.props('payload'),key:edit.key,values:{...edit.values,center:[8,9]}}
    viewer.vm.$emit('arc-change',event);await flushPromises();expect(center()).toBe('8')
    await select('Target boundary','1');viewer.vm.$emit('arc-change',event);await flushPromises();expect(center()).toBe('4')
    await select('3D handle','center');expect(viewer.props('editArc').key).not.toBe(edit.key)
    state.value={runId:'next',succeeded:false};await flushPromises();viewer.vm.$emit('arc-change',event);await flushPromises();expect(center()).toBe('4')
    const cancel=[...document.querySelectorAll('button')].filter(b=>b.textContent?.trim()==='Cancel').at(-1)!
    cancel.click();await flushPromises();viewer.vm.$emit('arc-change',event);await flushPromises()
    await w.get('button').trigger('click');await flushPromises();expect(center()).toBe('1')
    expect(w.emitted('update:modelValue')).toBeUndefined();expect(model.targets[0]!.arc.center).toEqual([1,2])
  }finally{w.unmount()}
})
