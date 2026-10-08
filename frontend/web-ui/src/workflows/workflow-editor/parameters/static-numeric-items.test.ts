import {describe,it,expect} from 'vitest'
import {staticNumericItems} from './static-numeric-items'
import type {ParameterEditorSource} from './editor-context'
describe('static recipe items',()=>{
  it('rejects malformed saved item definitions without crashing the editor',()=>{
    const source:ParameterEditorSource={nodeId:'measure',nodeTypeId:'custom.connector.measure',outputPort:'measurements',parameters:{items:[null]}}
    expect(staticNumericItems({table:[source]},undefined)).toBeNull()
    expect(staticNumericItems({table:[{...source,nodeTypeId:'custom.connector.pin-array-locate',outputPort:'checks',parameters:{layout:{pins:[null]}}}]},undefined)).toBeNull()
    expect(staticNumericItems({table:[{...source,nodeTypeId:'custom.connector.pin-array-locate',outputPort:'checks',parameters:{layout:{pins:[],candidate_bands:[null]}}}]},undefined)).toBeNull()
  })
  it('follows explicit merge inputs and enabled saved definitions without runtime results',()=>{
    const source:ParameterEditorSource={nodeId:'measure',nodeTypeId:'custom.connector.measure',outputPort:'measurements',parameters:{unit:'millimeter',items:[{item_id:'width',kind:'width'},{item_id:'angle',kind:'angle'},{item_id:'off',kind:'width',enabled:false}]}}
    expect(staticNumericItems({table:[source]},undefined)).toEqual([{item_id:'width',unit:'millimeter'},{item_id:'angle',unit:'degrees'}])
    const merge={nodeId:'merge',nodeTypeId:'core.value.numeric-tables-merge',parameters:{}}
    expect(staticNumericItems({table:[merge]},()=>({tables:[source]}))).toHaveLength(2)
    expect(staticNumericItems({table:[merge]},()=>({tables:[merge]}))).toBeNull()
    expect(staticNumericItems({table:[merge]},()=>({tables:[source,source]}))).toBeNull()
    expect(staticNumericItems({table:[{...source,outputPort:'summary'}]},undefined)).toBeNull()
  })
})
