import {expect,it} from 'vitest'
import {mount} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import RelationSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/RelationSettingsEditor.vue'
import {newRelation,relationIssues,relationSpace,relationNumericItems,relationRecipeValidator} from '../../../custom_nodes/metrology3d_nodes/frontend/relation-form'
import {object} from '../../../custom_nodes/metrology3d_nodes/frontend/form'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'

function valid(){const p=newRelation();p.item_id='distance';p.space={kind:'spatial',frame_id:'fixture',length_unit:'mm'};object(p.relation).reference={kind:'coordinate',position:[0,0,0]};object(p.relation).target={kind:'coordinate',position:[3,4,0]};object(p.quality_policy).policy_id='relations';return p}
it('keeps unspecified engineering limits empty and rejects unsupported combinations',()=>{
  const p=valid();expect(relationIssues(p)).toEqual([])
  for(const method of ['point-line','point-plane','line-line','line-angle','plane-angle'])expect(relationIssues(newRelation(method)).length).toBeGreaterThan(0)
  const r=object(p.relation);r.reference={kind:'source-point',source_index:-1};expect(relationIssues(p)).toContain('reference.source_index')
  const angle=newRelation('plane-angle');object(angle.relation).angle_mode='signed';expect(relationIssues(angle)).toContain('angle_mode')
  const plane=newRelation('point-plane');plane.space=relationSpace(p.space,'projection');expect(relationIssues(plane)).toContain('point-plane')
})
it('registers the existing editor/provider interfaces and keeps angle units explicit',()=>{
  expect(trustedParameterEditor('custom.metrology3d.measure-relation','settings')).toBe(RelationSettingsEditor)
  const p=valid(),source={parameters:{settings:p},nodeTypeId:'custom.metrology3d.measure-relation',nodeId:'r',portId:'measurements'}
  expect(relationNumericItems(source as never)).toEqual([{item_id:'distance',unit:'mm'}])
  object(p.relation).kind='line-angle';expect(relationNumericItems(source as never)).toEqual([{item_id:'distance',unit:'rad'}])
  const node={node_type_id:source.nodeTypeId,parameters:{settings:valid()}}
  expect(relationRecipeValidator(node as never,{},true)).toContain('必须连接一个当前点云')
})
it('opens without mutating input and closes an obsolete draft on model change',async()=>{
  const p=valid(),before=JSON.stringify(p),wrapper=mount(RelationSettingsEditor,{props:{modelValue:p,nodeType:'custom.metrology3d.measure-relation'},global:{plugins:[createI18n({legacy:false,locale:'zh-CN'})],stubs:{Teleport:true,CloudViewer:true}}})
  try{
    await wrapper.get('button').trigger('click')
    expect(wrapper.text()).toContain('点点距离')
    const input=wrapper.findAll('input').find(i=>i.element.value==='distance')!
    await input.setValue('changed')
    expect(JSON.stringify(p)).toBe(before)
    await wrapper.setProps({modelValue:{...valid(),item_id:'other'}})
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  }finally{wrapper.unmount()}
})
it('changes methods without carrying stale coverage and refuses apply while disabled',async()=>{
  const wrapper=mount(RelationSettingsEditor,{props:{modelValue:valid(),nodeType:'custom.metrology3d.measure-relation'},global:{plugins:[createI18n({legacy:false,locale:'en'})],stubs:{Teleport:true,CloudViewer:true}}})
  try{
    await wrapper.get('button').trigger('click')
    await wrapper.get('select').setValue('point-plane')
    expect(wrapper.text()).toContain('Finite measured support')
    expect(wrapper.text()).toContain('coverage')
    await wrapper.setProps({disabled:true})
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  }finally{wrapper.unmount()}
})
it('blocks a valid-looking draft when connected sources are stale or ambiguous',async()=>{
  const wrapper=mount(RelationSettingsEditor,{props:{modelValue:valid(),nodeType:'custom.metrology3d.measure-relation',draftIssues:()=>['reference feature is not in current inputs']},global:{plugins:[createI18n({legacy:false,locale:'en'})],stubs:{Teleport:true,CloudViewer:true}}})
  try{
    await wrapper.get('button').trigger('click')
    const apply=wrapper.findAll('button').find(b=>b.text()==='Apply')!
    expect(apply.attributes('disabled')).toBeDefined()
    await apply.trigger('click')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
  }finally{wrapper.unmount()}
})
