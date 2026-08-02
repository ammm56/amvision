import { describe, expect, it } from 'vitest'

const vueSources = import.meta.glob('/src/**/*.vue', {
  eager: true,
  import: 'default',
  query: '?raw',
}) as Record<string, string>

describe('collection refresh stability', () => {
  it('does not couple an empty collection state to loading', () => {
    const violations: string[] = []

    for (const [filePath, source] of Object.entries(vueSources)) {
      for (const match of source.matchAll(/v-(?:if|else-if)="([^"]+)"/g)) {
        const condition = match[1] ?? ''
        if (/loading/i.test(condition) && /(?:\.length|\bcount)\s*===\s*0/i.test(condition)) {
          violations.push(`${filePath}: ${condition}`)
        }
      }
    }

    expect(violations).toEqual([])
  })
})
