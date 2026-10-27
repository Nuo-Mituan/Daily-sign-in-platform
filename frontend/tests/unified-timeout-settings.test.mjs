import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const component = readFileSync(
  new URL('../src/components/UnifiedTimeoutSettings.vue', import.meta.url),
  'utf8',
)

test('timeout settings change events emit a save with current values', () => {
  assert.match(component, /@change="save"/)
  assert.match(component, /function save\(\)/)
  assert.match(component, /emit\('save', \{/)
  assert.match(component, /enabled: enabledModel\.value/)
  assert.match(component, /time: timeModel\.value/)
})
