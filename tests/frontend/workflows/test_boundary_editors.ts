import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {ref} from 'vue'
import BoundarySettingsEditor from '../../../custom_nodes/_metrology3d_nodes/frontend/BoundarySettingsEditor.vue'
import {newBoundarySettings,newBoundaryMethod,boundaryIssues} from '../../../custom_nodes/_metrology3d_nodes/frontend/boundary-form'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({__esModule:true,default:{props:['payload'],emits:['feature-selection'],template:'<div data-test="cloud"></div>'}}))
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
