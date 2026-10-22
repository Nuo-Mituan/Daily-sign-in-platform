function optionValues(spec) {
  return (spec.options || []).map((option) =>
    option && typeof option === 'object' && !Array.isArray(option)
      ? option.value
      : option,
  )
}

export function generateAccountId() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return `acct-${crypto.randomUUID()}`
  }
  return `acct-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

export function buildDefaultParams(schema = []) {
  const params = {}
  for (const spec of schema) {
    if (spec.type === 'switch') {
      params[spec.key] = Boolean(spec.default)
    } else if (spec.type === 'number') {
      params[spec.key] =
        typeof spec.default === 'number'
          ? spec.default
          : typeof spec.min === 'number'
            ? spec.min
            : undefined
    } else if (spec.type === 'select') {
      const values = optionValues(spec)
      params[spec.key] =
        values.includes(spec.default) ? spec.default : (values[0] ?? '')
    } else {
      params[spec.key] = spec.default ?? ''
    }
  }
  return params
}

export function createAccount(schema = [], label = '') {
  return {
    id: generateAccountId(),
    label,
    params: buildDefaultParams(schema),
  }
}

export function fillAccountParams(schema = [], existing = {}) {
  const params = buildDefaultParams(schema)
  for (const spec of schema) {
    if (existing[spec.key] !== undefined && existing[spec.key] !== null) {
      params[spec.key] = existing[spec.key]
    }
  }
  return params
}

export function maskAccountValue(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  if (text.includes('@')) {
    const [local, domain] = text.split('@')
    return `${local.slice(0, 2)}***@${domain}`
  }
  if (text.includes('=')) {
    const first = text.split(';')[0]
    const [, cookieValue = ''] = first.split('=')
    const masked =
      cookieValue.length > 8
        ? `${cookieValue.slice(0, 4)}***${cookieValue.slice(-2)}`
        : `${cookieValue.slice(0, 2)}***`
    return `${first.split('=')[0]}=${masked}`
  }
  if (text.length <= 6) return `${text.slice(0, 2)}***`
  return `${text.slice(0, 4)}***${text.slice(-2)}`
}

export function accountHint(account, schema = []) {
  if (account.label) return account.label
  const labelled = schema.filter((spec) => spec.account_label)
  const commonKeys = ['account', 'username', 'email', 'cookie', 'token']
  const candidates = labelled.length
    ? labelled
    : schema.filter((spec) => commonKeys.includes(spec.key.toLowerCase()))
  for (const spec of candidates) {
    const value = account.params?.[spec.key]
    if (value) return maskAccountValue(value)
  }
  return ''
}

export function accountCardTitle(account, schema, index) {
  return accountHint(account, schema) || `账号 ${index + 1}`
}

export function validateAccountFields(account, schema, index) {
  for (const spec of schema) {
    if (!spec.required || spec.type === 'switch') continue
    const value = account.params?.[spec.key]
    if (value === undefined || value === null || String(value).trim() === '') {
      return `第 ${index + 1} 个账号缺少必填项「${spec.label || spec.key}」`
    }
  }
  return ''
}
