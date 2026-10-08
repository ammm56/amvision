import {describe,it,expect} from 'vitest'
import {mount} from '@vue/test-utils'
import {i18n} from '@/platform/i18n'
import {formatResultCell} from './result-format'
import WorkflowPreviewTable from '@/workflows/workflow-editor/components/WorkflowPreviewTable.vue'
import {connectorResultReasons} from '../../../../../../custom_nodes/connector_nodes/frontend/result-reasons'

describe('explicit result formats',()=>{
  it('preserves ordinary booleans, raw precision and unknown units/reasons',()=>{
    expect(formatResultCell(true,undefined,true)).toBe('true')
    expect(formatResultCell(false,'result',true)).toBe('NG')
    expect(formatResultCell(true,'validity',false)).toBe('Valid')
    expect(formatResultCell('millimeter','unit',true)).toBe('mm')
    expect(formatResultCell('celsius','unit',true)).toBe('celsius')
    expect(formatResultCell('missing_value','reason',true)).toBe('缺少数值')
    expect(formatResultCell('custom_failure','reason',true)).toBe('custom_failure')
    expect(formatResultCell('pin_not_found','reason',true,connectorResultReasons)).toBe('未获得有效 PIN 位置')
    const value=.6900000000000001
    expect(formatResultCell(value,'value',true)).toBe('0.69')
    expect(value).toBe(.6900000000000001)
  })
  it('uses the same format in the plain table only when explicitly declared',()=>{
    const wrapper=mount(WorkflowPreviewTable,{props:{columns:[{key:'running',label:'Running'},{key:'passed',label:'Result',format:'result'},{key:'unit',label:'Unit',format:'unit'}],rows:[{running:true,passed:true,unit:'millimeter'}]},global:{plugins:[i18n]}})
    expect(wrapper.findAll('td').map(cell=>cell.text())).toEqual(['true','OK','mm'])
    wrapper.unmount()
  })
})
