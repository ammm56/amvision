/** 专属编辑器只读查看显式上游连接；不改变连线或执行语义。 */
import type { InjectionKey } from 'vue'
import type { WorkflowJsonObject } from '../types'
import type { NumericItemProviders } from './static-numeric-items'

export interface ParameterEditorSource {
  nodeId: string
  nodeTypeId: string
  parameters: WorkflowJsonObject
  outputPort?: string
  /** 仅当前成功且未过期的 Preview 原端口输出，不作为配置持久化。 */
  previewOutput?: unknown
}

export type ParameterEditorSources = Record<string, ParameterEditorSource[]>
/** 连接或配置变化使编辑失效，Preview 输出刷新不属于配方修改。 */
export function parameterSourceSignature(sources: ParameterEditorSources | undefined): string {
  return JSON.stringify(Object.entries(sources ?? {}).map(([port, values]) => [
    port, values.map(({ nodeId, nodeTypeId, parameters, outputPort }) => ({ nodeId, nodeTypeId, parameters, outputPort })),
  ]))
}
export const parameterEditorSourcesKey: InjectionKey<(nodeId: string) => ParameterEditorSources> =
  Symbol('workflow-parameter-sources')

/** 资源保存仅接受当前已成功完成的预览，上传/执行/失败状态均不能复用上次结果。 */
export const parameterPreviewStateKey: InjectionKey<() => {runId:string; succeeded:boolean; phase?:'idle'|'running'|'failed'|'stale'|'ready';error?:string|null}> = Symbol('workflow-parameter-preview-state')

/** 仅显式选择当前成功运行的有界显示，不读取完整点云或推断输入空间。 */
export interface ParameterCloudPreview { id:string; label:string; projectId:string; payload:Record<string,unknown>; sourceNodeId?:string;sourcePort?:string }
export const parameterCloudPreviewsKey: InjectionKey<() => ParameterCloudPreview[]> = Symbol('workflow-parameter-cloud-previews')
/** 当前参数所属节点；取参不提交弹窗草稿，不修改保存图。 */
export const parameterNodeContextKey: InjectionKey<()=>{nodeId:string;cloudPorts:string[];sources:ParameterEditorSources}> = Symbol('workflow-parameter-node-context')
export const parameterInputPreviewKey: InjectionKey<(nodeId:string,inputPort:string)=>Promise<void>> = Symbol('workflow-parameter-input-preview')
export const parameterNodePreviewKey: InjectionKey<(nodeId:string)=>Promise<void>> = Symbol('workflow-parameter-node-preview')
/** 联合编辑沿用一次参数批量更新；仅在原参数未被其他操作修改时提交。 */
export const parameterBatchUpdateKey: InjectionKey<(nodeId:string,expected:WorkflowJsonObject,updates:WorkflowJsonObject)=>boolean> = Symbol('workflow-parameter-batch-update')

export const parameterNumericItemsKey: InjectionKey<NumericItemProviders> = Symbol('workflow-numeric-item-providers')
/** 编辑时提示下游引用影响，保存/发布时统一拦截已知错误。 */
export const parameterDraftIssuesKey: InjectionKey<(nodeId:string, parameter:string, value:unknown) => string[]> = Symbol('workflow-parameter-draft-issues')
