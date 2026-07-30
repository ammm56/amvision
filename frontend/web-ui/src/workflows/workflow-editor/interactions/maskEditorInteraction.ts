export interface AppliedMaskBinding {
  mask_object_key: string
  mask_source_identity: string
}

/**
 * Mask Editor 的持久化状态必须同时包含 Mask 引用和对应的源图身份。
 * 两个字段缺少任意一个时都不能写回节点，避免产生无法验证来源的孤立 Mask。
 */
export function buildAppliedMaskBinding(
  maskObjectKey: string,
  sourceIdentity: string,
): AppliedMaskBinding | null {
  const normalizedObjectKey = maskObjectKey.trim()
  const normalizedSourceIdentity = sourceIdentity.trim()
  if (!normalizedObjectKey || !normalizedSourceIdentity) return null
  return {
    mask_object_key: normalizedObjectKey,
    mask_source_identity: normalizedSourceIdentity,
  }
}

export function isAppliedMaskBinding(
  parameters: Record<string, unknown>,
  expected: AppliedMaskBinding,
): boolean {
  return (
    parameters.mask_object_key === expected.mask_object_key
    && parameters.mask_source_identity === expected.mask_source_identity
  )
}
