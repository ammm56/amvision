import {afterEach,expect,it} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import PlaneSupportEditor from '../../../custom_nodes/metrology3d_nodes/frontend/PlaneSupportEditor.vue'
import RoiEditor from '../../../custom_nodes/metrology3d_nodes/frontend/RoiEditor.vue'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
import {planeSupportIssues} from '../../../custom_nodes/metrology3d_nodes/frontend/form'
import {geometryRecipeValidator} from '../../../custom_nodes/metrology3d_nodes/frontend/recipe-validation'
import type {WorkflowGraphNode} from '@/workflows/workflow-editor/types'
const roi={kind:'parameters',roi:{roi_id:'fit-area',frame_id:'fixture',length_unit:'mm',kind:'box',geometry:{center:[0,0,3],size:[2,2,1],rotation:[[1,0,0],[0,1,0],[0,0,1]]}},bounds:[]}
const wrappers:ReturnType<typeof mount>[]=[]
afterEach(()=>{wrappers.forEach(w=>w.unmount());wrappers.length=0;document.body.innerHTML=''})
function editor(value:unknown={kind:'cloud'}){const w=mount(PlaneSupportEditor,{props:{modelValue:value},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}});wrappers.push(w);return w}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===name)!
async function mode(value:string){const select=document.querySelector('select')!;select.value=value;select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()}
it('registers the existing ROI editor without enabling an unconnected ROI input',async()=>{
  expect(trustedParameterEditor('custom.metrology3d.fit-plane','support')).toBe(PlaneSupportEditor)
  const w=editor();await w.get('button').trigger('click');await mode('parameters')
  expect(button('Apply').disabled).toBe(true)
  expect(w.getComponent(RoiEditor).props('allowInput')).toBe(false)
  w.getComponent(RoiEditor).vm.$emit('update:modelValue',roi);await flushPromises()
  expect(w.emitted('update:modelValue')).toBeUndefined()
  button('Apply').click();await flushPromises()
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual(roi)
})
it('keeps explicit support on cancel and removes all ROI configuration when whole input is applied',async()=>{
  const w=editor(roi);await w.get('button').trigger('click');await mode('cloud');button('Cancel').click();await flushPromises()
  expect(w.emitted('update:modelValue')).toBeUndefined()
  await w.get('button').trigger('click');expect(w.getComponent(RoiEditor).props('modelValue')).toEqual(roi)
  await mode('cloud');button('Apply').click();await flushPromises()
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual({kind:'cloud'})
})
it('closes nested drafts on source changes, disable and unmount without submitting',async()=>{
  const w=editor(roi);await w.get('button').trigger('click')
  await w.setProps({inputSources:{cloud:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
  await w.get('button').trigger('click');await w.setProps({disabled:true});expect(document.querySelector('[role=dialog]')).toBeNull()
  await w.setProps({disabled:false});await w.get('button').trigger('click');w.unmount()
  expect(document.querySelector('[role=dialog]')).toBeNull();expect(w.emitted('update:modelValue')).toBeUndefined()
})
it('validates support in both field and full graph checks',()=>{
  expect(planeSupportIssues(undefined)).toEqual([])
  expect(planeSupportIssues(roi)).toEqual([])
  expect(planeSupportIssues({kind:'cloud'})).toEqual([])
  for(const support of [null,{kind:'input'},{kind:'cloud',roi:roi.roi},{...roi,bounds:{}},{...roi,roi:{...roi.roi,geometry:{...roi.roi.geometry,size:[0,2,1]}}}]){
    expect(planeSupportIssues(support).length).toBeGreaterThan(0)
    const node={node_id:'plane',node_type_id:'custom.metrology3d.fit-plane',parameters:{settings:{},support},enabled:true,ui_state:{},metadata:{}} as WorkflowGraphNode
    expect(geometryRecipeValidator(node,{},false)).toEqual(expect.arrayContaining(planeSupportIssues(support)))
  }
})
it('does not silently replace a malformed null support with whole input',async()=>{
  const w=editor(null);await w.get('button').trigger('click');await flushPromises()
  expect(button('Apply').disabled).toBe(true)
  expect(w.emitted('update:modelValue')).toBeUndefined()
})
