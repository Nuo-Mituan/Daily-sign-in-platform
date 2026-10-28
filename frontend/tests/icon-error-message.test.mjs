import test from 'node:test'
import assert from 'node:assert/strict'
import { iconHttpErrorMessage } from '../src/utils/moduleIcon.js'

test('maps icon HTTP failures to actionable Chinese messages', () => {
  assert.equal(iconHttpErrorMessage(415), '图标格式不支持，请上传 PNG / JPG / WebP 格式')
  assert.equal(iconHttpErrorMessage(413), '图标文件过大，请压缩后重试')
  assert.equal(iconHttpErrorMessage(404), '图标不存在，请检查模块图标路径')
  assert.equal(iconHttpErrorMessage(500), '')
})
