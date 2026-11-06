// Narrow layouts also apply when large text makes the window narrow
// (text-breakpoints.mjs, the Text setting, 2026-11).
import test from 'node:test'
import assert from 'node:assert/strict'
import { addTextBreakpoints } from '../text-breakpoints.mjs'

test('each max-width block is copied under its html.bb-wN class', () => {
  const out = addTextBreakpoints('.a{color:red}@media(max-width:600px){.b,.c>d{display:none}html{x:1}}')
  assert.match(out, /html\.bb-w600 \.b,html\.bb-w600 \.c>d\{display:none\}/)
  assert.match(out, /html\.bb-w600\{x:1\}/)
  assert.ok(out.startsWith('.a{color:red}@media(max-width:600px)'))
})

test('max-height blocks get html.bb-hN; min-width and print blocks are left alone', () => {
  const out = addTextBreakpoints('@media(max-height:600px){.p{height:auto}}@media(min-width:901px) and (max-width:1420px){.q{a:b}}@media print{.r{c:d}}')
  assert.match(out, /html\.bb-h600 \.p\{height:auto\}/)
  assert.doesNotMatch(out, /bb-w1420|html\.\S+ \.q|html\.\S+ \.r/)
})

test('a stylesheet with no breakpoints is unchanged', () => {
  assert.equal(addTextBreakpoints('.a{b:c}'), '.a{b:c}')
})
