export interface PaginationMeta {
  offset: number
  limit: number
  totalCount: number | null
  hasMore: boolean
  nextOffset: number | null
}

export interface PaginatedResult<T> {
  items: T[]
  pagination: PaginationMeta
}

function parseNumberHeader(headers: Headers, name: string): number | null {
  const value = headers.get(name)
  if (!value) {
    return null
  }
  const parsedValue = Number(value)
  return Number.isFinite(parsedValue) ? parsedValue : null
}

export function parsePaginationHeaders(headers: Headers): PaginationMeta {
  return {
    offset: parseNumberHeader(headers, 'x-offset') ?? 0,
    limit: parseNumberHeader(headers, 'x-limit') ?? 100,
    totalCount: parseNumberHeader(headers, 'x-total-count'),
    hasMore: headers.get('x-has-more') === 'true',
    nextOffset: parseNumberHeader(headers, 'x-next-offset'),
  }
}