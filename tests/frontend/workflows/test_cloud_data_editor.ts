import { selectWithOption, chooseSelect } from './select-control'
import {afterEach,expect,it} from 'vitest'
import {mount,flushPromises} from '@vue/test-utils'
import {createI18n} from 'vue-i18n'
import Editor from '../../../custom_nodes/metrology3d_nodes/frontend/CloudDataSettingsEditor.vue'
import {cloudDataIssues,compareDecimal,sentinelValue} from '../../../custom_nodes/metrology3d_nodes/frontend/cloud-data-form'
import {trustedParameterEditor} from '@/workflows/workflow-editor/parameters/trusted-editors'
const wrappers:ReturnType<typeof mount>[]=[]
afterEach(()=>{wrappers.splice(0).forEach(w=>w.unmount());document.body.innerHTML=''})
it.each([
  ['18446744073709551614','18446744073709551615',-1],['-2','-1',-1],['1e1000','9e999',1],['1.20','1.2',0],['-0','0.0',0],['0.001','1e-2',-1],['-0.001','-1e-2',1],
])('compares decimal range %s / %s without losing precision',(a,b,result)=>expect(Math.sign(compareDecimal(a as string,b as string))).toBe(result))
it('checks fields, sentinel precision and color without inventing values',()=>{
  expect(cloudDataIssues('finite_fields',['positions','intensity'])).toEqual([])
  expect(cloudDataIssues('finite_fields',['intensity'])).not.toEqual([])
  expect(cloudDataIssues('finite_fields',['positions','positions'])).not.toEqual([])
  expect(sentinelValue('18446744073709551615')).toBe('18446744073709551615')
  expect(sentinelValue('1.25')).toBe(1.25)
  expect(cloudDataIssues('sentinels',[{field:'intensity',values:['18446744073709551615'],match:'all'}])).toEqual([])
  expect(cloudDataIssues('sentinels',[{field:'x',values:['bad'],match:'all'}])).not.toEqual([])
  const color={mode:'scalar',field:'intensity',component:0,range:{mode:'fixed',min:'18446744073709551614',max:'18446744073709551615'}}
  expect(cloudDataIssues('color',color)).toEqual([])
  expect(cloudDataIssues('color',{...color,range:{...color.range,max:color.range.min}})).not.toEqual([])
  expect(trustedParameterEditor('custom.metrology3d.cloud-preview','color')).toBe(Editor)
})
it('edits structured color and cancels without changing the recipe',async()=>{
  const value={mode:'solid'},w=mount(Editor,{props:{modelValue:value,parameterName:'color'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'zh-CN'})]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  await chooseSelect(selectWithOption(w,'scalar'),'scalar')
  expect([...document.querySelectorAll('button')].find(b=>b.textContent==='应用')!.disabled).toBe(true)
  ;[...document.querySelectorAll('button')].find(b=>b.textContent==='取消')!.click();await flushPromises()
  expect(w.emitted('update:modelValue')).toBeUndefined();expect(value).toEqual({mode:'solid'})
})
it('preserves existing exact sentinel values on apply and closes when sources change',async()=>{
  const value=[{field:'intensity',values:['18446744073709551615'],match:'any'}]
  const w=mount(Editor,{props:{modelValue:value,parameterName:'sentinels'},attachTo:document.body,global:{plugins:[createI18n({legacy:false,locale:'en-US'})]}});wrappers.push(w)
  await w.get('button').trigger('click');await flushPromises()
  ;[...document.querySelectorAll('button')].find(b=>b.textContent==='Apply')!.click();await flushPromises()
  expect(w.emitted('update:modelValue')?.[0]?.[0]).toEqual(value)
  await w.get('button').trigger('click');await w.setProps({inputSources:{cloud:[{nodeId:'new',nodeTypeId:'custom.metrology3d.read-cloud',parameters:{}}]}});await flushPromises()
  expect(document.querySelector('[role=dialog]')).toBeNull()
})
