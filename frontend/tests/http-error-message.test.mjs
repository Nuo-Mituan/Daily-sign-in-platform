import test from 'node:test'
import assert from 'node:assert/strict'
import { extractErrorMessage } from '../src/api/errorMessage.js'

test('415/413 status overrides FastAPI detail for icon errors', () => {
  assert.equal(
    extractErrorMessage({ response: { status: 415, data: { detail: '图标格式不合法' } } }),
    '图标格式不支持，请上传 PNG / JPG / WebP 格式',
  )
  assert.equal(
    extractErrorMessage({ response: { status: 413, data: { detail: '图标文件过大' } } }),
    '图标文件过大，请压缩后重试',
  )
})

test('other statuses keep backend detail fallback behavior', () => {
  assert.equal(
    extractErrorMessage({ response: { status: 400, data: { detail: '参数错误' } } }),
    '参数错误',
  )
  assert.equal(
    extractErrorMessage({ response: { status: 500, data: {} } }),
    '请求失败（HTTP 500）',
  )
})
