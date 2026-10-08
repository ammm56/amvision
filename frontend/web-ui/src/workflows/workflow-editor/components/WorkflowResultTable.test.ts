import {mount} from '@vue/test-utils'
import {describe,it,expect} from 'vitest'
import {i18n} from '@/platform/i18n'
import {readResultTable,selectedResultShape,type ResultTable} from '@/shared/ui/image-viewer/result-geometry'
import WorkflowResultTable from './WorkflowResultTable.vue'
import WorkflowNodePreviewDisplay from './WorkflowNodePreviewDisplay.vue'
import type {PreviewNodeDisplay} from '../preview/useWorkflowPreviewDisplays'
const table:ResultTable={observation_id:'run-1',columns:[{key:'item_id',label:'Item'},{key:'value',label:'Value'},{key:'passed',label:'Result'}],rows:[{item_id:'width',value:.6900000000000001,passed:false},{item_id:'missing',value:null,passed:false}],result_geometry:{observation_id:'run-1',image:{width:100,height:80},items:[{item_id:'width',kind:'line',points:[[10,20],[30,20]]},{item_id:'missing',kind:'expected-point',points:[[50,50]]}]}}
describe('explicit result and image binding',()=>{
  it('rejects broken optional tables instead of crashing image display',()=>{
    expect(readResultTable(table)).toBe(table)
    for(const broken of [
      {...table,rows:[null]},
      {...table,rows:[table.rows[0],table.rows[0]]},
      {...table,columns:[null]},
      {...table,result_geometry:{...table.result_geometry,items:null}},
      {...table,result_geometry:{...table.result_geometry,image:{width:0,height:80}}},
      {...table,result_geometry:{...table.result_geometry,items:[{item_id:'width',kind:'line',points:[[NaN,0],[1,2]]}]}},
    ])expect(readResultTable(broken)).toBeNull()
  })
  it('does not invent geometry for absent rows or accept mismatched observations',()=>{
    expect(readResultTable({...table,observation_id:'old'})).toBeNull()
    expect(selectedResultShape(table,'absent')).toBeNull()
    expect(selectedResultShape(table,'missing')?.kind).toBe('expected-point')
  })
  it('selects fixed IDs, retains raw precision, explains expected positions and clears selection on a new observation',async()=>{
    const wrapper=mount(WorkflowResultTable,{props:{table,modelValue:'width'},global:{plugins:[i18n]}})
    expect(wrapper.get('pre').text()).toContain('0.6900000000000001')
    await wrapper.get('tr[aria-label=missing]').trigger('click')
    expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual(['missing'])
    await wrapper.setProps({modelValue:'missing'})
    expect(wrapper.text()).toMatch(/预期位置|expected position/)
    await wrapper.setProps({table:{...table,observation_id:'run-2',result_geometry:{...table.result_geometry,observation_id:'run-2'}}})
    expect(wrapper.emitted('update:modelValue')!.at(-1)).toEqual([null])
    expect(table.rows[0]!.value).toBe(.6900000000000001)
    wrapper.unmount()
  })
  it('keeps ordinary image previews unchanged and renders only the explicitly connected table',async()=>{
    const image={src:'data:image/jpeg;base64,x',title:'Image',width:100,height:80,overlays:[]}
    const display={kind:'image',outputName:'body',payload:{type:'image-preview'},image} as unknown as PreviewNodeDisplay
    const wrapper=mount(WorkflowNodePreviewDisplay,{props:{display,fallbackTitle:'Image',tooltip:''},global:{plugins:[i18n]}})
    expect(wrapper.findAll('img')).toHaveLength(1)
    expect(wrapper.find('.workflow-graph-node-preview__empty').exists()).toBe(false)
    expect(wrapper.findComponent(WorkflowResultTable).exists()).toBe(false)
    await wrapper.setProps({display:{...display,image:{...display.image!,results:table,selectedResultId:'missing'}}})
    expect(wrapper.findComponent(WorkflowResultTable).exists()).toBe(true)
    expect(wrapper.get('.result-shape--expected rect').attributes('x')).toBe('36')
    wrapper.unmount()
  })
  it('formats unit labels without changing source values',()=>{
    const rows=[{item_id:'angle',unit:'degrees'},{item_id:'width',unit:'millimeter'}]
    const wrapper=mount(WorkflowResultTable,{props:{table:{...table,columns:[{key:'unit',label:'Unit'}],rows}},global:{plugins:[i18n]}})
    expect(wrapper.findAll('tbody td').map(cell=>cell.text())).toEqual(['°','mm'])
    expect(rows[0]!.unit).toBe('degrees')
    wrapper.unmount()
  })
})
