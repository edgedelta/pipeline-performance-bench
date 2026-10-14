import { test } from "node:test";
import assert from "node:assert/strict";
import { mergeHistory, fromTag, validateRun, shortVersion, slimRun } from "./merge-history.mjs";

const mk = (runId, date) => ({ runId, date, vendors: { ed: { avg: [1,2,3,4], peak: [1,2,3,4] } } });

test("fromTag derives YYYY-MM-DD", () => {
  assert.equal(fromTag("20260608-093535"), "2026-06-08");
});

test("appends and sorts by date ascending", () => {
  const out = mergeHistory([mk("a","2026-01-02"), mk("b","2026-01-01")], mk("c","2026-01-03"));
  assert.deepEqual(out.map((r) => r.runId), ["b","a","c"]);
});

test("dedupes by runId, newest wins", () => {
  const out = mergeHistory([mk("a","2026-01-01")], { ...mk("a","2026-01-01"), note: "x" });
  assert.equal(out.length, 1);
  assert.equal(out[0].note, "x");
});

test("null/non-array existing treated as empty", () => {
  assert.equal(mergeHistory(null, mk("a","2026-01-01")).length, 1);
});

test("validateRun rejects wrong array length", () => {
  assert.throws(() => validateRun({ runId: "a", date: "2026-01-01", vendors: { ed: { avg: [1,2,3] } } }));
});

test("validateRun accepts an absent vendor", () => {
  assert.ok(validateRun({ runId: "a", date: "2026-01-01", vendors: { ed: { avg: [1,2,3,4], peak: [1,2,3,4] } } }));
});

test("shortVersion extracts the version token", () => {
  assert.equal(shortVersion("Agent version: v2.27.0-rc.10, commit hash: 560bedc"), "v2.27.0-rc.10");
  assert.equal(shortVersion("otelcol-contrib version 0.162.0"), "0.162.0");
  assert.equal(shortVersion("Fluent Bit v5.1.4"), "v5.1.4");
  assert.equal(shortVersion("red 3.15.0"), "3.15.0");
  assert.equal(shortVersion(null), null);
});

test("slimRun keeps only page fields", () => {
  const out = slimRun({ runId: "a", date: "2026-01-01", aggregation: "x", scenarios: { "red/filter": {} }, fixed_throughput: {}, provenance: {},
    versions: { red: "red 3.15.0" }, vendors: { red: { name: "Edge Delta (Rust)", avg: [1,2,3,4], peak: [null,null,null,null], cpu: 1, mem: 2, perCpu: 3, extra: 9 } } });
  assert.deepEqual(Object.keys(out), ["runId", "date", "aggregation", "scenarios", "versions", "vendors"]);
  assert.deepEqual(out.scenarios, ["Pass-Through", "Filter", "Mask", "Lookup"]);
  assert.equal(out.versions.red, "3.15.0");
  assert.equal(out.vendors.red.extra, undefined);
  assert.ok(validateRun(out));
});
