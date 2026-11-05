import {afterEach,expect,it,vi} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import RegistrationSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/RegistrationSettingsEditor.vue'
import {newRegistration,registrationIssues,changeRegistrationMode} from '../../../custom_nodes/metrology3d_nodes/frontend/registration-form'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
import GeometrySummary from '@/workflows/workflow-editor/point-cloud/GeometrySummary.vue'
import {object,type Form} from '../../../custom_nodes/metrology3d_nodes/frontend/form'
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
function coarse(){const p=changeRegistrationMode(parameters(),'fpfh');p.search={feature_radius:2,feature_max_neighbors:40,max_correspondence_distance:0.2,edge_length_ratio:0.9,samples:3,iterations_per_trial:128,trials:3,equivalent_translation:0.01,equivalent_rotation_degrees:0.1};return p}
it('requires an explicit search budget and removes mutually exclusive initial pose fields',()=>{
  const p=coarse();expect(registrationIssues(p)).toEqual([]);expect(p).not.toHaveProperty('initial_translation')
  expect(registrationIssues({...p,initial_rotation_degrees:[0,0,0]})).toContain('unknown parameter')
  for(const change of [{trials:1},{equivalent_rotation_degrees:181},{samples:2},{confidence:0.99}])expect(registrationIssues({...p,search:{...p.search as object,...change}}).length).toBeGreaterThan(0)
  const back=changeRegistrationMode(p,'explicit');expect(back).not.toHaveProperty('search');expect(registrationIssues(back)).toContain('initial_translation');expect(back.pose_id).toBe(p.pose_id)
})
it.each(['en-US','zh-CN'])('shows search fields only for feature initialization and preserves cancel: %s',async locale=>{
  const w=mount(RegistrationSettingsEditor,{props:{modelValue:parameters(),nodeType:'custom.metrology3d.register-cloud'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale})]}})
  try{
    await w.get('button').trigger('click');const select=document.querySelector('select')!;select.value='fpfh';select.dispatchEvent(new Event('change',{bubbles:true}));await flushPromises()
    expect(document.body.textContent).toContain(locale==='zh-CN'?'搜索批数':'Search trials');expect(button(locale==='zh-CN'?'应用':'Apply').disabled).toBe(true)
    button(locale==='zh-CN'?'取消':'Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toBeUndefined()
    await w.setProps({modelValue:coarse()});await w.get('button').trigger('click');expect(button(locale==='zh-CN'?'应用':'Apply').disabled).toBe(false)
    button(locale==='zh-CN'?'应用':'Apply').click();await flushPromises();expect(w.emitted('update:modelValue')![0]).toEqual([coarse()])
  }finally{w.unmount()}
})
it('shows each rejected candidate and keeps finite-search and ambiguity semantics separate',()=>{
  const frame={pose_id:'coarse',source_frame_id:'scan',target_frame_id:'part',state:'ambiguous',reason:'ambiguous_candidates',method:{method_id:'register-cloud',scope:'feature-se3',parameters:{algorithm:'point-to-point'},search:{feature_correspondence_count:90,candidates:[{trial:0,reason:'quality_failed',quality:{usable:false}},{trial:1,reason:null,quality:{usable:true}}]}}}
  const w=mount(GeometrySummary,{props:{geometry:{planes:[],frame}},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  expect(w.text()).toContain('Multiple poses found in this search');expect(w.text()).toContain('quality_failed');expect(w.text()).toContain('Global uniqueness: not evaluated');expect(w.text()).not.toContain('No competing pose');expect(w.findAll('details')).toHaveLength(2);expect(w.findAll('details').every(d=>d.attributes('open')===undefined)).toBe(true);w.unmount()
})

function datum():Form{return {...changeRegistrationMode(parameters(),'datum'),initial_uv:[0,0],initial_angle_degrees:0,max_solver_evaluations:40,solver_tolerance:1e-10}}
it('keeps datum initialization exclusive, three-dimensional correspondence and three solver freedoms',()=>{
  const p=datum();expect(registrationIssues(p)).toEqual([]);expect(p).not.toHaveProperty('initial_translation');expect(p).not.toHaveProperty('search')
  for(const c of [{initial_uv:[0,0,0]},{initial_angle_degrees:NaN},{max_solver_evaluations:0},{solver_tolerance:0},{solver_tolerance:1},{initial_translation:[0,0,0]}])expect(registrationIssues({...p,...c}).length).toBeGreaterThan(0)
  const q=structuredClone(p);(object(q.quality_policy).rules as Form[]).find(r=>r.item_id==='datum_valid')!.lower=0;expect(registrationIssues(q)).toContain('quality / datum_valid')
  for(const mode of ['fpfh','explicit']){const back=changeRegistrationMode(p,mode);expect(back).not.toHaveProperty('initial_uv');expect(back).not.toHaveProperty('solver_tolerance');expect((object(back.quality_policy).rules as Form[]).find(r=>r.item_id==='rank')!.lower).toBe(6)}
})
it.each(['en-US','zh-CN'])('requires both datum connections and closes changed drafts: %s',async locale=>{
  const w=mount(RegistrationSettingsEditor,{props:{modelValue:datum(),nodeType:'custom.metrology3d.register-cloud'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale})]}})
  try{
    await w.get('button').trigger('click');expect(button(locale==='zh-CN'?'应用':'Apply').disabled).toBe(true);expect(document.body.textContent).toContain('source_datum')
    const connection=(nodeId:string)=>({nodeId,nodeTypeId:'custom.metrology3d.build-frame',parameters:{},outputPort:'pose'})
    await w.setProps({inputSources:{source_datum:[connection('moving-frame')],reference_datum:[connection('target-frame')]}});expect(document.querySelector('[role=dialog]')).toBeNull()
    await w.get('button').trigger('click');expect(document.body.textContent).toContain(locale==='zh-CN'?'基准坐标内初值':'Initial pose in datum coordinates');expect(button(locale==='zh-CN'?'应用':'Apply').disabled).toBe(false)
    button(locale==='zh-CN'?'应用':'Apply').click();await flushPromises();expect(w.emitted('update:modelValue')![0]).toEqual([datum()])
  }finally{w.unmount()}
})
it('shows two datum origins and does not claim globally unique alignment',()=>{
  const frame={pose_id:'datum',state:'found',method:{method_id:'register-cloud',scope:'datum-se2',parameters:{algorithm:'point-to-plane'},datum:{frames:[{pose_id:'source-table',state:'found'},{pose_id:'target-table',state:'found'}]}}}
  const w=mount(GeometrySummary,{props:{geometry:{planes:[],frame}},global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}})
  expect(w.text()).toContain('Datum constraint');expect(w.text()).toContain('source-table');expect(w.text()).toContain('target-table');expect(w.text()).toContain('Global uniqueness: not evaluated');w.unmount()
})
