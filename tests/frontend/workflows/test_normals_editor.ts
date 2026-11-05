import {afterEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import {reactive} from 'vue'
import NormalsSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/NormalsSettingsEditor.vue'
import {newNormals,newNeighborhood,newOrientation,normalsValid} from '../../../custom_nodes/metrology3d_nodes/frontend/normals-form'
import {parameterCloudPreviewsKey,parameterPreviewStateKey} from '@/workflows/workflow-editor/parameters/editor-context'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{template:'<div data-test="normals-view" />'}}))
afterEach(()=>{document.body.innerHTML=''})
const valid=()=>({neighborhood:{kind:'knn',neighbors:8,support:{kind:'unrestricted'}},quality:{min_support_points:3,min_normal_gap:.01,max_rms:.01,max_surface_variation:.1},orientation:{kind:'direction',direction:[0,0,1],min_abs_cosine:.1},frame_id:'sample',length_unit:'mm',existing_normals:'reject',diagnostics:true})
const button=(text:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!
it('requires explicit quality and spatial values for all neighborhood/orientation methods',()=>{
  expect(normalsValid(newNormals())).toBe(false)
  for(const kind of ['knn','radius','hybrid'])for(const direction of ['unoriented','direction','viewpoint']){
    const p={...valid(),neighborhood:kind==='knn'?valid().neighborhood:kind==='radius'?{kind,radius:2}:{kind,radius:2,max_neighbors:10},orientation:direction==='direction'?valid().orientation:direction==='unoriented'?{kind:direction}:{kind:direction,position:[0,0,10],facing:'away',min_abs_cosine:.1}}
    expect(normalsValid(p)).toBe(true)
  }
  expect(normalsValid({...valid(),quality:{...valid().quality,min_support_points:10}})).toBe(false)
  expect(normalsValid({...valid(),orientation:{...valid().orientation,direction:[0,0,0]}})).toBe(false)
  expect(normalsValid({...valid(),neighborhood:{...valid().neighborhood,support:{kind:'bounded',max_distance:0}}})).toBe(false)
  expect(normalsValid({...valid(),quality:{...valid().quality,max_surface_variation:.34}})).toBe(false)
  expect(normalsValid({...valid(),neighborhood:{kind:'radius',radius:2,neighbors:8}})).toBe(false)
  expect(newNeighborhood('radius')).not.toHaveProperty('neighbors')
  expect(newOrientation('unoriented')).not.toHaveProperty('min_abs_cosine')
})
it('applies one settings object and discards drafts on cancel, source switch and unmount',async()=>{
  const state=reactive({runId:'one',succeeded:true})
  const w=mount(NormalsSettingsEditor,{props:{modelValue:valid(),nodeType:'custom.metrology3d.estimate-normals'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})],provide:{[parameterPreviewStateKey as symbol]:()=>state,[parameterCloudPreviewsKey as symbol]:()=>[{id:'one',label:'one',projectId:'p',payload:{}}]}}})
  try{
    await w.get('button').trigger('click');await flushPromises();expect(button('Apply').disabled).toBe(false)
    button('Apply').click();await flushPromises();expect(w.emitted('update:modelValue')![0]![0]).toEqual(valid())
    await w.get('button').trigger('click');await flushPromises()
    const n=document.querySelector('select')!;n.value='radius';n.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises();expect(button('Apply').disabled).toBe(true)
    button('Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toHaveLength(1)
    await w.get('button').trigger('click');await flushPromises()
    await w.setProps({inputSources:{cloud:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
    await w.get('button').trigger('click');w.unmount();expect(document.querySelector('[role=dialog]')).toBeNull()
  }finally{w.unmount()}
})
it('keeps malformed imported settings editable but cannot apply them',async()=>{
  const w=mount(NormalsSettingsEditor,{props:{modelValue:{...valid(),neighborhood:null,orientation:null},nodeType:'custom.metrology3d.estimate-normals'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  try{await w.get('button').trigger('click');await flushPromises();expect(button('Apply').disabled).toBe(true);expect(w.emitted('update:modelValue')).toBeUndefined()}finally{w.unmount()}
})
