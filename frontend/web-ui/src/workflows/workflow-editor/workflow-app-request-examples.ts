import type { WorkflowJsonObject } from './types'

export interface WorkflowAppRequestExamples {
  json: string
  multipartCurl: string
  dotnet: string
}

/** 只根据已发布 App Contract v2 生成公开请求示例。 */
export function buildWorkflowAppRequestExamples(
  contract: WorkflowJsonObject | null,
  workflowRuntimeId: string,
): WorkflowAppRequestExamples | null {
  if (contract?.format_id !== 'amvision.workflow-app-contract.v2' || !Array.isArray(contract.inputs)) return null
  const inputs = contract.inputs.filter(isRecord)
  const jsonBindings: WorkflowJsonObject = {}
  const multipartInlineBindings: WorkflowJsonObject = {}
  const multipartFields: string[] = []
  const dotnetCalls: string[] = []

  for (const input of inputs) {
    const bindingId = readText(input.binding_id)
    const payloadTypeId = readText(input.payload_type_id)
    if (!bindingId || !payloadTypeId) continue
    const sample = buildJsonSample(payloadTypeId)
    if (sample !== undefined) jsonBindings[bindingId] = sample
    if (payloadTypeId === 'value.v1' || payloadTypeId === 'text.v1' || payloadTypeId === 'image-base64.v1') {
      if (sample !== undefined) multipartInlineBindings[bindingId] = sample
    }
    if (payloadTypeId === 'image-ref.v1') {
      multipartFields.push(`  -F '${bindingId}=@sample.png;type=image/png'`)
      dotnetCalls.push(`    .AddImage("${escapeCSharp(bindingId)}", () => File.OpenRead("sample.png"), "sample.png", "image/png")`)
    } else if (payloadTypeId === 'file-ref.v1') {
      multipartFields.push(`  -F '${bindingId}=@sample.bin;type=application/octet-stream'`)
      dotnetCalls.push(`    .AddFile("${escapeCSharp(bindingId)}", () => File.OpenRead("sample.bin"), "sample.bin", "application/octet-stream")`)
    } else if (payloadTypeId === 'file-refs.v1') {
      multipartFields.push(
        `  -F '${bindingId}=@first.bin;type=application/octet-stream'`,
        `  -F '${bindingId}=@second.bin;type=application/octet-stream'`,
      )
      dotnetCalls.push(`    .AddFiles("${escapeCSharp(bindingId)}", new[]
    {
        WorkflowUploadFile.FromStreamFactory(() => File.OpenRead("first.bin"), "first.bin", "application/octet-stream"),
        WorkflowUploadFile.FromStreamFactory(() => File.OpenRead("second.bin"), "second.bin", "application/octet-stream"),
    })`)
    } else if (payloadTypeId === 'text.v1') {
      dotnetCalls.push(`    .AddText("${escapeCSharp(bindingId)}", "sample text", "text/plain", "utf-8")`)
    } else if (payloadTypeId === 'value.v1') {
      dotnetCalls.push(`    .AddJson("${escapeCSharp(bindingId)}", new { })`)
    }
  }

  const runtimeId = workflowRuntimeId || '{workflow_runtime_id}'
  const json = JSON.stringify(jsonBindings, null, 2)
  const multipartParts = [
    `curl -X POST '/api/v1/workflows/app-runtimes/${runtimeId}/invoke?response_mode=run'`,
    `  -F 'input_bindings_json=${escapeShellSingleQuotedJson(JSON.stringify(multipartInlineBindings))}'`,
    ...multipartFields,
  ]
  const dotnetChain = dotnetCalls.length > 0 ? `\n${dotnetCalls.join('\n')}` : ''
  return {
    json,
    multipartCurl: multipartParts.join(' \\\n'),
    dotnet: `var request = new WorkflowRequestBuilder()${dotnetChain}\n    .Build();\nawait client.InvokeWorkflowAppRuntimeUploadAppResultResponseAsync("${escapeCSharp(runtimeId)}", request, cancellationToken);`,
  }
}

function buildJsonSample(payloadTypeId: string): unknown {
  if (payloadTypeId === 'value.v1') return { value: {} }
  if (payloadTypeId === 'text.v1') return { text: 'sample text', media_type: 'text/plain', charset: 'utf-8' }
  if (payloadTypeId === 'image-base64.v1') return { image_base64: '<base64>', media_type: 'image/png' }
  if (payloadTypeId === 'image-ref.v1') {
    return { transport_kind: 'storage', object_key: '<immutable-image-object-key>', media_type: 'image/png' }
  }
  if (payloadTypeId === 'file-ref.v1') return buildFileRefSample('<immutable-file-object-key>', 'sample.bin')
  if (payloadTypeId === 'file-refs.v1') {
    return {
      items: [buildFileRefSample('<immutable-file-object-key>', 'sample.bin')],
      count: 1,
    }
  }
  return undefined
}

function buildFileRefSample(objectKey: string, fileName: string): WorkflowJsonObject {
  return {
    transport_kind: 'storage',
    storage_ref: 'object-store',
    object_key: objectKey,
    file_name: fileName,
    media_type: 'application/octet-stream',
    content_length: 0,
    checksum_algorithm: 'sha256',
    checksum: '<sha256>',
    immutable_version: '<immutable-version>',
  }
}

function isRecord(value: unknown): value is WorkflowJsonObject {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value))
}

function readText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function escapeShellSingleQuotedJson(value: string): string {
  return value.replaceAll("'", "'\\''")
}

function escapeCSharp(value: string): string {
  return value.replaceAll('\\', '\\\\').replaceAll('"', '\\"')
}
