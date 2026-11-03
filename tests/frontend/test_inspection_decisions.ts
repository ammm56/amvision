import {describe, expect, it} from 'vitest'
import {mount} from '@vue/test-utils'
import {i18n} from '@/platform/i18n'
import {formatResultCell} from '@/shared/ui/image-viewer/result-format'
import WorkflowPreviewTable from '@/workflows/workflow-editor/components/WorkflowPreviewTable.vue'

describe('inspection decision display', () => {
  it('keeps invalid separate from NG and ordinary booleans', () => {
    for (const [state, zh, en] of [['ok','合格','OK'],['ng','超差','NG'],['invalid','无法判定','INVALID']]) {
      expect(formatResultCell(state, 'decision-state', true)).toBe(zh)
      expect(formatResultCell(state, 'decision-state', false)).toBe(en)
    }
    for (const unknown of [null, false, 0, 'OK', 'missing']) {
      expect(formatResultCell(unknown, 'decision-state', true)).toBe('未知判定')
    }
    expect(formatResultCell(false, undefined, true)).toBe('false')
    expect(formatResultCell(false, 'result', true)).toBe('NG')
  })

  it('renders all three decisions and null without changing source values', () => {
    const rows = [{state:'ok',value:1.0},{state:'ng',value:3.0},{state:'invalid',value:null}]
    const before = JSON.stringify(rows)
    const wrapper = mount(WorkflowPreviewTable, {
      props: {columns:[{key:'state',label:'判定',format:'decision-state'}, {key:'value',label:'数值'}],rows},
      global:{plugins:[i18n]},
    })
    expect(wrapper.findAll('td').map(cell => cell.text())).toEqual(['合格','1','超差','3','无法判定','—'])
    expect(JSON.stringify(rows)).toBe(before)
    wrapper.unmount()
  })
})
