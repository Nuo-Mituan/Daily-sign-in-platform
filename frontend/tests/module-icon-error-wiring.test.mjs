import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const source = readFileSync(
  new URL('../src/components/ModuleIcon.vue', import.meta.url),
  'utf8',
)

test('ModuleIcon consumes shared icon error contract', () => {
  assert.match(source, /from '@\/utils\/iconErrorMessage'/)
  assert.match(source, /await response\.json\(\)/)
  assert.match(source, /iconErrorMessage\(\{/)
  assert.doesNotMatch(source, /iconHttpErrorMessage/)
})
