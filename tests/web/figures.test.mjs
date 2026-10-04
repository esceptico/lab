// Pure functions of the figure renderer. Run: node --test tests/web/*.test.mjs
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import vm from "node:vm";

const source = readFileSync(new URL("../../src/lab/views/web/figures.js", import.meta.url), "utf8");
const context = vm.createContext({ document: {}, getComputedStyle: () => ({ getPropertyValue: () => "" }) });
vm.runInContext(source + "\n;this.api = { extent, withDomain, niceTicks, tickFmt };", context);
const { extent, withDomain, niceTicks, tickFmt } = context.api;

test("extent ignores missing values and survives large arrays", () => {
  assert.deepEqual([...extent([3, null, -1, NaN, 2])], [-1, 3]);
  assert.deepEqual([...extent(new Array(300000).fill(1).map((v, i) => i))], [0, 299999]);
  assert.deepEqual([...extent([])], [0, 1]);
});

test("default ranges per chart type", () => {
  assert.deepEqual([...withDomain({ type: "heatmap", diverging: true, z: [[-0.2, 0.5], [0.1, 0]] }).domain], [-0.5, 0.5]);
  const [lo, hi] = withDomain({ type: "bars", series: [{ values: [10, 50] }] }).domain;
  assert.ok(lo === 0 && Math.abs(hi - 56) < 1e-9);
  assert.equal(withDomain({ type: "dots", items: [{ lo: 0.01, hi: 0.5 }] }).domain[0], 0);  // positive data keeps 0 in view
  assert.deepEqual([...withDomain({ type: "hist", domain: [0, 1], series: [] }).domain], [0, 1]);  // an author's range wins
});

test("ticks are round and never repeat", () => {
  const ticks = niceTicks(0, 0.6, 12);
  assert.equal(new Set(ticks.map(tickFmt(ticks))).size, ticks.length);
  assert.deepEqual([...niceTicks(0, 1, 5)], [0, 0.2, 0.4, 0.6, 0.8, 1]);
});
