/** 专属编辑器只读查看显式上游连接；不改变连线或执行语义。 */
import type { InjectionKey } from 'vue'
import type { WorkflowJsonObject } from '../types'
import type { NumericItemProviders } from './static-numeric-items'

export interface ParameterEditorSource {
  nodeId: string
  nodeTypeId: string
  parameters: WorkflowJsonObject
  outputPort?: string
}

export type ParameterEditorSources = Record<string, ParameterEditorSource[]>
export const parameterEditorSourcesKey: InjectionKey<(nodeId: string) => ParameterEditorSources> =
  Symbol('workflow-parameter-sources')

/** 资源保存仅接受当前已成功完成的预览，上传/执行/失败状态均不能复用上次结果。 */
export const parameterPreviewStateKey: InjectionKey<() => {runId:string; succeeded:boolean}> = Symbol('workflow-parameter-preview-state')

export const parameterNumericItemsKey: InjectionKey<NumericItemProviders> = Symbol('workflow-numeric-item-providers')
/** 编辑时提示下游引用影响，保存/发布时统一拦截已知错误。 */
export const parameterDraftIssuesKey: InjectionKey<(nodeId:string, parameter:string, value:unknown) => string[]> = Symbol('workflow-parameter-draft-issues')
