import { readFileSync, writeFileSync } from "node:fs";

export function fromTag(tag) {
  const d = String(tag).replace(/[^0-9]/g, "");
  return `${d.slice(0,4)}-${d.slice(4,6)}-${d.slice(6,8)}`;
}

const VENDOR_KEYS = ["ed", "red", "bp", "otel", "cribl", "fluentd", "vector", "fluentbit"];

export function validateRun(run) {
  if (!run || typeof run !== "object") throw new Error("run must be an object");
  if (!run.runId) throw new Error("run.runId required");
  if (!run.date || !/^\d{4}-\d{2}-\d{2}$/.test(run.date)) throw new Error("run.date must be YYYY-MM-DD");
  if (!run.vendors || typeof run.vendors !== "object") throw new Error("run.vendors required");
  for (const k of VENDOR_KEYS) {
    const v = run.vendors[k];
    if (!v) continue;
    for (const m of ["avg", "peak"]) {
      if (v[m] != null && (!Array.isArray(v[m]) || v[m].length !== 4))
        throw new Error(`vendors.${k}.${m} must be a length-4 array`);
    }
  }
  return true;
}

// Release data.json carries ~1 MB of per-trial evidence; the page needs only the summary.
export function shortVersion(v) {
  if (v == null) return null;
  const m = String(v).match(/v?\d+\.\d+(\.\d+)?(-[0-9A-Za-z.]+)?/);
  return m ? m[0] : String(v);
}

export function slimRun(run) {
  const versions = {};
  for (const [k, v] of Object.entries(run.versions || {})) versions[k] = shortVersion(v);
  const vendors = {};
  for (const [k, v] of Object.entries(run.vendors || {})) {
    vendors[k] = { name: v.name ?? null, avg: v.avg ?? null, peak: v.peak ?? null, cpu: v.cpu ?? null, mem: v.mem ?? null, perCpu: v.perCpu ?? null };
  }
  return { runId: run.runId, date: run.date, aggregation: run.aggregation ?? null, scenarios: ["Pass-Through", "Filter", "Mask", "Lookup"], versions, vendors };
}

// Go-loadgen "best-tier" releases predate the Rust method and are not comparable.
export const LEGACY_AGGREGATION = "best-tier";

export function mergeHistory(existing, run) {
  const arr = Array.isArray(existing) ? existing.slice() : [];
  const map = new Map(arr.map((r) => [r.runId, r]));
  map.set(run.runId, run);
  return [...map.values()].sort((a, b) =>
    a.date < b.date ? -1 : a.date > b.date ? 1 : a.runId < b.runId ? -1 : a.runId > b.runId ? 1 : 0
  );
}

// CLI: node merge-history.mjs <existing.json> <run.json> <out.json> <tag>
if (import.meta.url === `file://${process.argv[1]}`) {
  const [existingPath, runPath, outPath, tag] = process.argv.slice(2);
  if (!existingPath || !runPath || !outPath || !tag) {
    console.error("usage: merge-history.mjs <existing.json> <run.json> <out.json> <tag>");
    process.exit(1);
  }
  let existing = [];
  try { existing = JSON.parse(readFileSync(existingPath, "utf8")); } catch { existing = []; }
  const run = slimRun({ ...JSON.parse(readFileSync(runPath, "utf8")), runId: tag, date: fromTag(tag) });
  if (run.aggregation === LEGACY_AGGREGATION) {
    console.log(`skipping ${tag}: legacy ${LEGACY_AGGREGATION} method`);
    writeFileSync(outPath, JSON.stringify(Array.isArray(existing) ? existing : [], null, 2) + "\n");
    process.exit(0);
  }
  validateRun(run);
  const merged = mergeHistory(existing, run);
  writeFileSync(outPath, JSON.stringify(merged, null, 2) + "\n");
  console.log(`merged ${merged.length} runs -> ${outPath}`);
}
