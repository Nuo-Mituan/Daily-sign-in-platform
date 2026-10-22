let csrfToken = ''

export function setCsrfToken(value) {
  csrfToken = typeof value === 'string' ? value : ''
}

export function getCsrfToken() {
  return csrfToken
}
