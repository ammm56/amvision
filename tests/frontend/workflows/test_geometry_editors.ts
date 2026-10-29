import {afterEach,expect,it,vi} from 'vitest'
import {flushPromises,mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {ref} from 'vue'
import RoiEditor from '../../../custom_nodes/metrology3d_nodes/frontend/RoiEditor.vue'
import GeometrySettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/GeometrySettingsEditor.vue'
import {geometryIssues,newSettings} from '../../../custom_nodes/metrology3d_nodes/frontend/form'
import {geometryRecipeValidator} from '../../../custom_nodes/metrology3d_nodes/frontend/recipe-validation'
import type {WorkflowGraphNode} from '@/workflows/workflow-editor/types'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{props:['payload','editRois'],template:'<div data-test="cloud"></div>'}}))
const roi={roi_id:'area',frame_id:'fixture',length_unit:'mm',kind:'box',geometry:{center:[1,2,3],size:[2,3,4],rotation:[[1,0,0],[0,1,0],[0,0,1]]}}
const source=()=>({kind:'parameters',roi:structuredClone(roi),bounds:[]})
const plugin=()=>createI18n({legacy:false,locale:'en-US'})
afterEach(()=>{document.body.innerHTML='';vi.clearAllMocks()})
function buttons(text:string){return [...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!}
it('applies an atomic numeric ROI draft, cancels without changes and closes on external task change',async()=>{
  const w=mount(RoiEditor,{props:{modelValue:source(),draftIssues:()=>['another node is incomplete']},attachTo:document.body,global:{plugins:[plugin()]}})
  await w.get('button').trigger('click');await flushPromises()
  const input=document.querySelector<HTMLInputElement>('input[aria-label="Center XYZ 1"]')!;input.value='9';input.dispatchEvent(new Event('input',{bubbles:true}));await flushPromises()
  expect(w.emitted('update:modelValue')).toBeUndefined();buttons('Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toBeUndefined()
  await w.get('button').trigger('click');await flushPromises();expect(document.querySelector<HTMLInputElement>('input[aria-label="Center XYZ 1"]')!.value).toBe('1')
  buttons('Apply').click();await flushPromises();expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual(source())
  await w.get('button').trigger('click');await w.setProps({modelValue:{...source(),kind:'input',roi:undefined}});expect(document.querySelector('[role=dialog]')).toBeNull();w.unmount()
})
it('requires explicit preview selection and clears it on run invalidation',async()=>{
  const state=ref({runId:'one',succeeded:true}),views=ref([{id:'v',label:'Cloud',projectId:'p',payload:{state:'ready'}}])
  const w=mount(RoiEditor,{props:{modelValue:source()},attachTo:document.body,global:{plugins:[plugin()],provide:{[parameterCloudPreviewsKey as symbol]:()=>views.value,[parameterPreviewStateKey as symbol]:()=>state.value}}})
  await w.get('button').trigger('click');await flushPromises();expect(document.querySelector('[data-test=cloud]')).toBeNull()
  const select=[...document.querySelectorAll('select')].find(e=>e.textContent?.includes('Cloud'))!;select.value='v';select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises();expect(document.querySelector('[data-test=cloud]')).not.toBeNull()
  state.value={runId:'two',succeeded:false};await flushPromises();expect(document.querySelector('[data-test=cloud]')).toBeNull();w.unmount();expect(document.querySelector('[role=dialog]')).toBeNull()
})
it('does not invent geometric quality thresholds or accept degenerate ROI recipes',()=>{
  expect(geometryIssues('fit-plane',newSettings(true))).not.toEqual([])
  expect(geometryIssues('build-frame',newSettings(false))).not.toEqual([])
  expect(geometryIssues('crop-roi',source())).toEqual([])
  const s=source();s.roi.geometry.rotation[2]=[0,0,-1];expect(geometryIssues('crop-roi',s)).not.toEqual([])
  expect(geometryIssues('crop-roi',{kind:'parameters',roi:{...roi,kind:'section-band',geometry:{origin:[0,0,0],normal:[0,0,1],thickness:2,bounds_roi_id:'missing'}},bounds:[]})).not.toEqual([])
})
it('changes RANSAC and frame modes without preserving inactive fields or filling thresholds',async()=>{
  const w=mount(GeometrySettingsEditor,{props:{modelValue:null,nodeType:'custom.metrology3d.fit-plane'},attachTo:document.body,global:{plugins:[plugin()]}})
  await w.get('button').trigger('click');await flushPromises();const select=document.querySelector('select')!;select.value='ransac-svd';select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
  expect(document.querySelector<HTMLInputElement>('input[aria-label="Inlier distance (cloud unit)"]')!.value).toBe('');expect(buttons('Apply').disabled).toBe(true)
  await w.setProps({nodeType:'custom.metrology3d.build-frame'});expect(document.querySelector('[role=dialog]')).toBeNull();w.unmount()
})

it('requires an ROI edge only in explicit input mode',()=>{
  const node:WorkflowGraphNode={node_id:'crop',node_type_id:'custom.metrology3d.crop-roi',parameters:{source:{kind:'input',bounds:[]}},enabled:true,ui_state:{},metadata:{}}
  const connected={roi:[{nodeId:'roi',nodeTypeId:'core.flow.input',parameters:{},outputPort:'value'}]}
  expect(geometryRecipeValidator(node,{},false)).toContain('Input ROI requires an input connection')
  expect(geometryRecipeValidator(node,connected,false)).toEqual([])
  node.parameters.source=source()
  expect(geometryRecipeValidator(node,{},false)).toEqual([])
  expect(geometryRecipeValidator(node,connected,false)).toContain('Parameter ROI cannot also have an input connection')
})
