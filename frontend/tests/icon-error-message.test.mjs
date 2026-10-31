import test from 'node:test'
import assert from 'node:assert/strict'
import { iconErrorMessage } from '../src/utils/iconErrorMessage.js'

test('maps icon HTTP failures to actionable Chinese messages', () => {
  assert.equal(iconErrorMessage({ status: 415 }), '图标格式不支持，请使用 PNG / JPG / ICO / WebP')
  assert.equal(iconErrorMessage({ status: 413 }), '图标文件过大，请压缩后重试')
  assert.equal(iconErrorMessage({ status: 404 }), '图标不存在，请检查模块图标路径')
  assert.equal(iconErrorMessage({ status: 500 }), '')
})

test('shared function honors generic codes and concrete details', () => {
  assert.equal(
    iconErrorMessage({ status: 415, code: 'icon_format_default', detail: 'x' }),
    '图标格式不支持，请使用 PNG / JPG / ICO / WebP',
  )
  assert.equal(
    iconErrorMessage({ status: 413, code: 'icon_size_default', detail: 'x' }),
    '图标文件过大，请压缩后重试',
  )
  assert.equal(
    iconErrorMessage({ status: 415, detail: 'SVG 图标已停止支持' }),
    'SVG 图标已停止支持',
  )
})
