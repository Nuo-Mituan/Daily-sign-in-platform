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

test('icon route returns a specific SVG deprecation detail', () => {
  assert.equal(
    extractErrorMessage({
      config: { url: '/modules/icon?key=demo&path=icon.svg' },
      response: {
        status: 415,
        data: { detail: 'SVG 图标已停止支持，请改用 PNG 格式' },
      },
    }),
    'SVG 图标已停止支持，请改用 PNG 格式',
  )
})

test('icon route falls back to fixed 415 copy for generic detail', () => {
  assert.equal(
    extractErrorMessage({
      config: { url: '/modules/icon?key=demo' },
      response: { status: 415, data: { detail: '图标格式不合法' } },
    }),
    '图标格式不支持，请使用 PNG / JPG / ICO / WebP',
  )
})

test('icon route keeps fixed 413 copy for generic size detail', () => {
  assert.equal(
    extractErrorMessage({
      config: { url: '/modules/icon?key=demo' },
      response: { status: 413, data: { detail: '图标文件过大' } },
    }),
    '图标文件过大，请压缩后重试',
  )
})

test('icon route returns a specific 413 detail', () => {
  assert.equal(
    extractErrorMessage({
      config: { url: '/modules/icon?key=demo' },
      response: { status: 413, data: { detail: '图标尺寸超过限制' } },
    }),
    '图标尺寸超过限制',
  )
})
