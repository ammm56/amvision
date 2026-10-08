import {describe,it,expect} from 'vitest'
import {reactive} from 'vue'
import {recipeIssues} from './recipe-validation'
import {trustedNumericItemProviders,trustedRecipeValidators} from './trusted-recipe-providers'
import {createPinLayout,generatePins} from '../../../../../../custom_nodes/connector_nodes/frontend/pin-layout'
import {buildMeasurementBatch} from '../../../../../../custom_nodes/connector_nodes/frontend/measurement-items'
import type {WorkflowGraphNode,WorkflowGraphEdge} from '../types'

function fixture(){
  const layout=createPinLayout();layout.pins=generatePins(1,2,[100,100],50,50,0,'normal')
  const node=(id:string,type:string,parameters:Record<string,unknown>):WorkflowGraphNode=>({node_id:id,node_type_id:type,parameters,enabled:true,ui_state:{},metadata:{}})
  const nodes=[node('pins','custom.connector.pin-array-locate',{layout}),node('measure','custom.connector.measure',{unit:'millimeter',items:buildMeasurementBatch(layout,['R1P01'],['width'])}),node('limits','core.rule.check-limits',{rules:[{item_id:'width:R1P01',unit:'millimeter',upper:1}]})]
  const edge=(from:string,port:string,to:string,target:string):WorkflowGraphEdge=>({edge_id:`${from}-${port}`,source_node_id:from,source_port:port,target_node_id:to,target_port:target,metadata:{}})
  const edges=[edge('pins','pins','measure','pins'),edge('pins','features','measure','features'),edge('measure','measurements','limits','table')]
  return {nodes,edges,layout}
}
const check=(f:ReturnType<typeof fixture>)=>recipeIssues(f.nodes,f.edges,trustedNumericItemProviders,trustedRecipeValidators,true)
describe('recipe preflight',()=>{
  it('accepts reactive valid recipes without cloning proxies or changing definitions',()=>{
    const f=reactive(fixture()),original=JSON.stringify(f)
    expect(check(f)).toEqual([]);expect(JSON.stringify(f)).toBe(original)
    const items=f.nodes[1]!.parameters.items as Record<string,unknown>[]
    delete items[0]!.pin_b
    expect(check(f)).toEqual([])
  })
  it('locates downstream broken IDs and units before save/publish',()=>{
    const f=fixture();f.layout.pins[0]!.pin_id='renamed'
    expect(check(f)).toContainEqual({nodeId:'measure',message:'width:R1P01: PIN / 端点引用无效'})
    f.nodes[2]!.parameters.rules=[{item_id:'width:R1P01',unit:'pixel',upper:1}]
    expect(check(f).some(i=>i.nodeId==='limits'&&i.message.includes('单位'))).toBe(true)
  })
  it('does not reject dynamic upstreams or disabled nodes as missing static definitions',()=>{
    const f=fixture();f.nodes[0]!.node_type_id='test.dynamic-pins';f.nodes[1]!.node_type_id='test.dynamic-measure'
    expect(check(f)).toEqual([])
    f.nodes[2]!.enabled=false;f.nodes[2]!.parameters.rules=[null]
    expect(check(f)).toEqual([])
  })
  it('detects reference version mismatch and split observations',()=>{
    const f=fixture();f.layout.reference_sha256='a'.repeat(64)
    f.nodes.push({...f.nodes[0]!,node_id:'locate',node_type_id:'custom.opencv.rigid-locate',parameters:{template_resource:{sha256:'b'.repeat(64)}}})
    f.edges.push({edge_id:'pose',source_node_id:'locate',source_port:'pose',target_node_id:'pins',target_port:'pose',metadata:{}})
    expect(check(f).some(i=>i.message.includes('模板版本不同'))).toBe(true)
    f.nodes.push({...f.nodes[0]!,node_id:'other'});f.edges[1]!.source_node_id='other'
    expect(check(f).some(i=>i.message.includes('同一节点'))).toBe(true)
  })
})
