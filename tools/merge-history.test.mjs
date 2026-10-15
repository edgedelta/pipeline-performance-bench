import { test } from "node:test";
import assert from "node:assert/strict";
import { mergeHistory, fromTag, validateRun, shortVersion, slimRun, slimLadder } from "./merge-history.mjs";

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
  assert.deepEqual(Object.keys(out), ["runId", "date", "aggregation", "scenarios", "versions", "vendors", "ladder"]);
  assert.deepEqual(out.scenarios, ["Pass-Through", "Filter", "Mask", "Lookup"]);
  assert.equal(out.versions.red, "3.15.0");
  assert.equal(out.vendors.red.extra, undefined);
  assert.ok(validateRun(out));
});

test("slimLadder keeps measurements, including tiers that fell short", () => {
  const tier = (ok, status) => ({ sustains_target: ok, status, acknowledged_logs_per_second: 124956.9, offered_logs_per_second: 124957.2, agent_cpu_percent: 193.04, agent_avg_memory_mb: 62.33, logs_per_second_per_core: 64896.4, logs_per_second_per_mb: 2009.18 });
  const out = slimLadder({ targets: [10000, 125000], tiers: {
    "red/pass-through/10000": tier(true, "ok"),
    "edgedelta/filter/125000": tier(false, "generator_limited"),
    "cribl/filter/125000": { sustains_target: false, status: "skipped_after_shortfall" },
  } });
  assert.deepEqual(out.targets, [10000, 125000]);
  assert.deepEqual(out.agents.red[0][0], { s: "ok", ack: 124957, off: 124957, cpu: 193, mem: 62.3, lpc: 64896, lpm: 2009.2 });
  assert.equal(out.agents.ed[1][1].s, "generator_limited");
  assert.equal(out.agents.ed[1][1].lpc, 64896);
  assert.deepEqual(out.agents.cribl[1][1], { s: "skipped_after_shortfall" });
  assert.equal(out.agents.otel[0][0], null);
  assert.equal(slimLadder(undefined), null);
});
