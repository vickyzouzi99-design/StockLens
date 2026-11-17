export const apiBase = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/$/, '')
export async function accountApi<T>(path: string, body?: unknown, method = 'POST'): Promise<T> {
  const response = await fetch(apiBase + path, { credentials: 'include', method: body === undefined ? 'GET' : method, headers: { 'Content-Type': 'application/json' }, ...(body === undefined ? {} : { body: JSON.stringify(body) }) })
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '请求失败，请检查输入。')
  return data
}
