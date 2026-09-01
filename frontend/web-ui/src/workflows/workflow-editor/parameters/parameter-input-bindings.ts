import type {
  NodeDefinition,
  NodeParameterInputBinding,
  NodeParameterUiField,
  NodePortDefinition,
} from '../types'

/** 读取节点声明的参数输入绑定；旧节点目录未提供字段时保持空集合。 */
export function readNodeParameterInputBindings(definition: NodeDefinition | null): NodeParameterInputBinding[] {
  return definition?.parameter_input_bindings ?? []
}

/** 按参数名查找绑定，供参数编辑器把端口显示到对应输入框旁。 */
export function findNodeParameterInputBinding(
  definition: NodeDefinition | null,
  parameterName: string,
): NodeParameterInputBinding | null {
  return readNodeParameterInputBindings(definition).find((binding) => binding.parameter_name === parameterName) ?? null
}

/** 按输入端口名查找绑定，供连线坐标和普通端口列表使用。 */
export function findNodeParameterInputBindingByPort(
  definition: NodeDefinition | null,
  inputPortName: string,
): NodeParameterInputBinding | null {
  return readNodeParameterInputBindings(definition).find((binding) => binding.input_port_name === inputPortName) ?? null
}

/** 读取参数对应的真实 value.v1 输入端口；目录不完整时安全退回普通参数输入框。 */
export function readNodeParameterInputPort(
  definition: NodeDefinition | null,
  parameterName: string,
): NodePortDefinition | null {
  const binding = findNodeParameterInputBinding(definition, parameterName)
  if (!binding) return null
  return definition?.input_ports.find((port) => port.name === binding.input_port_name) ?? null
}

/** 只有可见参数字段才在输入框旁渲染端口；隐藏字段的端口仍保留在普通端口区。 */
export function readRenderedParameterInputPortNames(
  definition: NodeDefinition | null,
  fields: NodeParameterUiField[],
): Set<string> {
  const visibleParameterNames = new Set(fields.filter((field) => !field.hidden).map((field) => field.parameter_name))
  return new Set(readNodeParameterInputBindings(definition)
    .filter((binding) => visibleParameterNames.has(binding.parameter_name))
    .filter((binding) => definition?.input_ports.some((port) => port.name === binding.input_port_name))
    .map((binding) => binding.input_port_name))
}

/** 返回仍应显示在节点顶部端口区的输入端口。 */
export function readRegularNodeInputPorts(
  definition: NodeDefinition | null,
  inputPorts: NodePortDefinition[],
  fields: NodeParameterUiField[],
): NodePortDefinition[] {
  const renderedParameterPorts = readRenderedParameterInputPortNames(definition, fields)
  return inputPorts.filter((port) => !renderedParameterPorts.has(port.name))
}
