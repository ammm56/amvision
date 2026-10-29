import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {ref} from 'vue'
import DimensionSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/DimensionSettingsEditor.vue'
import {dimensionFeatureChoices,dimensionIssues,dimensionNumericItems,dimensionRecipeValidator,newDimension,newExtentMode} from '../../../custom_nodes/metrology3d_nodes/frontend/dimension-form'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'

vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({__esModule:true,default:{name:'DimensionCloud',props:['payload'],emits:['candidate','feature-selection'],template:'<div data-test="cloud"></div>'}}))
afterEach(()=>{document.body.innerHTML='';vi.clearAllMocks()})

it.each(['measure-extents','measure-edge-pair','measure-hole'])('registers %s without filling unknown numeric settings',kind=>{
  expect(trustedParameterEditor('custom.metrology3d.'+kind,'settings')).toBe(DimensionSettingsEditor)
  expect(dimensionIssues(kind,newDimension(kind))).not.toEqual([])
})
it('requires explicit rectangle tolerances and exposes every configured numeric output',()=>{
  expect(newExtentMode('minimum-area-rectangle').dimension_abs_tolerance).toBeNull()
  expect(dimensionNumericItems({nodeId:'hole',nodeTypeId:'custom.metrology3d.measure-hole',parameters:{settings:{evaluation:{length_unit:'mm'},outputs:[{component:'diameter',item_id:'diameter'},{component:'center_x',item_id:'cx'}]}}})).toEqual([{item_id:'diameter',unit:'mm'},{item_id:'cx',unit:'mm'}])
})
it('only uses connected source output for restored boundary candidates',()=>{
  const source={nodeId:'saved',nodeTypeId:'custom.metrology3d.read-cloud',parameters:{},outputPort:'features'}
  expect(dimensionFeatureChoices({features:[source]})).toEqual([])
  const output={format_id:'amvision.features3d.v1',items:[{feature_id:'saved-boundary',kind:'boundary',geometry:{segments:[{segment_id:'inner'}]}}]}
  expect(dimensionFeatureChoices({features:[{...source,previewOutput:output}]})).toEqual([{id:'saved-boundary',kind:'boundary',segments:['inner'],nodeId:'saved'}])
  expect(dimensionFeatureChoices({cloud:[{...source,previewOutput:output}]})).toEqual([])
})
it('rejects out-of-plane settings and unknown quality metric units before Apply',()=>{
  const p={...newDimension('measure-edge-pair'),evaluation:{frame_id:'fixture',length_unit:'mm',origin:[0,0,0],rotation:[[1,0,0],[0,1,0],[0,0,1]]},direction:[0,0,1],query_position:[0,0,2],max_plane_distance:.1,quality_policy:{policy_id:'q',policy_version:1,rules:[{item_id:'geometry_usable',unit:'1',lower:1},{item_id:'reference_plane_distance',unit:'rad',upper:1}]}}
  expect(dimensionIssues('measure-edge-pair',p)).toEqual(expect.arrayContaining(['direction / evaluation plane','query / evaluation plane','quality / metric unit']))
})
it('rejects wrong connected feature type and duplicate identity',()=>{
  const node={node_id:'measure',node_type_id:'custom.metrology3d.measure-hole',enabled:true,ui_state:{},metadata:{},parameters:{settings:{...newDimension('measure-hole'),feature_id:'circle'}}}
  const line={nodeId:'line',nodeTypeId:'custom.metrology3d.fit-line',parameters:{settings:{feature_id:'circle'}}}
  expect(dimensionRecipeValidator(node,{features:[line]},false)).toContain('Selected feature is not in current inputs')
  expect(dimensionRecipeValidator(node,{features:[line,{...line,nodeId:'other'}]},false)).toContain('Duplicate input feature IDs')
})
it('mode switching discards old output identities without modifying the committed configuration',async()=>{
  const value={...newDimension('measure-extents'),outputs:[{component:'u',item_id:'old-u'},{component:'v',item_id:'old-v'}]}
  const w=mount(DimensionSettingsEditor,{props:{modelValue:value,nodeType:'custom.metrology3d.measure-extents'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{
    await w.get('button').trigger('click');await flushPromises()
    const radios=[...document.querySelectorAll<HTMLInputElement>('input[name=dimension-mode]')]
    radios[1]!.checked=true;radios[1]!.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    expect(document.querySelector<HTMLInputElement>('input[aria-label="Length L ID"]')?.value).toBe('')
    expect(value.outputs[0]!.item_id).toBe('old-u')
    expect(w.emitted('update:modelValue')).toBeUndefined()
  }finally{w.unmount()}
})
it('ignores late picks after run/source switches and closes on unmount',async()=>{
  const state=ref({runId:'one',succeeded:true}),payload={state:'ready',spatial:{frame_id:'fixture',length_unit:'mm'}}
  const views=ref([{id:'v',label:'Cloud',projectId:'p',payload}])
  const value={...newDimension('measure-edge-pair'),evaluation:{frame_id:'fixture',length_unit:'mm',origin:[0,0,0],rotation:[[1,0,0],[0,1,0],[0,0,1]]}}
  const w=mount(DimensionSettingsEditor,{props:{modelValue:value,nodeType:'custom.metrology3d.measure-edge-pair'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterCloudPreviewsKey as symbol]:()=>views.value,[parameterPreviewStateKey as symbol]:()=>state.value}}})
  try{
    await w.get('button').trigger('click');await flushPromises()
    const select=[...document.querySelectorAll('select')].find(s=>s.textContent?.includes('Cloud'))!
    select.value='v';select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    const viewer=w.findComponent({name:'DimensionCloud'})
    state.value={runId:'two',succeeded:false};await flushPromises()
    viewer.vm.$emit('candidate',{payload,xyz:[9,9,9]});await flushPromises()
    expect(document.querySelector('[data-test=cloud]')).toBeNull()
    expect(w.emitted('update:modelValue')).toBeUndefined()
    await w.setProps({inputSources:{features:[{nodeId:'new',nodeTypeId:'custom.metrology3d.fit-line',parameters:{}}]}})
    expect(document.querySelector('[role=dialog]')).toBeNull()
  }finally{w.unmount()}
  expect(document.querySelector('[role=dialog]')).toBeNull()
})
