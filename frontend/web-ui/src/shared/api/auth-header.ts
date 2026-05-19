export function buildBearerAuthHeader(token: string | null): Record<string, string> {
  if (!token) {
    return {}
  }
  return { Authorization: `Bearer ${token}` }
}