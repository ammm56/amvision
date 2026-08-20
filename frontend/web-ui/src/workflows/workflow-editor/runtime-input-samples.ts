export type ImageRefSampleTransportKind = 'storage' | 'local-path'

/** 按公开 payload 类型构造可直接编辑并提交的 Runtime 输入示例。 */
export function buildWorkflowRuntimeInputSample(
  payloadTypeId: string,
  bindingId: string,
  imageRefTransportKind: ImageRefSampleTransportKind,
): unknown {
  if (bindingId.includes('deployment_request')) {
    return { request_id: 'manual-test', source: 'web-ui' }
  }
  if (payloadTypeId === 'image-ref.v1') {
    if (imageRefTransportKind === 'local-path') {
      return {
        transport_kind: 'local-path',
        local_path: 'C:\\vision\\inputs\\sample.png',
        media_type: 'image/png',
      }
    }
    return {
      transport_kind: 'storage',
      object_key: 'workflows/inputs/sample.png',
      media_type: 'image/png',
    }
  }
  if (payloadTypeId === 'image-base64.v1') {
    return {
      image_base64: '<base64>',
      media_type: 'image/png',
    }
  }
  if (payloadTypeId.includes('boolean')) return false
  if (payloadTypeId.includes('number') || payloadTypeId.includes('float') || payloadTypeId.includes('integer')) return 0
  if (payloadTypeId.includes('object') || payloadTypeId.includes('json')) return {}
  if (payloadTypeId.includes('array') || payloadTypeId.includes('list')) return []
  return ''
}
