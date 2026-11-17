export type IndustrySelection = string | string[] | null
export function industryCodes(value: IndustrySelection): string[] {
  return [...new Set(value === null ? [] : typeof value === 'string' ? [value] : value)].sort()
}
export function normalizeIndustry(value: unknown): IndustrySelection {
  if (value === null) return null
  const values = typeof value === 'string' ? [value] : value
  if (!Array.isArray(values) || values.length > 64 || values.some(code => typeof code !== 'string' || !/^\d{6}\.TI$/.test(code))) throw new Error('策略行业代码无效')
  const codes = industryCodes(values)
  return codes.length === 1 ? codes[0] : codes.length ? codes : null
}
