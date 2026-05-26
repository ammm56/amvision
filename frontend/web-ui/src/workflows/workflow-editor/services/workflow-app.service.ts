import type { PaginatedResult } from '@/shared/api/pagination'
import { getWorkflowApplication, listWorkflowApplications, saveWorkflowApplication, type WorkflowApplicationListQuery } from './workflow-application.service'
import { getWorkflowTemplate, saveWorkflowTemplate } from './workflow-template.service'
import { listWorkflowAppRuntimes } from './workflow-runtime.service'
import type {
  FlowApplication,
  WorkflowApplicationDocument,
  WorkflowApplicationSummary,
  WorkflowAppRuntime,
  WorkflowGraphTemplate,
  WorkflowTemplateDocument,
} from '../types'

export interface WorkflowAppSummary {
  application: WorkflowApplicationSummary
  runtimes: WorkflowAppRuntime[]
  primaryRuntime: WorkflowAppRuntime | null
}

export interface WorkflowAppDocument {
  applicationDocument: WorkflowApplicationDocument
  graphDocument: WorkflowTemplateDocument
  runtimes: WorkflowAppRuntime[]
  primaryRuntime: WorkflowAppRuntime | null
}

export interface WorkflowAppListResult extends PaginatedResult<WorkflowAppSummary> {
  runtimes: WorkflowAppRuntime[]
}

export interface WorkflowAppSaveInput {
  projectId: string
  application: FlowApplication
  template: WorkflowGraphTemplate
}

export interface WorkflowAppSaveResult {
  applicationDocument: WorkflowApplicationDocument
  graphDocument: WorkflowTemplateDocument
}

function pickPrimaryRuntime(runtimes: WorkflowAppRuntime[]): WorkflowAppRuntime | null {
  return runtimes.find((runtime) => runtime.observed_state === 'running') ?? runtimes[0] ?? null
}

function groupRuntimesByApplication(runtimes: WorkflowAppRuntime[]): Map<string, WorkflowAppRuntime[]> {
  const groupedRuntimes = new Map<string, WorkflowAppRuntime[]>()
  for (const runtime of runtimes) {
    const applicationRuntimes = groupedRuntimes.get(runtime.application_id) ?? []
    applicationRuntimes.push(runtime)
    groupedRuntimes.set(runtime.application_id, applicationRuntimes)
  }
  return groupedRuntimes
}

export async function listWorkflowApps(projectId: string, query: WorkflowApplicationListQuery = {}): Promise<WorkflowAppListResult> {
  const [applicationResponse, runtimeResponse] = await Promise.all([
    listWorkflowApplications(projectId, query),
    listWorkflowAppRuntimes({ projectId, limit: 100 }),
  ])
  const runtimesByApplication = groupRuntimesByApplication(runtimeResponse.items)
  return {
    items: applicationResponse.items.map((application) => {
      const runtimes = runtimesByApplication.get(application.application_id) ?? []
      return {
        application,
        runtimes,
        primaryRuntime: pickPrimaryRuntime(runtimes),
      }
    }),
    pagination: applicationResponse.pagination,
    runtimes: runtimeResponse.items,
  }
}

export async function getWorkflowApp(projectId: string, applicationId: string): Promise<WorkflowAppDocument> {
  const [applicationDocument, runtimeResponse] = await Promise.all([
    getWorkflowApplication(projectId, applicationId),
    listWorkflowAppRuntimes({ projectId, limit: 100 }),
  ])
  const graphDocument = await getWorkflowTemplate(
    projectId,
    applicationDocument.application.template_ref.template_id,
    applicationDocument.application.template_ref.template_version,
  )
  const runtimes = runtimeResponse.items.filter((runtime) => runtime.application_id === applicationId)
  return {
    applicationDocument,
    graphDocument,
    runtimes,
    primaryRuntime: pickPrimaryRuntime(runtimes),
  }
}

export async function saveWorkflowApp(input: WorkflowAppSaveInput): Promise<WorkflowAppSaveResult> {
  const graphDocument = await saveWorkflowTemplate(input.projectId, input.template)
  const applicationDocument = await saveWorkflowApplication(input.projectId, {
    ...input.application,
    template_ref: {
      ...input.application.template_ref,
      template_id: input.template.template_id,
      template_version: input.template.template_version,
    },
  })
  return { applicationDocument, graphDocument }
}
