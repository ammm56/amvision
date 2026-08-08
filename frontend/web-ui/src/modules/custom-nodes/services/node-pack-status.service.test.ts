import { beforeEach, describe, expect, it, vi } from 'vitest'

import { apiRequest } from '@/shared/api/http-client'
import {
  getNodePackAudit,
  getNodePackVersions,
  installNodePack,
  rollbackNodePack,
} from './node-pack-status.service'

vi.mock('@/shared/api/http-client', () => ({ apiRequest: vi.fn() }))

describe('node pack lifecycle service', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(apiRequest).mockResolvedValue({} as never)
  })

  it('uploads the ZIP and explicit enabled state as multipart form data', async () => {
    const packageFile = new File(['node-pack'], 'demo-nodes.zip', { type: 'application/zip' })

    await installNodePack(packageFile, false)

    const [path, options] = vi.mocked(apiRequest).mock.calls[0]
    expect(path).toBe('/workflows/node-packs/install')
    expect(options?.method).toBe('POST')
    expect(options?.body).toBeInstanceOf(FormData)
    const body = options?.body as FormData
    expect(body.get('package')).toBe(packageFile)
    expect(body.get('enabled')).toBe('false')
  })

  it('encodes node pack ids and versions in lifecycle paths', async () => {
    await getNodePackVersions('vendor/demo.nodes')
    await rollbackNodePack('vendor/demo.nodes', '2.0.0+cuda/12')

    expect(vi.mocked(apiRequest).mock.calls[0][0]).toBe(
      '/workflows/node-packs/vendor%2Fdemo.nodes/versions',
    )
    expect(vi.mocked(apiRequest).mock.calls[1][0]).toBe(
      '/workflows/node-packs/vendor%2Fdemo.nodes/rollback/2.0.0%2Bcuda%2F12',
    )
    expect(vi.mocked(apiRequest).mock.calls[1][1]?.method).toBe('POST')
  })

  it('uses query parameters for filtered audit reads', async () => {
    await getNodePackAudit('demo.nodes')

    expect(vi.mocked(apiRequest)).toHaveBeenCalledWith('/workflows/node-packs/audit', {
      query: { node_pack_id: 'demo.nodes', limit: 200 },
    })
  })
})
