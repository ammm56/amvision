import { chooseLabel } from './select-control'
import graph from '../../../docs/examples/workflows/lithium_workpiece.template.json'
import {afterEach,expect,it} from 'vitest'
import {flushPromises,mount,type VueWrapper} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import CloudFileSettingsEditor from '../../../custom_nodes/metrology3d_nodes/frontend/CloudFileSettingsEditor.vue'
import {copyFileOptions,fileOptionsIssues,newFileOptions,newFileMapping,profiles,textLayouts,textLayoutMappings,type FileOptions} from '../../../custom_nodes/metrology3d_nodes/frontend/cloud-file-form'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'

const existing=graph.nodes.find(n=>n.node_id==='read')!.parameters.file_options as FileOptions
const mounted:VueWrapper[]=[]
afterEach(()=>{mounted.splice(0).forEach(w=>w.unmount());document.body.innerHTML=''})
function editor(value:unknown=existing,locale='en-US'){
  const w=mount(CloudFileSettingsEditor,{props:{modelValue:value,nodeType:'custom.metrology3d.read-cloud',parameters:{source:{kind:'file'}}},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale})]}})
  mounted.push(w);return w
}
const button=(name:string)=>[...document.querySelectorAll('button')].find(b=>b.textContent?.trim()===name)!
async function change(label:string,value:string){
  const container=[...document.querySelectorAll('label')].find(l=>l.firstChild?.textContent?.trim()===label)!
  const trigger=container.querySelector('.ui-select__button')
  if(trigger){await chooseLabel(trigger,({'':'Unknown',m:'m',left:'Left-handed','xyzn-whitespace':'XYZN · Positions and normals'} as Record<string,string>)[value]??value);return}
  const field=container.querySelector('input')!
  field.value=value;field.dispatchEvent(new Event('input',{bubbles:true}));await flushPromises()
}
it('registers only the Read Cloud file options and preserves the full workpiece contract',async()=>{
  expect(trustedParameterEditor('custom.metrology3d.read-cloud','file_options')).toBe(CloudFileSettingsEditor)
  expect(fileOptionsIssues(existing)).toEqual([])
  const w=editor();await w.get('button').trigger('click');await flushPromises()
  expect(document.querySelector('textarea')).toBeNull()
  expect(button('Apply').disabled).toBe(false)
  button('Apply').click();await flushPromises()
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual(existing)
})
it('does not guess units, frame, format or floating point precision for new input',()=>{
  const v=newFileOptions()
  expect(v.spatial.length_unit).toBeNull();expect(v.field_mapping[0]!.dtype).toBe('')
  expect(fileOptionsIssues(v).map(i=>i.path)).toEqual(expect.arrayContaining(['profile_id','frame_id','field_mapping.1.dtype']))
})
it('accepts all declared file profiles without removing additional PLY/PCD fields or narrowing float64',()=>{
  for(const profile of profiles){
    const v=copyFileOptions(existing);v.profile_id=profile
    v.field_mapping[0]!.dtype='float64'
    if(textLayouts[profile]){
      v.field_mapping=textLayoutMappings(profile,v.field_mapping)
      v.field_mapping.forEach(f=>{if(f.dtype==='')f.dtype='float64'})
    }else v.field_mapping.push({...newFileMapping('scalar'),target_name:'confidence',source_names:['confidence'],dtype:'uint64'})
    expect(fileOptionsIssues(v),profile).toEqual([])
    expect(v.field_mapping[0]!.dtype).toBe('float64')
  }
})
it.each([
  ['duplicate source',(v:FileOptions)=>{v.field_mapping[0]!.source_names[1]='x'}],
  ['duplicate target',(v:FileOptions)=>{v.field_mapping.push(copyFileOptions(v).field_mapping[0]!)}],
  ['reserved field type',(v:FileOptions)=>{v.field_mapping[0]!.dtype='int32'}],
  ['missing source',(v:FileOptions)=>{v.field_mapping[0]!.source_names[0]=''}],
  ['fabricated lineage',(v:FileOptions)=>{v.field_mapping.push({...newFileMapping('scalar'),target_name:'sample_origin',source_names:['origin'],dtype:'uint8'})}],
  ['unit mismatch',(v:FileOptions)=>{v.spatial.unit_source='unknown'}],
  ['axis mismatch',(v:FileOptions)=>{v.spatial.axes.definition_source='unknown'}],
  ['wrong text layout',(v:FileOptions)=>{v.profile_id='xyzn-whitespace'}],
  ['unknown fields',(v:FileOptions)=>{Object.assign(v,{legacy:true})}],
])('rejects %s',(_,mutate)=>{const v=copyFileOptions(existing);mutate(v);expect(fileOptionsIssues(v).length).toBeGreaterThan(0)})
it('edits spatial data through controls, preserving axis/unit source and original object on cancel',async()=>{
  const original=copyFileOptions(existing),w=editor()
  await w.get('button').trigger('click');await change('Length unit','m');await change('Handedness','left')
  button('Cancel').click();await flushPromises();expect(w.emitted('update:modelValue')).toBeUndefined();expect(existing).toEqual(original)
  await w.get('button').trigger('click');await change('Length unit','');button('Apply').click();await flushPromises()
  const value=w.emitted('update:modelValue')![0]![0] as FileOptions
  expect(value.spatial.length_unit).toBeNull();expect(value.spatial.unit_source).toBe('unknown')
  expect(value.spatial.axes).toEqual(existing.spatial.axes)
})
it('requires explicit confirmation before replacing text mappings',async()=>{
  const w=editor();await w.get('button').trigger('click');await change('Format and encoding','xyzn-whitespace')
  expect(button('Apply').disabled).toBe(true)
  button('Use selected text layout').click();await flushPromises();button('Replace').click();await flushPromises()
  expect(document.querySelectorAll('.mapping-row').length).toBe(2)
  expect(button('Apply').disabled).toBe(true)
  await chooseLabel(document.querySelectorAll('.mapping-row .ui-select__button')[1]!,'float64')
  button('Apply').click();await flushPromises()
  const v=w.emitted('update:modelValue')![0]![0] as FileOptions
  expect(v.field_mapping[1]!.source_names).toEqual(['nx','ny','nz']);expect(v.field_mapping[0]!.dtype).toBe('float32')
  expect(fileOptionsIssues(v)).toEqual([])
})
it('blocks asset editing and discards draft on upstream changes, model replacement and unmount',async()=>{
  const w=editor();await w.get('button').trigger('click');await change('Coordinate frame','changed')
  await w.setProps({parameters:{source:{kind:'asset',resource_id:'r',version:1}}});await flushPromises()
  expect(document.querySelector('[role=dialog]')).toBeNull();expect(w.find('button').exists()).toBe(false)
  expect(w.emitted('update:modelValue')).toBeUndefined()
  await w.setProps({parameters:{source:{kind:'file'}}});await w.get('button').trigger('click')
  await w.setProps({inputSources:{file:[]}});expect(document.querySelector('[role=dialog]')).toBeNull()
  await w.get('button').trigger('click');await w.setProps({modelValue:copyFileOptions(existing)});expect(document.querySelector('[role=dialog]')).toBeNull()
  await w.get('button').trigger('click');w.unmount();expect(document.querySelector('[role=dialog]')).toBeNull()
})
it('handles malformed saved data without silently replacing it and renders Chinese controls',async()=>{
  const w=editor({profile_id:'ply-ascii'},'zh-CN');await w.get('button').trigger('click');await flushPromises()
  expect(button('应用').disabled).toBe(true);expect(document.body.textContent).toContain('未覆盖原配置')
  button('取消').click();await flushPromises();expect(w.emitted('update:modelValue')).toBeUndefined()
})
