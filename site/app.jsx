/* Pipeline Throughput Benchmark — driven by data/history.json */

const SCENARIOS = ["Pass-Through", "Filter", "Mask", "Lookup"];
const VENDORS = [
  { key: "ed",       name: "Edge Delta (Go)",              short: "Edge Delta" },
  { key: "red",      name: "Edge Delta (Rust)",       short: "ED Rust" },
  { key: "otel",     name: "OpenTelemetry Collector", short: "OTel Collector" },
  { key: "cribl",    name: "Cribl",                   short: "Cribl" },
  { key: "vector", name: "Vector", short: "Vector" },
  { key: "fluentbit", name: "Fluent Bit", short: "Fluent Bit" },
  { key: "fluentd",  name: "Fluentd",                 short: "Fluentd" },
];
const PALETTE = { ed: "#00DA63", red: "#E5484D", otel: "#9F4FFF", cribl: "#FF9554", fluentd: "#00C2D7", vector: "#E5C454", fluentbit: "#4F8DF7" };
const vendorColor = (k) => PALETTE[k];
const PLOT_H = 440;

const fmt = (n) => n == null ? "N/A" : n.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt0 = (n) => n.toLocaleString("en-US", { maximumFractionDigits: 0 });
const fmtK = (n) => n === 0 ? "0" : n >= 1000 ? (n / 1000) + "k" : String(n);

function niceScale(maxVal, targetTicks = 7) {
  if (!(maxVal > 0)) return { max: 10, ticks: [0, 10] };
  const rawStep = maxVal / targetTicks;
  const pow = Math.pow(10, Math.floor(Math.log10(rawStep)));
  const n = rawStep / pow;
  const niceStep = (n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10) * pow;
  const max = Math.ceil(maxVal / niceStep) * niceStep;
  const ticks = [];
  for (let t = 0; t <= max + niceStep * 0.5; t += niceStep) ticks.push(Math.round(t));
  return { max, ticks: [...new Set(ticks)] };
}

/* ───── Throughput (grouped bars) ───── */
function ThroughputChart({ data, axisMax, ticks, fmtv = fmt0, unit = "logs/sec", tipFmt = fmt, missing = () => "N/A", failed = () => null }) {
  return (
    <div className="tp">
      <div className="plot">
        {ticks.map((t) => (
          <div className="grid" key={t} style={{ bottom: (t / axisMax) * PLOT_H + "px" }}>
            <span className="ytick">{fmtK(t)}</span>
            <span className="gline" />
          </div>
        ))}
        <div className="groups">
          {SCENARIOS.map((sc, si) => (
            <div className="group" key={sc}>
              <div className="bars">
                {VENDORS.map((v) => {
                  const val = data[v.key][si];
                  const f = failed(v.key, si);
                  if (val == null && f) {
                    return (
                      <div className="barslot" key={v.key}>
                        <div className="bval" style={{ bottom: "26px" }}>✕</div>
                        <div className="bar failed">
                          <div className="tip">
                            <div className="tip-v" style={{ color: vendorColor(v.key) }}>{v.name}</div>
                            <div className="tip-s">{sc}</div>
                            <div className="tip-n">{f}</div>
                          </div>
                        </div>
                      </div>
                    );
                  }
                  if (val == null) {
                    return (
                      <div className="barslot" key={v.key} data-na="1">
                        <div className="na">{missing(v.key, si)}</div>
                        <div className="na-base" style={{ background: vendorColor(v.key) }} />
                      </div>
                    );
                  }
                  const h = (val / axisMax) * PLOT_H;
                  return (
                    <div className="barslot" key={v.key}>
                      <div className="bval" style={{ bottom: h + 8 + "px" }}>{fmtv(val)}</div>
                      <div className={"bar" + (v.key === "ed" ? " ed" : "")} style={{ height: h + "px", background: vendorColor(v.key) }}>
                        <div className="tip">
                          <div className="tip-v" style={{ color: vendorColor(v.key) }}>{v.name}</div>
                          <div className="tip-s">{sc}</div>
                          <div className="tip-n">{tipFmt(val)} <span>{unit}</span></div>
                        </div>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="xaxis">{SCENARIOS.map((sc) => <div className="xlab" key={sc}>{sc}</div>)}</div>
    </div>
  );
}

/* ───── Efficiency at a fixed offered load ───── */
const LADDER_METRICS = [
  { key: "lpc", label: "Logs/sec per core", unit: "logs/sec/core", better: "higher", get: (c) => c.lpc, fmtv: (v) => fmtK(Math.round(v / 100) * 100) },
  { key: "lpm", label: "Logs/sec per MB", unit: "logs/sec/MB", better: "higher", get: (c) => c.lpm, fmtv: fmt0 },
  { key: "cpu", label: "CPU cores", unit: "cores", better: "lower", get: (c) => c.cpu / 100, fmtv: (v) => v.toFixed(2) },
  { key: "mem", label: "Memory MB", unit: "MB", better: "lower", get: (c) => c.mem, fmtv: fmt0 },
];
const tierLabel = (t) => fmtK(t);
const STATUS_SHORT = { unsupported: "N/A", invalid: "!", missing: "?" };
const sustained = (c) => c && c.s === "ok" && c.cpu != null;
// A shortfall at this tier, or a lower one (higher tiers are then skipped).
const failsAt = (c) => !!c && !sustained(c) && c.s !== "unsupported";
const ladderCell = (ladder, key, si, ti) => ladder?.agents?.[key]?.[si]?.[ti] ?? null;
const fmtFull = (v) => v.toLocaleString("en-US", { maximumFractionDigits: 2 });

function CellTip({ v, sc, target, cell }) {
  return (
    <>
      <div className="tip-v" style={{ color: vendorColor(v.key) }}>{v.name}</div>
      <div className="tip-s">{sc} · {fmt0(target)} logs/sec offered</div>
      <div className="tip-grid">
        <span>CPU</span><b>{(cell.cpu / 100).toFixed(2)} cores</b>
        <span>Memory</span><b>{fmt0(cell.mem)} MB</b>
        <span>Per core</span><b>{fmt0(cell.lpc)} logs/s</b>
        <span>Per MB</span><b>{fmt0(cell.lpm)} logs/s</b>
      </div>
    </>
  );
}

function TierBars({ ladder, tierIndex, metric }) {
  const data = {}, vals = [];
  VENDORS.forEach((v) => {
    data[v.key] = SCENARIOS.map((_, si) => {
      const cell = ladderCell(ladder, v.key, si, tierIndex);
      const val = sustained(cell) ? metric.get(cell) : null;
      if (val != null) vals.push(val);
      return val;
    });
  });
  const { max, ticks } = niceScale(vals.length ? Math.max(...vals) : 10);
  const target = fmt0(ladder.targets[tierIndex]);
  const missing = (key, si) => {
    const cell = ladderCell(ladder, key, si, tierIndex);
    return cell ? (STATUS_SHORT[cell.s] ?? "?") : "N/A";
  };
  const failed = (key, si) => failsAt(ladderCell(ladder, key, si, tierIndex)) ? `Could not sustain ${target} logs/sec` : null;
  return <ThroughputChart key={metric.key + tierIndex} data={data} axisMax={max} ticks={ticks}
    fmtv={metric.fmtv} unit={metric.unit} tipFmt={fmtFull} missing={missing} failed={failed} />;
}

/* ───── Trend (line chart over time) ───── */
function TrendChart({ history, scenarioIndex, metric, visible, hover, setHover }) {
  const W = 1040, H = 440, padL = 58, padR = 18, padT = 18, padB = 42;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = history.length;

  const series = VENDORS.map((v) => {
    let prevVer = null;
    return {
      v,
      pts: history.map((r, i) => {
        const vd = r.vendors && r.vendors[v.key];
        const arr = vd ? vd[metric] : null;
        const val = arr && arr[scenarioIndex] != null ? arr[scenarioIndex] : null;
        const ver = r.versions && r.versions[v.key] != null ? r.versions[v.key] : null;
        const changed = ver != null && prevVer != null && ver !== prevVer;
        if (ver != null) prevVer = ver;
        return { i, val, date: r.date, ver, changed };
      }),
    };
  });

  const vals = [];
  series.forEach((s) => { if (visible.has(s.v.key)) s.pts.forEach((p) => { if (p.val != null) vals.push(p.val); }); });
  const { max: yMax, ticks } = niceScale(vals.length ? Math.max(...vals) : 10);

  const X = (i) => (n <= 1 ? padL + plotW / 2 : padL + (i / (n - 1)) * plotW);
  const Y = (val) => padT + plotH - (val / yMax) * plotH;
  const step = Math.max(1, Math.ceil(n / 8));

  React.useEffect(() => { setHover(null); }, [scenarioIndex, metric]);

  return (
    <div className="trend-plot">
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={Y(t)} y2={Y(t)} stroke="var(--ed-border-1)" strokeWidth="1" />
            <text x={padL - 10} y={Y(t)} textAnchor="end" dominantBaseline="middle" fontFamily="var(--ed-font-mono)" fontSize="11" fill="var(--ed-text-secondary)">{fmtK(t)}</text>
          </g>
        ))}
        <line x1={padL} x2={W - padR} y1={Y(0)} y2={Y(0)} stroke="var(--ed-border-2)" strokeWidth="1" />
        {history.map((r, i) => (i % step === 0 || i === n - 1) ? (
          <text key={i} x={X(i)} y={H - padB + 20} textAnchor="middle" fontFamily="var(--ed-font-mono)" fontSize="10.5" fill="var(--ed-text-secondary)">{(r.date ?? "").slice(5)}</text>
        ) : null)}
        {series.map((s) => {
          if (!visible.has(s.v.key)) return null;
          const isEd = s.v.key === "ed";
          const segs = []; let cur = [];
          s.pts.forEach((p) => { if (p.val == null) { if (cur.length) segs.push(cur); cur = []; } else cur.push(p); });
          if (cur.length) segs.push(cur);
          return (
            <g key={s.v.key}>
              {segs.map((seg, k) => (
                <polyline key={k} fill="none" stroke={vendorColor(s.v.key)} strokeWidth={isEd ? 2.6 : 1.6}
                  strokeLinejoin="round" strokeLinecap="round" points={seg.map((p) => `${X(p.i)},${Y(p.val)}`).join(" ")} />
              ))}
              {s.pts.map((p) => {
                if (p.val == null) return null;
                const cx = X(p.i), cy = Y(p.val);
                const handlers = {
                  style: { cursor: "pointer" },
                  onMouseEnter: () => setHover({ key: s.v.key, name: s.v.name, val: p.val, date: p.date, ver: p.ver, changed: p.changed, x: cx, y: cy }),
                  onMouseLeave: () => setHover(null),
                };
                if (p.changed) {
                  const d = isEd ? 5 : 4.4;
                  return <path key={p.i} d={`M ${cx} ${cy - d} L ${cx + d} ${cy} L ${cx} ${cy + d} L ${cx - d} ${cy} Z`}
                    fill="var(--ed-surface-1)" stroke={vendorColor(s.v.key)} strokeWidth="2" {...handlers} />;
                }
                return <circle key={p.i} cx={cx} cy={cy} r={isEd ? 3.6 : 3} fill="var(--ed-surface-1)"
                  stroke={vendorColor(s.v.key)} strokeWidth="2" {...handlers} />;
              })}
            </g>
          );
        })}
      </svg>
      {hover && (
        <div className="trend-tip" style={{ left: (hover.x / W * 100) + "%", top: (hover.y / H * 100) + "%" }}>
          <div className="tip-v" style={{ color: vendorColor(hover.key) }}>{hover.name}</div>
          <div className="tip-s">{SCENARIOS[scenarioIndex]} · {hover.date}</div>
          <div className="tip-n">{fmt(hover.val)} <span>logs/sec</span></div>
          {hover.ver != null && <div className="tip-ver">{hover.changed ? "◆ updated to " : "version "}{hover.ver}</div>}
        </div>
      )}
    </div>
  );
}

/* ───── App ───── */
const QS = new URLSearchParams(location.search);
const qsInt = (k) => (QS.has(k) && !isNaN(+QS.get(k)) ? +QS.get(k) : null);

function App() {
  const [history, setHistory] = React.useState(null);
  const [err, setErr] = React.useState(null);
  const [metric, setMetric] = React.useState("avg");
  const [view, setView] = React.useState(["tier", "throughput", "trend"].includes(QS.get("view")) ? QS.get("view") : "tier");
  const [scenarioIdx, setScenarioIdx] = React.useState(qsInt("scenario") ?? 0);
  const [hidden, setHidden] = React.useState(() => new Set());
  const [hover, setHover] = React.useState(null);
  const [effMetric, setEffMetric] = React.useState(LADDER_METRICS.some((m) => m.key === QS.get("metric")) ? QS.get("metric") : "lpc");
  const [tierIdx, setTierIdx] = React.useState(qsInt("tier"));

  React.useEffect(() => {
    fetch("data/history.json", { cache: "no-cache" })
      .then((r) => { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then((h) => setHistory(Array.isArray(h) ? h : []))
      .catch((e) => setErr(e.message));
  }, []);

  if (err) return <div className="wrap"><div className="card state">Failed to load benchmark data: {err}</div></div>;
  if (history == null) return <div className="wrap"><div className="card state">Loading benchmark data…</div></div>;
  if (history.length === 0) return <div className="wrap"><div className="card state">No benchmark runs published yet.</div></div>;

  const latest = history[history.length - 1];
  const AVG = {}, PEAK = {};
  VENDORS.forEach((v) => {
    const vd = latest.vendors?.[v.key] || {};
    AVG[v.key] = vd.avg || [null, null, null, null];
    PEAK[v.key] = vd.peak || [null, null, null, null];
  });
  const data = metric === "avg" ? AVG : PEAK;

  const allLatest = [];
  VENDORS.forEach((v) => (AVG[v.key] || []).concat(PEAK[v.key] || []).forEach((x) => { if (x != null) allLatest.push(x); }));
  const { max: axisMax, ticks } = niceScale(allLatest.length ? Math.max(...allLatest) : 10);

  const visible = new Set(VENDORS.map((v) => v.key).filter((k) => !hidden.has(k)));
  const ladder = latest.ladder;
  const lm = LADDER_METRICS.find((m) => m.key === effMetric);
  const tierI = tierIdx ?? (ladder ? ladder.targets.length - 1 : 0);
  const tierView = view === "tier" && !!ladder;
  const clickable = view === "trend";
  // Agents that cannot sustain the selected load in any scenario they support.
  const failsTier = (k) => tierView && [0, 1, 2, 3].every((si) => {
    const c = ladderCell(ladder, k, si, tierI);
    return !sustained(c);
  }) && [0, 1, 2, 3].some((si) => failsAt(ladderCell(ladder, k, si, tierI)));

  const toggle = (k) => {
    if (!clickable) return;
    setHidden((prev) => { const n = new Set(prev); n.has(k) ? n.delete(k) : n.add(k); return n; });
  };

  return (
    <div className="wrap">
      <div className="card">
        <header className="head">
          <div className="brand">
            <div className="titles">
              <h1>Pipeline throughput benchmark</h1>
              <p className="sub">
                {view === "throughput" ? "Highest sustained rate per scenario · logs/sec · tests stop at the top tier"
                  : tierView ? lm.label + " at " + fmt0(ladder.targets[tierI]) + " logs/sec offered · " + lm.better + " is better"
                  : "Trend over time · logs/sec · " + SCENARIOS[scenarioIdx]}
              </p>
            </div>
          </div>
          <div className="controls">
            <div className="seg">
              {ladder && <button className={view === "tier" ? "on" : ""} onClick={() => { setView("tier"); setHover(null); }}>By tier</button>}
              <button className={view === "throughput" ? "on" : ""} onClick={() => { setView("throughput"); setHover(null); }}>Throughput</button>
              <button className={view === "trend" ? "on" : ""} onClick={() => setView("trend")}>Trend</button>
            </div>
            {!tierView && (
              <div className="seg">
                <button className={metric === "avg" ? "on" : ""} onClick={() => setMetric("avg")}>Average</button>
                <button className={metric === "peak" ? "on" : ""} onClick={() => setMetric("peak")}>Peak</button>
              </div>
            )}
          </div>
        </header>

        {(view === "trend" || tierView) && (
          <div className="subcontrols">
            {view === "trend" && (
              <div className="seg seg-scn">
                {SCENARIOS.map((sc, i) => (
                  <button key={sc} className={scenarioIdx === i ? "on" : ""} onClick={() => setScenarioIdx(i)}>{sc}</button>
                ))}
              </div>
            )}
            {tierView && (
              <div className="seg seg-scn">
                {ladder.targets.map((t, i) => [t, i]).reverse().map(([t, i]) => (
                  <button key={t} className={tierI === i ? "on" : ""} onClick={() => setTierIdx(i)}>{tierLabel(t)}</button>
                ))}
              </div>
            )}
            {tierView && (
              <div className="seg seg-scn">
                {LADDER_METRICS.map((m) => (
                  <button key={m.key} className={effMetric === m.key ? "on" : ""} onClick={() => setEffMetric(m.key)}>{m.label}</button>
                ))}
              </div>
            )}
          </div>
        )}

        <div className="legend">
          {VENDORS.map((v) => {
            const off = clickable && hidden.has(v.key);
            const fails = failsTier(v.key);
            return (
              <div className={"leg" + (clickable ? " leg-click" : "") + (off ? " off" : "") + (fails ? " fails" : "")} key={v.key} onClick={() => toggle(v.key)}
                title={fails ? `Could not sustain ${fmt0(ladder.targets[tierI])} logs/sec` : undefined}>
                <span className="sw" style={{ background: fails ? "var(--ed-text-disabled)" : vendorColor(v.key) }} />
                <span className={v.key === "ed" ? "leg-ed" : ""}>{v.name}</span>
                {latest.versions?.[v.key] && <span className="leg-ver">{latest.versions[v.key]}</span>}
              </div>
            );
          })}
        </div>

        <div className="viewbody">
          {view === "throughput" && <ThroughputChart key={metric} data={data} axisMax={axisMax} ticks={ticks} />}
          {tierView && <TierBars ladder={ladder} tierIndex={tierI} metric={lm} />}
          {view === "trend" && <TrendChart history={history} scenarioIndex={scenarioIdx} metric={metric} visible={visible} hover={hover} setHover={setHover} />}
        </div>

        <footer className="foot">
          <span>{latest.date} · run {latest.runId}{view === "trend" ? " · " + history.length + " runs" : ""}</span>
          <span className="na-key">
            {tierView ? "Grey ✕ = could not sustain this load (within 2%) · N/A = scenario not supported"
              : (view === "trend" ? "◆ = agent version change · " : "") + "N/A = scenario not supported by that vendor"}
          </span>
        </footer>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
