import test from 'node:test'
import assert from 'node:assert/strict'
import { extractErrorMessage } from '../src/api/errorMessage.js'

test('icon route 415 uses icon semantics even with backend detail', () => {
  assert.equal(
    extractErrorMessage({
      config: { url: '/modules/icon?key=demo' },
      response: { status: 415, data: { detail: '图标格式不合法' } },
    }),
    '图标格式不支持，请使用 PNG / JPG / ICO / WebP',
  )
})

test('non-icon 413 keeps backend detail', () => {
  assert.equal(
    extractErrorMessage({
      config: { url: '/modules/upload' },
      response: { status: 413, data: { detail: 'ZIP 文件过大' } },
    }),
    'ZIP 文件过大',
  )
})

test('non-icon 415 without detail keeps generic fallback', () => {
  assert.equal(
    extractErrorMessage({
      config: { url: '/modules/upload' },
      response: { status: 415, data: {} },
    }),
    '请求失败（HTTP 415）',
  )
})
