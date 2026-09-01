import { describe, expect, it } from 'vitest'

import type { NodeDefinition, NodeParameterUiField, NodePortDefinition } from '../types'
import {
  findNodeParameterInputBindingByPort,
  readNodeParameterInputPort,
  readRegularNodeInputPorts,
  readRenderedParameterInputPortNames,
} from './parameter-input-bindings'

const imagePort: NodePortDefinition = {
  name: 'image',
  display_name: 'Image',
  payload_type_id: 'image-ref.v1',
  description: '',
  required: true,
  multiple: false,
  metadata: {},
}

const directoryPort: NodePortDefinition = {
  name: 'save_directory',
  display_name: 'Save Directory',
  payload_type_id: 'value.v1',
  description: '',
  required: false,
  multiple: false,
  metadata: {},
}

const field: NodeParameterUiField = {
  parameter_name: 'save_directory',
  display_name: 'Save Directory',
  description: '',
  group_id: 'save',
  order: 1,
  required: false,
  hidden: false,
  readonly: false,
  default_value: '',
  enum_options: [],
  json_schema: { type: 'string' },
}

function buildDefinition(): NodeDefinition {
  return {
    format_id: 'amvision.node-definition.v1',
    node_type_id: 'core.io.image-save',
    display_name: 'Save Image',
    category: 'I/O',
    description: '',
    implementation_kind: 'core-node',
    runtime_kind: 'python-callable',
    input_ports: [imagePort, directoryPort],
    output_ports: [],
    parameter_schema: {
      type: 'object',
      properties: { save_directory: { type: 'string' } },
    },
    parameter_ui_schema: {
      groups: [],
      fields: [field],
    },
    parameter_input_bindings: [{ parameter_name: 'save_directory', input_port_name: 'save_directory' }],
    capability_tags: [],
    runtime_requirements: {},
    metadata: {},
  }
}

describe('parameter input bindings', () => {
  it('可见参数绑定只在参数输入框旁显示，不在普通端口区重复显示', () => {
    const definition = buildDefinition()

    expect([...readRenderedParameterInputPortNames(definition, [field])]).toEqual(['save_directory'])
    expect(readRegularNodeInputPorts(definition, definition.input_ports, [field])).toEqual([imagePort])
    expect(readNodeParameterInputPort(definition, 'save_directory')).toEqual(directoryPort)
    expect(findNodeParameterInputBindingByPort(definition, 'save_directory')?.parameter_name).toBe('save_directory')
  })

  it('隐藏参数或不完整目录不会吞掉仍可使用的普通输入端口', () => {
    const definition = buildDefinition()
    const hiddenField = { ...field, hidden: true }
    const incompleteDefinition = { ...definition, input_ports: [imagePort] }

    expect(readRegularNodeInputPorts(definition, definition.input_ports, [hiddenField])).toEqual([imagePort, directoryPort])
    expect(readRegularNodeInputPorts(incompleteDefinition, [imagePort, directoryPort], [field])).toEqual([imagePort, directoryPort])
  })

  it('旧节点目录没有绑定声明时保留全部输入端口', () => {
    const definition = buildDefinition()
    delete definition.parameter_input_bindings

    expect(readRegularNodeInputPorts(definition, definition.input_ports, [field])).toEqual([imagePort, directoryPort])
    expect(readNodeParameterInputPort(definition, 'save_directory')).toBeNull()
  })
})
