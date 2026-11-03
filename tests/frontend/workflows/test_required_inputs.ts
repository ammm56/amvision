import { describe, expect, it } from 'vitest'
import { validateRequiredInputConnections } from '@/workflows/workflow-editor/validation/required-inputs'
import type { NodeDefinition, WorkflowGraphTemplate } from '@/workflows/workflow-editor/types'

const definitions = new Map([['crop', { input_ports: [{ name: 'cloud', required: true }, { name: 'roi', required: false }] } as NodeDefinition]])

function graph(): WorkflowGraphTemplate {
  return {
    nodes: [{ node_id: 'a', node_type_id: 'crop', enabled: true }, { node_id: 'b', node_type_id: 'crop', enabled: true }],
    edges: [{ source_node_id: 'a', source_port: 'cloud', target_node_id: 'b', target_port: 'cloud' }],
    template_inputs: [{ target_node_id: 'a', target_port: 'cloud' }],
  } as WorkflowGraphTemplate
}

describe('publication input readiness', () => {
  it('accepts explicit sources and does not require optional ports', () => {
    expect(validateRequiredInputConnections(graph(), definitions)).toBeNull()
  })
  it('locates a missing source instead of publishing an unusable version', () => {
    const template = graph()
    template.edges = []
    expect(validateRequiredInputConnections(template, definitions)?.nodeId).toBe('b')
    template.template_inputs = []
    expect(validateRequiredInputConnections(template, definitions)?.nodeId).toBe('a')
  })
  it('ignores disabled targets but does not count disabled upstream nodes', () => {
    const template = graph()
    template.nodes[1].enabled = false
    expect(validateRequiredInputConnections(template, definitions)).toBeNull()
    template.nodes[1].enabled = true
    template.nodes[0].enabled = false
    expect(validateRequiredInputConnections(template, definitions)?.nodeId).toBe('b')
  })
})
