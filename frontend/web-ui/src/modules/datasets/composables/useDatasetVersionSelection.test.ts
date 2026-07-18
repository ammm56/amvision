import { describe, expect, it } from 'vitest'

import type { DatasetImportSummary, DatasetVersionRelation } from '../services/dataset.service'
import { buildDatasetVersionSelectionItems } from './useDatasetVersionSelection'

function version(
  datasetVersionId: string,
  metadata: Record<string, unknown>,
): DatasetVersionRelation {
  return {
    dataset_version_id: datasetVersionId,
    dataset_id: 'dataset-1',
    project_id: 'project-1',
    task_type: 'classification',
    sample_count: 10,
    category_count: 2,
    split_names: ['train', 'val'],
    metadata,
  }
}

describe('dataset version selection items', () => {
  it('keeps a persisted DatasetVersion visible after its import record is deleted', () => {
    const items = buildDatasetVersionSelectionItems([
      version('dataset-version-1', {
        source_import_id: 'dataset-import-deleted',
        format_type: 'imagenet-classification',
        created_at: '2026-07-19T01:00:00Z',
      }),
    ], [])

    expect(items).toHaveLength(1)
    expect(items[0]?.dataset_version_id).toBe('dataset-version-1')
    expect(items[0]?.source_import_id).toBe('dataset-import-deleted')
    expect(items[0]?.source_format_type).toBe('imagenet-classification')
    expect(items[0]?.source_status).toBe('')
  })

  it('uses live import metadata when the source record still exists', () => {
    const sourceImport = {
      dataset_import_id: 'dataset-import-1',
      dataset_version_id: 'dataset-version-1',
      dataset_id: 'dataset-1',
      project_id: 'project-1',
      task_type: 'classification',
      format_type: 'imagenet-classification',
      status: 'completed',
      processing_state: 'completed',
      created_at: '2026-07-19T02:00:00Z',
      package_path: 'imports/package.zip',
      staging_path: 'imports/staging',
    } satisfies DatasetImportSummary

    const items = buildDatasetVersionSelectionItems([
      version('dataset-version-1', { source_import_id: 'dataset-import-1' }),
    ], [sourceImport])

    expect(items[0]?.source_created_at).toBe(sourceImport.created_at)
    expect(items[0]?.source_status).toBe('completed')
  })
})
