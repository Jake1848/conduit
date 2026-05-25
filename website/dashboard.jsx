/* ============================================================
   CONDUIT — dashboard.jsx
   Console mockup: KPIs, area chart, bar chart, agents, live tx
   ============================================================ */

/* ----------------------- LINE / AREA CHART ----------------------- */
function LineChart({ data, width = 600, height = 220 }) {
  const padding = { t: 18, r: 16, b: 28, l: 44 };
  const innerW = width - padding.l - padding.r;
  const innerH = height - padding.t - padding.b;
  const max = Math.max(...data) * 1.12 || 1;
  const min = Math.min(...data) * 0.85;
  const range = max - min || 1;

  function x(i, len) { return padding.l + (i / (len - 1)) * innerW; }
  function y(v) { return padding.t + innerH - ((v - min) / range) * innerH; }

  const pts = data.map((v, i) => [x(i, data.length), y(v)]);
  const line = pts.reduce((acc, [px, py], i) => {
    if (i === 0) return `M ${px} ${py}`;
    const [ppx, ppy] = pts[i - 1];
    const cx1 = ppx + (px - ppx) * 0.5;
    const cx2 = ppx + (px - ppx) * 0.5;
    return acc + ` C ${cx1} ${ppy} ${cx2} ${py} ${px} ${py}`;
  }, '');
  const area = line + ` L ${padding.l + innerW} ${padding.t + innerH} L ${padding.l} ${padding.t + innerH} Z`;

  const yTicks = [0, 0.5, 1].map(p => ({
    y: padding.t + innerH - p * innerH,
    label: fmt(min + range * p, { compact: true })
  }));
  const xLabels = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
  const xStep = innerW / (xLabels.length - 1);

  return (
    <svg className="chart" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <g className="grid">
        {yTicks.map((t, i) => (
          <line key={i} x1={padding.l} x2={padding.l + innerW} y1={t.y} y2={t.y} />
        ))}
      </g>
      <g className="axis">
        {yTicks.map((t, i) => (
          <text key={i} x={padding.l - 10} y={t.y + 3} textAnchor="end">{t.label}</text>
        ))}
        {xLabels.map((l, i) => (
          <text key={i} x={padding.l + i * xStep} y={height - 8} textAnchor="middle">{l}</text>
        ))}
      </g>
      <path className="area-gold" d={area} />
      <path className="line-gold" d={line} />
      {pts.length > 0 && (
        <>
          <circle className="pt-ring" cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="8" />
          <circle className="pt-gold" cx={pts[pts.length - 1][0]} cy={pts[pts.length - 1][1]} r="3" />
        </>
      )}
    </svg>
  );
}

/* ----------------------- BAR CHART ----------------------- */
function BarChart({ data, accentCount = 5 }) {
  const max = Math.max(...data) || 1;
  return (
    <>
      <div className="bars">
        {data.map((v, i) => (
          <div key={i}
               className={'bar' + (i < data.length - accentCount ? ' muted' : '')}
               style={{ height: `${Math.max(8, (v / max) * 100)}%`, animationDelay: `${i * 30}ms` }} />
        ))}
      </div>
      <div className="bars-axis">
        {data.map((_, i) => (i % 2 === 0 ? <span key={i}>{String(i * 2).padStart(2, '0')}</span> : <span key={i}>&nbsp;</span>))}
      </div>
    </>
  );
}

/* ----------------------- DASHBOARD ----------------------- */
function Dashboard() {
  const [tab, setTab] = React.useState('Wallets');
  const sideItems = [
    { lbl: 'Overview',  count: '' },
    { lbl: 'Wallets',   count: '2,840' },
    { lbl: 'Policies',  count: '18' },
    { lbl: 'Network',   count: '412' },
    { lbl: 'Audit Log', count: '∞' },
    { lbl: 'Webhooks',  count: '6' },
  ];

  // chart series
  const chartData = React.useMemo(() => {
    return makeSeries(28, 17, { trend: 0.55, vol: 0.18, base: 0.3 }).map(v => Math.round(v * 32000));
  }, []);
  const bars = React.useMemo(() => {
    return makeSeries(14, 99, { trend: 0.4, vol: 0.4, base: 0.4 }).map(v => Math.round(v * 100));
  }, []);

  // tx feed
  const routes = [
    { from: 'inference-router-04', to: 'gpu-pool-aws-us',      dir: 'out' },
    { from: 'compute-broker-01',   to: 'compute-node-7',       dir: 'out' },
    { from: 'data-buyer-21',       to: 'agent-fleet-prod',     dir: 'in'  },
    { from: 'agent-fleet-prod',    to: 'storage-mesh-eu',      dir: 'out' },
    { from: 'treasury-rebalancer', to: 'lnd.conduit.energy',   dir: 'out' },
    { from: 'm2m-router',          to: 'merchant-bot-09',      dir: 'out' },
    { from: 'partner-agent',       to: 'agent-fleet-prod',     dir: 'in'  },
    { from: 'render-bot-3',        to: 'gpu-spot-04',          dir: 'out' },
  ];
  const satOptions = [12, 47, 88, 150, 220, 320, 1240, 64, 410, 96, 2040, 18, 540];
  const msOptions  = [31, 36, 39, 41, 44, 47, 51, 58];
  function pick(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
  function now() {
    const d = new Date();
    const p = (n) => String(n).padStart(2, '0');
    return p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  function mkTx() {
    const r = pick(routes);
    return { ...r, sats: pick(satOptions), ms: pick(msOptions), ts: now(), id: Math.random().toString(36).slice(2, 9) };
  }
  const [txs, setTxs] = React.useState(() => Array.from({ length: 6 }, mkTx));
  const [containerRef, inView] = useInView({ threshold: 0.15 });
  React.useEffect(() => {
    if (!inView) return;
    const t = setInterval(() => {
      setTxs(prev => [mkTx(), ...prev].slice(0, 6));
    }, 1700);
    return () => clearInterval(t);
  }, [inView]);

  const agents = [
    { c: 'cyan',   av: 'IR', nm: 'inference-router-04', sub: 'scope: api-payments · 482 tx today',  bal: '12,408', usd: '$8.27' },
    { c: 'purple', av: 'CB', nm: 'compute-broker-01',   sub: 'scope: gpu-spot · 1,204 tx today',    bal: '38,210', usd: '$25.47' },
    { c: 'gold',   av: 'TR', nm: 'treasury-rebalancer', sub: 'scope: read+write · policy: tight',   bal: '2.1M',   usd: '$1,398' },
    { c: 'amber',  av: 'DM', nm: 'data-buyer-09',       sub: 'scope: counterparty:allowlist',       bal: '4,820',  usd: '$3.21' },
    { c: 'green',  av: 'AG', nm: 'agent-to-agent-router', sub: 'scope: m2m · 8,210 tx today',       bal: '94,108', usd: '$62.74' },
  ];

  return (
    <div className="dashboard-wrap" data-reveal data-rd="2" ref={containerRef}>
      <div className="dashboard">
        <div className="dash-chrome">
          <div className="dots"><span /><span /><span /></div>
          <div className="url">conduit.energy / console / <b>agent-fleet-prod</b></div>
          <div className="env"><span className="d" />MAINNET</div>
          <div className="actions">
            <button>SHARE</button>
            <button>EXPORT</button>
          </div>
        </div>

        <div className="dash-body">
          <aside className="dash-side">
            <h6>WORKSPACE</h6>
            {sideItems.map(s => (
              <div key={s.lbl} className={'nav-item' + (tab === s.lbl ? ' active' : '')} onClick={() => setTab(s.lbl)}>
                <span>{s.lbl}</span>
                {s.count && <span className="count">{s.count}</span>}
              </div>
            ))}
            <div className="divider" />
            <h6>DEVELOPER</h6>
            <div className="nav-item">API Keys <span className="count">4</span></div>
            <div className="nav-item">Sandbox</div>
            <div className="nav-item">Docs ↗</div>
            <div className="profile">
              <div className="av">RB</div>
              <div className="nm">Rao Bhargava<small>admin · agent-fleet-prod</small></div>
            </div>
          </aside>

          <main className="dash-main">
            {/* KPIs */}
            <div className="kpis">
              <div className="kpi">
                <div className="lbl">Treasury Balance</div>
                <div className="v gold">0.4218<span className="u">BTC</span></div>
                <div className="d">≈ $28,847.20 · <b>+ 1.42%</b> 24h</div>
                <div className="spark"><Sparkline data={makeSeries(28, 4, { trend: 0.5, vol: 0.18, base: 0.3 })} /></div>
              </div>
              <div className="kpi">
                <div className="lbl">Active Agents</div>
                <div className="v">2,840</div>
                <div className="d"><b>+ 12</b> this hour</div>
                <div className="spark"><Sparkline data={makeSeries(28, 22, { trend: 0.7, vol: 0.10, base: 0.2 })} /></div>
              </div>
              <div className="kpi">
                <div className="lbl">Tx / minute</div>
                <div className="v">14,288</div>
                <div className="d">peak <b>32,144</b></div>
                <div className="spark"><Sparkline data={makeSeries(28, 71, { trend: 0.35, vol: 0.28, base: 0.4 })} /></div>
              </div>
              <div className="kpi">
                <div className="lbl">Avg Settlement</div>
                <div className="v">47<span className="u">ms</span></div>
                <div className="d">p99 <b>118ms</b></div>
                <div className="spark"><Sparkline data={makeSeries(28, 88, { trend: -0.3, vol: 0.15, base: 0.6 })} /></div>
              </div>
            </div>

            {/* Charts row */}
            <div className="dash-row">
              <div className="panel">
                <div className="head">
                  <h4>Routed Volume <span className="sub">· 7d</span></h4>
                  <span className="live-tag">LIVE</span>
                </div>
                <LineChart data={chartData} />
                <div className="chart-stats" style={{ marginTop: 10 }}>
                  <div className="chart-stat"><div className="l">HIGH</div><div className="v">{fmt(Math.max(...chartData), { compact: true })}</div></div>
                  <div className="chart-stat"><div className="l">LOW</div><div className="v">{fmt(Math.min(...chartData), { compact: true })}</div></div>
                  <div className="chart-stat"><div className="l">AVG</div><div className="v">{fmt(chartData.reduce((a,b)=>a+b,0)/chartData.length, { compact: true })}</div></div>
                </div>
              </div>

              <div className="panel">
                <div className="head">
                  <h4>Hourly Throughput <span className="sub">· tx/h</span></h4>
                  <span className="live-tag">24h</span>
                </div>
                <BarChart data={bars} />
              </div>
            </div>

            {/* Agents + tx feed */}
            <div className="dash-row-2">
              <div className="panel">
                <div className="head">
                  <h4>Agent Wallets</h4>
                  <div className="controls">
                    <span className="pill active">ALL</span>
                    <span className="pill">LIVE</span>
                    <span className="pill">FROZEN</span>
                  </div>
                </div>
                <div className="agents">
                  {agents.map(a => (
                    <div className="agent" data-c={a.c} key={a.nm}>
                      <div className="av">{a.av}</div>
                      <div className="nm"><div>{a.nm}</div><small>{a.sub}</small></div>
                      <div className="bal">{a.bal} sats<small>{a.usd}</small></div>
                      <div className="status"><span className="pill"><span className="d" />LIVE</span></div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="panel">
                <div className="head">
                  <h4>Live Transactions</h4>
                  <span className="live-tag">STREAMING</span>
                </div>
                <div className="tx-feed">
                  {txs.map(t => (
                    <div className={'tx-row ' + t.dir} key={t.id}>
                      <div className="dir">{t.dir === 'out' ? '→' : '←'}</div>
                      <div className="meta">
                        <div className="route">{t.from}<span>{t.dir === 'out' ? '→' : '←'}</span>{t.to}</div>
                        <div className="ts">{t.ts}</div>
                      </div>
                      <div className="sats">{t.sats.toLocaleString()} sats</div>
                      <div className="ms">{t.ms}ms</div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </main>
        </div>
      </div>
    </div>
  );
}

/* ----------------------- CONSOLE SECTION ----------------------- */
function ConsoleSection() {
  return (
    <section className="section col" id="console">
      <div className="head-2">
        <div data-reveal>
          <div className="eyebrow">04 — Inside the Console</div>
          <h2>A control plane for<br /><em>fleets of agents.</em></h2>
        </div>
        <p data-reveal data-rd="1">Watch every wallet, every signature, every routed payment in real time. Set policy, freeze keys, reconcile to the satoshi — without leaving the page.</p>
      </div>
      <Dashboard />
    </section>
  );
}

window.LineChart = LineChart;
window.BarChart = BarChart;
window.Dashboard = Dashboard;
window.ConsoleSection = ConsoleSection;
