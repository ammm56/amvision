import {afterEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import RegistrationSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/RegistrationSettingsEditor.vue'
import {newRegistration,registrationIssues} from '../../../custom_nodes/metrology3d_nodes/frontend/registration-form'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
import GeometrySummary from '@/workflows/workflow-editor/point-cloud/GeometrySummary.vue'
vi.mock('@/workflows/workflow-editor/point-cloud/CloudViewer.vue',()=>({default:{template:'<div />'}}))
afterEach(()=>{document.body.innerHTML=''})
const button=(text:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===text)!
function parameters(){return {...newRegistration(),pose_id:'local',source_frame_id:'scan',target_frame_id:'part',length_unit:'mm',initial_translation:[0,0,0],initial_rotation_degrees:[0,0,0],max_correspondence_distance:1,max_iterations:20,fitness_change:1e-6,rmse_change:1e-6,quality_policy:{policy_id:'test',policy_version:1,rules:[...Object.entries({correspondence_count:3,source_coverage:0.9,reference_coverage:0.9,observability:0.01,rank:6,converged:1}).map(([item_id,lower])=>({item_id,unit:'1',lower})),{item_id:'rms',unit:'mm',upper:0.1},{item_id:'max_residual',unit:'mm',upper:0.2}]}}}
it('requires explicit initial pose, coverage, full rank, convergence and quality units',()=>{
  expect(registrationIssues(newRegistration()).length).toBeGreaterThan(0)
  expect(registrationIssues(parameters())).toEqual([])
  for(const change of [{initial_translation:[0,null,0]},{source_frame_id:'part'},{algorithm:'auto'},{max_iterations:1.5},{unexpected:true}])expect(registrationIssues({...parameters(),...change}).length).toBeGreaterThan(0)
  const p=parameters();p.quality_policy.rules[0]={item_id:'correspondence_count',unit:'1',lower:0};expect(registrationIssues(p)).toContain('quality / correspondence_count')
})
it.each(['en-US','zh-CN'])('uses existing dialog, preserves local drafts and closes on task changes: %s',async locale=>{
  expect(trustedParameterEditor('custom.metrology3d.register-cloud','settings')).toBe(RegistrationSettingsEditor)
  const w=mount(RegistrationSettingsEditor,{props:{modelValue:parameters(),nodeType:'custom.metrology3d.register-cloud'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale})]}})
  const apply=locale==='zh-CN'?'应用':'Apply',cancel=locale==='zh-CN'?'取消':'Cancel'
  try{
    await w.get('button').trigger('click');await flushPromises();expect(button(apply).disabled).toBe(false)
    button(apply).click();await flushPromises();expect(w.emitted('update:modelValue')![0]).toEqual([parameters()])
    await w.get('button').trigger('click');button(cancel).click();await flushPromises();expect(w.emitted('update:modelValue')).toHaveLength(1)
    await w.get('button').trigger('click');await w.setProps({inputSources:{source:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
    await w.get('button').trigger('click');await w.setProps({disabled:true});expect(document.querySelector('[role=dialog]')).toBeNull()
    await w.setProps({disabled:false,modelValue:newRegistration()});await w.get('button').trigger('click');expect(button(apply).disabled).toBe(true)
  }finally{w.unmount();expect(document.querySelector('[role=dialog]')).toBeNull()}
})
it('displays local-only evidence and never reports global uniqueness',()=>{
  const w=mount(GeometrySummary,{props:{geometry:{planes:[],frame:{pose_id:'local',source_frame_id:'scan',target_frame_id:'part',state:'found',method:{method_id:'register-cloud',parameters:{algorithm:'point-to-point'}}}}},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  expect(w.text()).toContain('Global uniqueness: not evaluated');expect(w.text()).toContain('point-to-point');w.unmount()
})
