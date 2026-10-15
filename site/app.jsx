/* Pipeline Throughput Benchmark — driven by data/history.json */

const SCENARIOS = ["Pass-Through", "Filter", "Mask", "Lookup"];
const VENDORS = [
  { key: "red",      name: "Edge Delta (Rust)",       short: "ED Rust" },
  { key: "ed",       name: "Edge Delta (Go)",              short: "Edge Delta" },
  { key: "otel",     name: "OpenTelemetry Collector", short: "OTel Collector" },
  { key: "cribl",    name: "Cribl",                   short: "Cribl" },
  { key: "vector", name: "Vector", short: "Vector" },
  { key: "fluentbit", name: "Fluent Bit", short: "Fluent Bit" },
  { key: "fluentd",  name: "Fluentd",                 short: "Fluentd" },
];
const PALETTE = { ed: "#3B82F6", red: "#00DA63", otel: "#9F4FFF", cribl: "#FF9554", fluentd: "#00C2D7", vector: "#E5C454", fluentbit: "#F472B6" };
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

/* ───── Grouped bars: one group per scenario, best result on the left ───── */
// groups[si] = [{ v, kind: "ok" | "short" | "skip" | "na", val, sub, tip }], already sorted.
function GroupedBars({ groups, axisMax, ticks, fmtv, tickFmt = fmtK, axisLabel }) {
  return (
    <div className="tp">
      {axisLabel && <div className="yunit">{axisLabel}</div>}
      <div className="plot">
        {ticks.map((t) => (
          <div className="grid" key={t} style={{ bottom: (t / axisMax) * PLOT_H + "px" }}>
            <span className="ytick">{tickFmt(t)}</span>
            <span className="gline" />
          </div>
        ))}
        <div className="groups">
          {SCENARIOS.map((sc, si) => (
            <div className="group" key={sc}>
              <div className="bars">
                {groups[si].map((c) => {
                  if (c.val == null) {
                    return (
                      <div className="barslot" key={c.v.key}>
                        <div className="na">{c.kind === "skip" ? "—" : "N/A"}</div>
                        <div className="na-base" style={{ background: c.kind === "skip" ? "var(--ed-text-disabled)" : vendorColor(c.v.key) }} />
                        {c.tip && <div className="tip">{c.tip}</div>}
                      </div>
                    );
                  }
                  const h = Math.max(2, (c.val / axisMax) * PLOT_H);
                  const short = c.kind === "short";
                  return (
                    <div className={"barslot" + (short ? " short" : "")} key={c.v.key}>
                      <div className="bval" style={{ bottom: h + 6 + "px" }}>
                        {fmtv(c.val)}
                        {c.sub && <span className="bsub">{c.sub}</span>}
                      </div>
                      <div className={"bar" + (short ? " failed" : "")} style={{ height: h + "px", background: short ? undefined : vendorColor(c.v.key), "--vc": vendorColor(c.v.key) }}>
                        <div className="tip">{c.tip}</div>
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

const KIND_RANK = { ok: 0, short: 1, skip: 2, na: 3 };
function sortCells(cells, better) {
  return cells.slice().sort((a, b) =>
    KIND_RANK[a.kind] - KIND_RANK[b.kind] ||
    (a.val == null || b.val == null ? 0 : better === "lower" ? a.val - b.val : b.val - a.val));
}

/* ───── Efficiency at a fixed offered load ───── */
const kRound = (v) => fmtK(v >= 10000 ? Math.round(v / 100) * 100 : Math.round(v / 10) * 10);
const LADDER_METRICS = [
  { key: "lpc", label: "Logs/sec per core", unit: "logs/sec/core", axis: "logs/sec per CPU core", better: "higher", get: (c) => c.lpc, fmtv: kRound,
    tip: "Logs/sec handled for each CPU core the agent uses. Higher = more work per core." },
  { key: "lpm", label: "Logs/sec per MB", unit: "logs/sec/MB", axis: "logs/sec per MB of memory", better: "higher", get: (c) => c.lpm, fmtv: fmt0,
    tip: "Logs/sec handled for each MB of memory the agent uses. Higher = leaner." },
  { key: "cpu", label: "CPU cores", unit: "cores", axis: "CPU cores used (1 = one full core)", better: "lower", get: (c) => c.cpu / 100, fmtv: (v) => v.toFixed(2), tickFmt: String,
    tip: "CPU cores the agent uses. 1.00 = one fully busy core. Lower is better." },
  { key: "mem", label: "Memory MB", unit: "MB", axis: "average memory, MB", better: "lower", get: (c) => c.mem, fmtv: fmt0,
    tip: "Average memory the agent uses, in MB. Lower is better." },
  { key: "ack", label: "Logs/sec reached", unit: "logs/sec", axis: "logs/sec accepted", better: "higher", get: (c) => c.ack, fmtv: kRound,
    tip: "Logs/sec the agent actually accepted versus what was sent. Matching the load means it kept up." },
];

const tierLabel = (t) => fmtK(t);
const LOAD_NAMES = ["Lowest", "Low", "Medium", "High", "Highest"];
// Name tiers from the top down so a longer ladder still ends at "Highest".
const loadName = (i, n) => LOAD_NAMES[LOAD_NAMES.length - n + i] ?? tierLabel(i);
const sustained = (c) => c && c.s === "ok" && c.cpu != null;
const measured = (c) => c && c.cpu != null;
// A shortfall at this tier, or a lower one (higher tiers are then skipped).
const failsAt = (c) => !!c && !sustained(c) && c.s !== "unsupported";
const ladderCell = (ladder, key, si, ti) => ladder?.agents?.[key]?.[si]?.[ti] ?? null;
const SHORT_REASON = {
  capacity_limited: "Agent rejected or failed requests",
  generator_limited: "Under-offered; agent limit not proven",
};

function CellTip({ v, sc, target, cell }) {
  const ok = sustained(cell);
  return (
    <>
      <div className="tip-v" style={{ color: vendorColor(v.key) }}>{v.name}</div>
      <div className="tip-s">{sc} · {fmt0(target)} logs/sec offered</div>
      {!ok && <div className="tip-warn">✕ Fell short · {SHORT_REASON[cell.s] ?? cell.s}</div>}
      <div className="tip-grid">
        <span>Reached</span><b>{fmt0(cell.ack)} logs/s</b>
        <span>CPU</span><b>{(cell.cpu / 100).toFixed(2)} cores</b>
        <span>Memory</span><b>{fmt0(cell.mem)} MB</b>
        <span>Per core</span><b>{fmt0(cell.lpc)} logs/s</b>
        <span>Per MB</span><b>{fmt0(cell.lpm)} logs/s</b>
      </div>
    </>
  );
}

function TierBars({ ladder, tierIndex, metric }) {
  const target = ladder.targets[tierIndex];
  const vals = [];
  const groups = SCENARIOS.map((sc, si) => sortCells(VENDORS.map((v) => {
    const cell = ladderCell(ladder, v.key, si, tierIndex);
    if (measured(cell) && metric.get(cell) != null) {
      const val = metric.get(cell);
      vals.push(val);
      return { v, val, kind: sustained(cell) ? "ok" : "short", sub: sustained(cell) || metric.key === "ack" ? null : kRound(cell.ack) + "/s",
        tip: <CellTip v={v} sc={sc} target={target} cell={cell} /> };
    }
    const skip = cell && cell.s === "skipped_after_shortfall";
    return { v, val: null, kind: skip ? "skip" : "na",
      tip: (<>
        <div className="tip-v" style={{ color: vendorColor(v.key) }}>{v.name}</div>
        <div className="tip-s">{sc}</div>
        <div className="tip-n">{skip ? "Not tested: fell short at a lower load" : "Scenario not supported"}</div>
      </>) };
  }), metric.better));
  const { max, ticks } = niceScale(vals.length ? Math.max(...vals) : 10);
  return <GroupedBars key={metric.key + tierIndex} groups={groups} axisMax={max} ticks={ticks} fmtv={metric.fmtv} tickFmt={metric.tickFmt} axisLabel={metric.axis} />;
}

/* ───── Trend: one metric at one tier across daily runs ───── */
function TrendChart({ history, scenarioIndex, target, metric, visible, hover, setHover }) {
  const W = 1040, H = 440, padL = 58, padR = 18, padT = 18, padB = 42;
  const plotW = W - padL - padR, plotH = H - padT - padB;
  const n = history.length;

  const series = VENDORS.map((v) => {
    let prevVer = null;
    return {
      v,
      pts: history.map((r, i) => {
        const ti = r.ladder ? r.ladder.targets.indexOf(target) : -1;
        const cell = ti < 0 ? null : ladderCell(r.ladder, v.key, scenarioIndex, ti);
        const val = measured(cell) ? metric.get(cell) : null;
        const ver = r.versions && r.versions[v.key] != null ? r.versions[v.key] : null;
        const changed = ver != null && prevVer != null && ver !== prevVer;
        if (ver != null) prevVer = ver;
        return { i, val, ok: sustained(cell), cell, date: r.date, ver, changed };
      }),
    };
  });

  const vals = [];
  series.forEach((s) => { if (visible.has(s.v.key)) s.pts.forEach((p) => { if (p.val != null) vals.push(p.val); }); });
  const { max: yMax, ticks } = niceScale(vals.length ? Math.max(...vals) : 10);
  const tickFmt = metric.tickFmt || fmtK;

  const X = (i) => (n <= 1 ? padL + plotW / 2 : padL + (i / (n - 1)) * plotW);
  const Y = (val) => padT + plotH - (val / yMax) * plotH;
  const step = Math.max(1, Math.ceil(n / 8));

  React.useEffect(() => { setHover(null); }, [scenarioIndex, target, metric.key]);

  return (
    <div className="trend-plot">
      <div className="yunit">{metric.axis}</div>
      <svg viewBox={`0 0 ${W} ${H}`} style={{ width: "100%", height: "auto", display: "block" }}>
        {ticks.map((t) => (
          <g key={t}>
            <line x1={padL} x2={W - padR} y1={Y(t)} y2={Y(t)} stroke="var(--ed-border-1)" strokeWidth="1" />
            <text x={padL - 10} y={Y(t)} textAnchor="end" dominantBaseline="middle" fontFamily="var(--ed-font-mono)" fontSize="11" fill="var(--ed-text-secondary)">{tickFmt(t)}</text>
          </g>
        ))}
        <line x1={padL} x2={W - padR} y1={Y(0)} y2={Y(0)} stroke="var(--ed-border-2)" strokeWidth="1" />
        {history.map((r, i) => (i % step === 0 || i === n - 1) ? (
          <text key={i} x={X(i)} y={H - padB + 20} textAnchor="middle" fontFamily="var(--ed-font-mono)" fontSize="10.5" fill="var(--ed-text-secondary)">{(r.date ?? "").slice(5)}</text>
        ) : null)}
        {series.map((s) => {
          if (!visible.has(s.v.key)) return null;
          const color = vendorColor(s.v.key);
          const segs = []; let cur = [];
          s.pts.forEach((p) => { if (p.val == null || !p.ok) { if (cur.length) segs.push(cur); cur = []; } else cur.push(p); });
          if (cur.length) segs.push(cur);
          return (
            <g key={s.v.key}>
              {segs.map((seg, k) => (
                <polyline key={k} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round"
                  points={seg.map((p) => `${X(p.i)},${Y(p.val)}`).join(" ")} />
              ))}
              {s.pts.map((p) => {
                if (p.val == null) return null;
                const cx = X(p.i), cy = Y(p.val);
                const handlers = {
                  style: { cursor: "pointer" },
                  onMouseEnter: () => setHover({ v: s.v, cell: p.cell, date: p.date, ver: p.ver, changed: p.changed, x: cx, y: cy }),
                  onMouseLeave: () => setHover(null),
                };
                if (!p.ok) {
                  return <circle key={p.i} cx={cx} cy={cy} r="3.2" fill="none" stroke={color} strokeWidth="1.4" strokeDasharray="2 2" opacity="0.6" {...handlers} />;
                }
                if (p.changed) {
                  return <path key={p.i} d={`M ${cx} ${cy - 5} L ${cx + 5} ${cy} L ${cx} ${cy + 5} L ${cx - 5} ${cy} Z`}
                    fill="var(--ed-surface-1)" stroke={color} strokeWidth="2" {...handlers} />;
                }
                return <circle key={p.i} cx={cx} cy={cy} r="3.2" fill="var(--ed-surface-1)" stroke={color} strokeWidth="2" {...handlers} />;
              })}
            </g>
          );
        })}
      </svg>
      {hover && (
        <div className="trend-tip" style={{ left: (hover.x / W * 100) + "%", top: (hover.y / H * 100) + "%" }}>
          <CellTip v={hover.v} sc={SCENARIOS[scenarioIndex] + " · " + hover.date} target={target} cell={hover.cell} />
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
  const [view, setView] = React.useState(QS.get("view") === "trend" ? "trend" : "tier");
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
  const visible = new Set(VENDORS.map((v) => v.key).filter((k) => !hidden.has(k)));
  const ladder = latest.ladder;
  const lm = LADDER_METRICS.find((m) => m.key === effMetric);
  const tierI = tierIdx ?? (ladder ? ladder.targets.length - 1 : 0);
  if (!ladder) return <div className="wrap"><div className="card state">The latest run has no fixed-rate tier data.</div></div>;
  const target = ladder.targets[tierI];
  const tierView = view === "tier";
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
                {lm.label + " at " + loadName(tierI, ladder.targets.length).toLowerCase() + " load (" + fmt0(target) + " logs/sec in) · " + (tierView ? "" : SCENARIOS[scenarioIdx] + " over time · ") + lm.better + " is better"}
              </p>
            </div>
          </div>
          <div className="controls">
            <div className="seg">
              <button className={view === "tier" ? "on" : ""} onClick={() => { setView("tier"); setHover(null); }}>By tier</button>
              <button className={view === "trend" ? "on" : ""} onClick={() => { setView("trend"); setHover(null); }}>Trend</button>
            </div>
          </div>
        </header>

        <div className="subcontrols">
          <div className="seg seg-scn">
            {ladder.targets.map((t, i) => [t, i]).reverse().map(([t, i]) => (
              <button key={t} className={"has-tip" + (tierI === i ? " on" : "")} onClick={() => setTierIdx(i)}
                data-tip={`${fmt0(t)} logs/sec sent to each agent`}>{loadName(i, ladder.targets.length)}</button>
            ))}
          </div>
          <div className="seg seg-scn">
            {LADDER_METRICS.map((m) => (
              <button key={m.key} className={"has-tip wrap-tip" + (effMetric === m.key ? " on" : "")} onClick={() => setEffMetric(m.key)} data-tip={m.tip}>{m.label}</button>
            ))}
          </div>
        </div>
        {view === "trend" && (
          <div className="subcontrols subrow">
            <div className="ctl">
              <span className="ctl-label">Scenario</span>
              <div className="seg seg-scn">
                {SCENARIOS.map((sc, i) => (
                  <button key={sc} className={scenarioIdx === i ? "on" : ""} onClick={() => setScenarioIdx(i)}>{sc}</button>
                ))}
              </div>
            </div>
          </div>
        )}

        <div className="legend">
          {VENDORS.map((v) => {
            const off = clickable && hidden.has(v.key);
            const fails = failsTier(v.key);
            return (
              <div className={"leg" + (clickable ? " leg-click" : "") + (off ? " off" : "") + (fails ? " fails" : "")} key={v.key} onClick={() => toggle(v.key)}
                title={fails ? `Could not sustain ${fmt0(target)} logs/sec` : undefined}>
                <span className="sw" style={{ background: vendorColor(v.key) }} />
                <span className={v.key === "red" ? "leg-ed" : ""}>{v.name}</span>
                {latest.versions?.[v.key] && <span className="leg-ver">{latest.versions[v.key]}</span>}
              </div>
            );
          })}
        </div>

        <div className="viewbody">
          {tierView && <TierBars ladder={ladder} tierIndex={tierI} metric={lm} />}
          {view === "trend" && <TrendChart history={history} scenarioIndex={scenarioIdx} target={target} metric={lm} visible={visible} hover={hover} setHover={setHover} />}
        </div>

        <footer className="foot">
          <span>{latest.date} · run {latest.runId}{view === "trend" ? " · " + history.length + " runs" : ""}</span>
          <span className="na-key">
            {tierView ? "Best on the left · dashed = fell short of this load (small label = logs/sec it reached) · — = not tested after a lower shortfall · N/A = unsupported"
              : "Click legend to hide agents · ◆ = agent version change · dashed hollow point = fell short of this load that day (value is what it reached)"}
          </span>
        </footer>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
