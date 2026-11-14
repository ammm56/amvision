import {expect,it} from 'vitest'
import {mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import DeviationSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/DeviationSettingsEditor.vue'
import {newDeviation,deviationIssues,deviationNumericItems,deviationRecipeValidator} from '../../../custom_nodes/metrology3d_nodes/frontend/deviation-form'
import {object} from '../../../custom_nodes/metrology3d_nodes/frontend/form'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'

function valid(){const p=newDeviation();Object.assign(p,{reference_feature_id:'datum',frame_id:'fixture',length_unit:'mm',support_radius:2});p.outputs=(p.outputs as Record<string,unknown>[]).map(o=>({...o,item_id:`deviation.${o.component}`}));p.quality_policy={policy_id:'test',policy_version:1,rules:(object(p.quality_policy).rules as Record<string,unknown>[]).map(r=>({...r,unit:String(r.item_id).endsWith('_count')||String(r.item_id).endsWith('_covered')||String(r.item_id).endsWith('_cosine')?'1':'mm',lower:String(r.item_id).endsWith('_count')?3:String(r.item_id).endsWith('_covered')?1:String(r.item_id).endsWith('_cosine')?.01:null,upper:String(r.item_id).endsWith('_count')||String(r.item_id).endsWith('_covered')||String(r.item_id).endsWith('_cosine')?null:3}))};return p}
const setup=(p=valid())=>mount(DeviationSettingsEditor,{props:{modelValue:p,nodeType:'custom.metrology3d.measure-deviation'},global:{plugins:[createI18n({legacy:false,locale:'en'})],stubs:{Teleport:true,CloudViewer:true}}})
it('uses existing editor and numeric item providers with all five outputs',()=>{
  const p=valid();expect(deviationIssues(p)).toEqual([])
  expect(deviationIssues(newDeviation()).length).toBeGreaterThan(0)
  expect(trustedParameterEditor('custom.metrology3d.measure-deviation','settings')).toBe(DeviationSettingsEditor)
  expect(deviationNumericItems({parameters:{settings:p}} as never)).toHaveLength(5)
  expect(deviationRecipeValidator({parameters:{settings:p}} as never,{},true)).toContain('必须连接完整目标点云')
  p.outputs=(p.outputs as unknown[]).slice(1);expect(deviationIssues(p)).toContain('outputs')
})
it('round-trips explicit settings and does not mutate the live recipe',async()=>{
  const p=valid(),before=JSON.stringify(p),w=setup(p)
  try{await w.get('button').trigger('click');const apply=w.findAll('button').find(b=>b.text()==='Apply')!;expect(apply.attributes('disabled')).toBeUndefined();await apply.trigger('click');expect(w.emitted('update:modelValue')).toEqual([[p]]);expect(JSON.stringify(p)).toBe(before)}finally{w.unmount()}
})
it('clears extension limit on mode switch and rejects missing explicit limit',async()=>{
  const w=setup()
  try{await w.get('button').trigger('click');await w.findAll('select').find(s=>s.element.value==='measured-support')!.setValue('plane-extension');expect(w.text()).toContain('max_extension_distance');expect(w.findAll('button').find(b=>b.text()==='Apply')!.attributes('disabled')).toBeDefined();await w.findAll('select').find(s=>s.element.value==='plane-extension')!.setValue('measured-support');await w.findAll('button').find(b=>b.text()==='Apply')!.trigger('click');expect(object(object(w.emitted('update:modelValue')![0]![0]).reference_policy)).toEqual({kind:'measured-support'})}finally{w.unmount()}
})
it('does not apply stale drafts after task input changes and blocks reference errors',async()=>{
  const w=setup()
  try{await w.get('button').trigger('click');await w.setProps({inputSources:{features:[]}});expect(w.find('[role=dialog]').exists()).toBe(false);expect(w.emitted('update:modelValue')).toBeUndefined();await w.setProps({draftIssues:()=>['Missing datum']});await w.get('button').trigger('click');expect(w.findAll('button').find(b=>b.text()==='Apply')!.attributes('disabled')).toBeDefined()}finally{w.unmount()}
})
