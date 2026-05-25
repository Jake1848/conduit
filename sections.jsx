/* ============================================================
   CONDUIT — sections.jsx
   Nav, Hero (Portal), StatStrip, Problem, Layer, SDK, Cases,
   Security, Vision, Final, Footer
   ============================================================ */

/* ----------------------- LOGO MARK ----------------------- */
function LogoMark(props) {
  return <span className="nav-mark" style={{ width: props.size || 32, height: props.size || 32 }} aria-hidden="true" />;
}

/* ----------------------- PORTAL ----------------------- */
function Portal() {
  return (
    <div className="portal" aria-hidden="true">
      <div className="portal-glow" />
      <span className="portal-hud-c tl" />
      <span className="portal-hud-c tr" />
      <span className="portal-hud-c bl" />
      <span className="portal-hud-c br" />
      <span className="portal-tag top">CONDUIT · NODE 001</span>
      <span className="portal-tag bottom">⚡ LIGHTNING · MAINNET</span>

      <svg viewBox="0 0 480 480">
        <defs>
          <mask id="ringMask">
            <rect width="480" height="480" fill="white" />
            <rect x="0" y="218" width="480" height="12" fill="black" />
            <rect x="0" y="250" width="480" height="12" fill="black" />
          </mask>
        </defs>

        {/* faint orbits */}
        <circle cx="240" cy="240" r="232" fill="none" stroke="rgba(212,160,23,0.16)" />
        <g style={{ transformOrigin: '240px 240px', animation: 'spin 80s linear infinite' }}>
          <circle cx="240" cy="240" r="210" fill="none" stroke="rgba(212,160,23,0.28)" strokeDasharray="1 8" />
        </g>
        <g style={{ transformOrigin: '240px 240px', animation: 'spin 60s linear infinite reverse' }}>
          <circle cx="240" cy="240" r="188" fill="none" stroke="rgba(212,160,23,0.16)" strokeDasharray="2 14" />
        </g>

        {/* ripples */}
        <circle cx="240" cy="240" r="120" fill="none" stroke="rgba(255,224,138,0.4)" strokeWidth="1.2">
          <animate attributeName="r" from="120" to="206" dur="3.4s" repeatCount="indefinite" />
          <animate attributeName="opacity" from="0.7" to="0" dur="3.4s" repeatCount="indefinite" />
        </circle>
        <circle cx="240" cy="240" r="120" fill="none" stroke="rgba(255,224,138,0.4)" strokeWidth="1.2">
          <animate attributeName="r" from="120" to="206" dur="3.4s" begin="1.1s" repeatCount="indefinite" />
          <animate attributeName="opacity" from="0.7" to="0" dur="3.4s" begin="1.1s" repeatCount="indefinite" />
        </circle>
        <circle cx="240" cy="240" r="120" fill="none" stroke="rgba(255,224,138,0.4)" strokeWidth="1.2">
          <animate attributeName="r" from="120" to="206" dur="3.4s" begin="2.2s" repeatCount="indefinite" />
          <animate attributeName="opacity" from="0.7" to="0" dur="3.4s" begin="2.2s" repeatCount="indefinite" />
        </circle>

        {/* radial core glow */}
        <circle cx="240" cy="240" r="146" fill="url(#goldRad)" opacity="0.55" />

        {/* tick marks around the ring */}
        <g stroke="rgba(212,160,23,0.5)" strokeWidth="1">
          {Array.from({ length: 24 }).map((_, i) => {
            const a = (i * 15) * Math.PI / 180;
            const r1 = 162, r2 = i % 6 === 0 ? 172 : 168;
            const x1 = 240 + Math.cos(a) * r1, y1 = 240 + Math.sin(a) * r1;
            const x2 = 240 + Math.cos(a) * r2, y2 = 240 + Math.sin(a) * r2;
            return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} />;
          })}
        </g>

        {/* The thick gold C ring with two horizontal gaps */}
        <g mask="url(#ringMask)">
          <circle cx="240" cy="240" r="140" fill="none" stroke="url(#goldStroke)" strokeWidth="40"
            style={{ filter: 'drop-shadow(0 0 24px rgba(212,160,23,0.55)) drop-shadow(0 0 60px rgba(212,160,23,0.2))' }} />
          <circle cx="240" cy="240" r="120" fill="none" stroke="rgba(255,224,138,0.9)" strokeWidth="0.6" opacity="0.55" />
          <circle cx="240" cy="240" r="160" fill="none" stroke="rgba(110,79,8,0.9)" strokeWidth="0.6" opacity="0.55" />
        </g>

        {/* two parallel conduit bars passing all the way through */}
        <rect x="0" y="220" width="480" height="8" fill="url(#goldH)"
          style={{ filter: 'drop-shadow(0 0 8px rgba(212,160,23,0.5))' }} />
        <rect x="0" y="252" width="480" height="8" fill="url(#goldH)"
          style={{ filter: 'drop-shadow(0 0 8px rgba(212,160,23,0.5))' }} />

        {/* flowing light dashes */}
        <line x1="0" y1="224" x2="480" y2="224" stroke="#FFE08A" strokeWidth="2" strokeDasharray="6 18"
          style={{ animation: 'flow 1.8s linear infinite' }} />
        <line x1="0" y1="256" x2="480" y2="256" stroke="#FFE08A" strokeWidth="2" strokeDasharray="6 18"
          style={{ animation: 'flow 1.8s linear infinite' }} />

        {/* center diamond — energy pulse */}
        <g style={{ transformOrigin: '240px 240px', animation: 'pulseD 3s ease-in-out infinite' }}>
          <path d="M 240 174 L 298 240 L 240 306 L 182 240 Z" fill="url(#goldFill)"
            style={{ filter: 'drop-shadow(0 0 18px rgba(255,224,138,0.85)) drop-shadow(0 0 48px rgba(212,160,23,0.55))' }} />
          <path d="M 240 198 L 280 240 L 240 282 L 200 240 Z" fill="#1a1308" opacity="0.45" />
          <circle cx="240" cy="240" r="6" fill="#FFE08A" />
        </g>
      </svg>
    </div>
  );
}

/* ----------------------- NAV ----------------------- */
function Nav() {
  const scrolled = useScrolled(24);
  return (
    <nav className={'nav' + (scrolled ? ' scrolled' : '')}>
      <a href="#top" className="nav-brand">
        <LogoMark />
        <span className="nav-wordmark">CONDUIT</span>
      </a>
      <div className="nav-links">
        <a href="#layer">Product</a>
        <a href="#sdk">Developers</a>
        <a href="#console">Console</a>
        <a href="#cases">Use Cases</a>
        <a href="#security">Security</a>
      </div>
      <Magnetic strength={6}>
        <a className="nav-cta" href="#final">Request Access</a>
      </Magnetic>
      <button className="nav-burger" aria-label="Open menu"><span /></button>
    </nav>
  );
}

window.LogoMark = LogoMark;
window.Portal = Portal;
window.Nav = Nav;

/* ----------------------- HERO ----------------------- */
function Hero() {
  const samples = [
    [150, 47], [82, 39], [220, 53], [1240, 61], [44, 31],
    [310, 49], [98, 42], [560, 58], [27, 34], [410, 51]
  ];
  const [i, setI] = React.useState(0);
  React.useEffect(() => { const t = setInterval(() => setI(v => (v + 1) % samples.length), 2400); return () => clearInterval(t); }, []);
  const [sats, ms] = samples[i];

  const btcRef = React.useRef(null);
  React.useEffect(() => {
    let v = 68420.17;
    const t = setInterval(() => {
      v += (Math.random() - 0.5) * 16;
      if (btcRef.current) btcRef.current.textContent = v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }, 1800);
    return () => clearInterval(t);
  }, []);

  return (
    <section className="hero col" id="top">
      <div>
        <div className="hero-status" data-reveal>
          <span className="dot" />
          <span className="live">LIVE</span>
          <span className="sep">/</span>
          <span>Settled</span>
          <span className="gold">{sats.toLocaleString()} sats</span>
          <span>in</span>
          <span className="gold">{ms}ms</span>
        </div>
        <h1 data-reveal data-rd="1">
          Autonomous AI<br />
          needs <span className="em">autonomous</span><br />
          money.
        </h1>
        <p className="hero-sub" data-reveal data-rd="2">
          Conduit gives AI agents Bitcoin-native wallets, Lightning settlement, programmable spending controls, and machine-to-machine payments — <em>without banks, cards, or human permission.</em>
        </p>
        <div className="hero-actions" data-reveal data-rd="3">
          <Magnetic strength={8}>
            <a className="btn btn-primary" href="#final">Request Early Access <span className="btn-arrow">→</span></a>
          </Magnetic>
          <Magnetic strength={8}>
            <a className="btn btn-ghost" href="#sdk">Read the Docs</a>
          </Magnetic>
        </div>
      </div>

      <div data-reveal data-rd="2"><Portal /></div>

      <div className="hero-foot">
        <div className="stack">
          <span>BTC / USD</span>
          <span className="v" ref={btcRef}>68,420.17</span>
        </div>
        <div className="scroll-hint">
          <span>SCROLL</span>
          <span className="line" />
        </div>
        <div className="stack" style={{ textAlign: 'right' }}>
          <span>NETWORK</span>
          <span className="v">LIGHTNING · MAINNET</span>
        </div>
      </div>
    </section>
  );
}

/* ----------------------- STAT STRIP ----------------------- */
function StatStrip() {
  const items = [
    { lbl: 'Assets Under Policy', to: 48.2,  decimals: 1, prefix: '$', suffix: 'M', delta: '+ $4.2M · 30d', seed: 12 },
    { lbl: 'M2M Settlements',     to: 12.8,  decimals: 1, prefix: '',  suffix: 'M', delta: '+ 38% MoM',    seed: 34 },
    { lbl: 'Settlement Latency',  to: 47,    decimals: 0, prefix: '',  suffix: '',  delta: 'p99 · 118ms', seed: 56, dn: true },
    { lbl: 'Agents Live',         to: 2840,  decimals: 0, prefix: '',  suffix: '',  delta: '+ 12 / hr',   seed: 78 },
  ];
  return (
    <div className="strip" data-reveal>
      {items.map((it, i) => (
        <div className="strip-item" key={it.lbl}>
          <div className="num">
            <CountUp to={it.to} decimals={it.decimals} prefix={it.prefix} duration={1400 + i * 120} />
            <span className="unit">{it.suffix}</span>
          </div>
          <div className="lbl">{it.lbl}</div>
          <div className={'delta' + (it.dn ? ' dn' : '')}>{it.delta}</div>
          <div className="spark-wrap">
            <Sparkline data={makeSeries(28, it.seed, { trend: it.dn ? -0.3 : 0.45, vol: 0.16, base: it.dn ? 0.6 : 0.35 })} />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ----------------------- PROBLEM ----------------------- */
function Problem() {
  const cells = [
    { idx: '01 / NO IDENTITY',
      h: 'Agents can\u2019t pass KYC.',
      p: 'Banks and card networks require a human legal identity, a date of birth, a tax ID. An autonomous program has none of these — and never will.',
      lbl: 'verified bank accounts · 2026',
      stat: '0' },
    { idx: '02 / TOO EXPENSIVE',
      h: 'Card fees eat micropayments alive.',
      p: 'A 30¢ swipe fee on a $0.001 inference call is a 30,000% tax. Card rails were designed for groceries, not API tokens metered in milliseconds.',
      lbl: 'card min · LN floor',
      stat: '$0.30 / 0.1 sat' },
    { idx: '03 / TOO SLOW',
      h: 'Three-day settlement is a lifetime.',
      p: 'Machines transact in milliseconds. Agents waiting on ACH, wire windows, or T+2 clearing simply cannot operate. The clock is not on their side.',
      lbl: 'ACH vs Lightning',
      stat: '2 days / 47ms' },
  ];
  return (
    <section className="section col" id="problem">
      <div className="head-2">
        <div data-reveal>
          <div className="eyebrow">01 — The Gap</div>
          <h2>Credit cards were<br />built for <em>humans.</em></h2>
        </div>
        <p data-reveal data-rd="1">AI agents can't open bank accounts, pass KYC, or wait three business days for settlement. The financial system has no entry point for software that thinks for itself.</p>
      </div>
      <div className="problem-grid">
        {cells.map((c, i) => (
          <article className="problem-cell" key={c.idx} data-reveal data-rd={i + 1}>
            <div className="idx">{c.idx}</div>
            <h3>{c.h}</h3>
            <p>{c.p}</p>
            <div className="stat"><span>{c.lbl}</span><b>{c.stat}</b></div>
          </article>
        ))}
      </div>
    </section>
  );
}

window.Hero = Hero;
window.StatStrip = StatStrip;
window.Problem = Problem;

/* ----------------------- LAYER ----------------------- */
function Layer() {
  const nodes = [
    { lbl: 'SOURCE', nm: 'AI Agent',      ico: 'A', c: '#67E8F9' },
    { lbl: 'WALLET', nm: 'Conduit',       ico: 'C', c: '#FFE08A' },
    { lbl: 'RULES',  nm: 'Policy Engine', ico: 'P', c: '#C084FC' },
    { lbl: 'SETTLE', nm: 'Lightning',     ico: '⚡', c: '#F59E0B' },
    { lbl: 'FINAL',  nm: 'Bitcoin',       ico: '₿', c: '#F7931A' },
  ];
  const features = [
    { n: '01', t: 'Agent Wallets',
      b: 'Spin up non-custodial Bitcoin wallets in one API call. Each agent gets its own keys, its own ledger, its own identity — no human required.',
      tg: 'Wallet · Keys · Identity' },
    { n: '02', t: 'Spending Policies',
      b: 'Declarative budgets, allowlists, velocity limits, and counterparty rules — enforced server-side before any sats leave the wallet.',
      tg: 'Limits · Rules · Override' },
    { n: '03', t: 'Lightning Settlement',
      b: 'Sub-second, sub-cent payments routed through our managed Lightning mesh. We handle channel liquidity so your agents do not have to.',
      tg: 'Sub-50ms · Routed · Managed' },
    { n: '04', t: 'Bitcoin Finality',
      b: 'Every transaction lands on the most credibly neutral monetary network in existence. No issuer, no chargebacks, no permission.',
      tg: 'Mainnet · Final · Neutral' },
  ];
  return (
    <section className="section col" id="layer">
      <div className="layer-head" data-reveal>
        <div className="eyebrow">02 — The Conduit Layer</div>
        <h2>The monetary operating layer<br />for <em>autonomous</em> machines.</h2>
      </div>
      <div className="pipeline" data-reveal data-rd="1">
        <span className="pipe-pulse" />
        {nodes.map(n => (
          <div className="pipe-node" key={n.nm} style={{ '--accent': n.c }}>
            <div className="ico" style={{ background: n.c + '1f', borderColor: n.c + '44', color: n.c }}>{n.ico}</div>
            <div className="lbl">{n.lbl}</div>
            <div className="nm">{n.nm}</div>
          </div>
        ))}
      </div>
      <div className="feature-grid">
        {features.map((f, i) => (
          <article className="feature-card" key={f.t} data-reveal data-rd={(i % 4) + 1}>
            <div className="num">{f.n} / PRIMITIVE</div>
            <h3>{f.t}</h3>
            <p>{f.b}</p>
            <div className="tag">{f.tg}</div>
          </article>
        ))}
      </div>
    </section>
  );
}

/* ----------------------- SDK ----------------------- */
const SDK_SAMPLES = {
  'Python': [
    { c: 'com', t: '# autonomous_agent.py — Conduit SDK quickstart' },
    null,
    { c: 'kw',  t: 'from' }, { c: 'pun', t: ' conduit ' }, { c: 'kw', t: 'import' }, { c: 'pun', t: ' ' }, { c: 'cls', t: 'Agent' }, { c: 'pun', t: ', ' }, { c: 'cls', t: 'Policy' }, 'NL',
    null,
    { c: 'pun', t: 'agent = ' }, { c: 'cls', t: 'Agent' }, { c: 'pun', t: '.' }, { c: 'fn', t: 'create' }, { c: 'pun', t: '(' }, 'NL',
    { c: 'pun', t: '    name=' }, { c: 'str', t: '"compute-router-7"' }, { c: 'pun', t: ',' }, 'NL',
    { c: 'pun', t: '    policy=' }, { c: 'cls', t: 'Policy' }, { c: 'pun', t: '(' }, { c: 'pun', t: 'max_per_hour=' }, { c: 'num', t: '10_000' }, { c: 'pun', t: '),' }, 'NL',
    { c: 'pun', t: ')' }, 'NL',
    null,
    { c: 'com', t: '# pay another agent over Lightning, settled to Bitcoin' }, 'NL',
    { c: 'pun', t: 'receipt = agent.' }, { c: 'fn', t: 'pay' }, { c: 'pun', t: '(' }, 'NL',
    { c: 'pun', t: '    to=' }, { c: 'str', t: '"compute-node-7@lnd.conduit.energy"' }, { c: 'pun', t: ',' }, 'NL',
    { c: 'pun', t: '    sats=' }, { c: 'num', t: '150' }, { c: 'pun', t: ',' }, 'NL',
    { c: 'pun', t: '    memo=' }, { c: 'str', t: '"inference · 1.2K tokens"' }, { c: 'pun', t: ',' }, 'NL',
    { c: 'pun', t: ')' }, 'NL',
    null,
    { c: 'fn',  t: 'print' }, { c: 'pun', t: '(receipt.hash, receipt.settled_in_ms)' }, 'NL',
    { c: 'com', t: '# → 4a8c…f1   47' },
  ],
};

function rowsFromTokens(tokens) {
  const rows = [[]];
  for (const tk of tokens) {
    if (tk === null) { rows.push([]); rows.push([]); }
    else if (tk === 'NL') { rows.push([]); }
    else { rows[rows.length - 1].push(tk); }
  }
  // collapse — each row is one line
  return rows;
}

function SDK() {
  const [lang, setLang] = React.useState('Python');
  const [copied, setCopied] = React.useState(false);
  const langs = ['Python', 'TypeScript', 'Rust', 'MCP Native'];
  // for langs other than Python, render Python sample (placeholder) — same look
  const tokens = SDK_SAMPLES[lang] || SDK_SAMPLES['Python'];
  const lines = rowsFromTokens(tokens).slice(0, 19);

  function copy() {
    const raw = lines.map(row => row.map(t => t.t).join('')).join('\n');
    navigator.clipboard && navigator.clipboard.writeText(raw);
    setCopied(true);
    setTimeout(() => setCopied(false), 1400);
  }

  const filename = {
    'Python': 'autonomous_agent.py',
    'TypeScript': 'autonomous_agent.ts',
    'Rust': 'autonomous_agent.rs',
    'MCP Native': 'conduit_tool.json',
  }[lang];

  return (
    <section className="section col sdk" id="sdk">
      <div className="sdk-copy" data-reveal>
        <div className="eyebrow">03 — Developer SDK</div>
        <h2>Five lines of code.<br /><em>First payment.</em></h2>
        <p>Drop the Conduit SDK into any agent runtime. Issue a wallet, attach a policy, send sats. The whole loop — wallet creation, signature, route, settlement — happens before your model finishes its next token.</p>
        <div className="lang-badges">
          {langs.map(l => (
            <button key={l} className={'lang-badge' + (l === lang ? ' active' : '')} onClick={() => setLang(l)}>{l}</button>
          ))}
        </div>
        <Magnetic strength={8}>
          <a className="btn btn-ghost" href="#"><span>View on GitHub</span> <span className="btn-arrow">↗</span></a>
        </Magnetic>
      </div>

      <div className="code" data-reveal data-rd="1">
        <div className="code-chrome">
          <div className="code-dots"><span /><span /><span /></div>
          <div className="code-fn">~ / agents / <b>{filename}</b></div>
          <button className="code-copy" onClick={copy}>{copied ? 'COPIED ✓' : 'COPY'}</button>
        </div>
        <div className="code-body">
          {lines.map((row, i) => (
            <div className="code-row" key={i}>
              <div className="ln">{String(i + 1).padStart(2, '0')}</div>
              <div className="src">
                {row.length === 0 ? '\u00A0' : row.map((tk, j) => (
                  <span key={j} className={'tk-' + tk.c}>{tk.t}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="code-result">
          <span className="ck">✓</span>
          <span className="msg">Settled <span className="sats">150 sats</span> → compute-node-7</span>
          <span className="ms">47ms</span>
        </div>
      </div>
    </section>
  );
}

window.Layer = Layer;
window.SDK = SDK;

/* ----------------------- CASES ----------------------- */
function Cases() {
  const cards = [
    { c: 'cyan',   badge: 'CYAN · 01',   tag: '/ INFRASTRUCTURE', t: 'API Micropayments',
      p: 'Charge agents per request, per token, per millisecond of GPU. No subscriptions, no minimums, no chargebacks. Streaming payments that scale to zero.',
      demo: { l: 'PER 1K TOKENS', v: '~ 12 sats · 8ms' } },
    { c: 'purple', badge: 'PURPLE · 02', tag: '/ COMPUTE',        t: 'Autonomous Compute',
      p: 'Agents rent CPU, GPU, and storage by the second from a global marketplace. Pay only for cycles consumed; release the lease the moment work finishes.',
      demo: { l: 'A100 / SECOND', v: '340 sats · streaming' } },
    { c: 'gold',   badge: 'GOLD · 03',   tag: '/ COMMERCE',       t: 'Agent-to-Agent Commerce',
      p: 'Agents transact with other agents — buying data, hiring services, settling deals — directly, without intermediaries. A native economy for software.',
      demo: { l: 'MEAN TX',       v: '~ 2,400 sats · 41ms' } },
    { c: 'amber',  badge: 'AMBER · 04',  tag: '/ TREASURY',       t: 'Autonomous Treasury',
      p: 'Each agent holds, allocates, and rebalances its own balance sheet within rules you define. Programmable cashflow without a human in the loop.',
      demo: { l: 'MANAGED',       v: '$48.2M · 12,840 wallets' } },
  ];
  return (
    <section className="section col" id="cases">
      <div className="cases-head">
        <div className="eyebrow" data-reveal>05 — Use Cases</div>
        <h2 data-reveal data-rd="1">Let machines <em>pay</em> machines.</h2>
        <p data-reveal data-rd="2">When agents can hold value and settle it without permission, entirely new economies appear — priced in fractions of a cent, cleared in milliseconds.</p>
      </div>
      <div className="cases-grid">
        {cards.map((c, i) => (
          <article className="case-card" data-c={c.c} key={c.t} data-reveal data-rd={(i % 2) + 1}>
            <div className="head">
              <span className="badge">{c.badge}</span>
              <span className="num">{c.tag}</span>
            </div>
            <h3>{c.t}</h3>
            <p>{c.p}</p>
            <div className="demo">
              <span className="lbl">{c.demo.l}</span>
              <span className="v">{c.demo.v}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

/* ----------------------- SECURITY ----------------------- */
function Security() {
  const cells = [
    { t: 'Spending Limits',
      p: 'Hard caps per minute, hour, day. Velocity rules halt runaway loops before they drain a balance.',
      ico: (<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="3" y="6" width="18" height="12" rx="2"/><path d="M3 10h18"/><path d="M7 14h4"/></svg>) },
    { t: 'Allowlists',
      p: 'Constrain counterparties to known wallets, nodes, or namespaces. Reject any destination outside the policy.',
      ico: (<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="9"/><path d="M8 12l3 3 5-6"/></svg>) },
    { t: 'Audit Logs',
      p: 'Every signature, route, and rule decision is signed and exported. Reconstruct any agent history to the satoshi.',
      ico: (<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M4 6h16M4 12h16M4 18h10"/></svg>) },
    { t: 'Scoped Keys',
      p: 'Issue narrow keys per task or session. Capability-style scopes mean a compromise never reaches the master wallet.',
      ico: (<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="6" y="10" width="12" height="10" rx="2"/><path d="M9 10V7a3 3 0 016 0v3"/></svg>) },
    { t: 'Human Override',
      p: 'One call, one keystroke — freeze any wallet or revoke any policy. The human is always at the top of the call stack.',
      ico: (<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="12" cy="12" r="9"/><path d="M12 7v5M12 16h.01"/></svg>) },
    { t: 'Revocable Access',
      p: 'Rotate, expire, or revoke any credential at any time. Permissions are leases, never permanent grants.',
      ico: (<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M3 12a9 9 0 0115-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 01-15 6.7L3 16"/><path d="M3 21v-5h5"/></svg>) },
  ];
  return (
    <section className="section col security" id="security">
      <div className="security-copy" data-reveal>
        <div className="eyebrow">06 — Controls</div>
        <h2>Give every agent a wallet,<br />a budget, and <em>rules.</em></h2>
        <p>Autonomy without limits is a liability. Conduit policy engine evaluates every outbound payment against your declared spending rules before a signature ever happens — and gives you the kill switch if something looks wrong.</p>
        <Magnetic strength={8}>
          <a className="btn btn-ghost" href="#"><span>Read the threat model</span> <span className="btn-arrow">↗</span></a>
        </Magnetic>
      </div>
      <div className="security-grid">
        {cells.map((c, i) => (
          <div className="security-cell" key={c.t} data-reveal data-rd={(i % 5) + 1}>
            <div className="ico">{c.ico}</div>
            <h4>{c.t}</h4>
            <p>{c.p}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ----------------------- VISION ----------------------- */
function Vision() {
  return (
    <section className="section vision col">
      <div className="rule" data-reveal />
      <blockquote data-reveal data-rd="1">
        Built on <span className="gold">Bitcoin.</span><br />
        Routed through <span className="gold">Lightning.</span><br />
        Controlled by <span className="gold">Conduit.</span>
      </blockquote>
      <div className="rule" data-reveal data-rd="2" />
      <div className="wordmark" data-reveal data-rd="3">C O N D U I T &nbsp; · &nbsp; E N E R G Y</div>
    </section>
  );
}

/* ----------------------- FINAL ----------------------- */
function Final() {
  return (
    <section className="section final col" id="final">
      <div className="eyebrow" data-reveal style={{ justifyContent: 'center' }}>07 — Build with Us</div>
      <h2 data-reveal data-rd="1" style={{ marginTop: 22 }}>The machine economy needs a monetary layer.</h2>
      <p className="ser" data-reveal data-rd="2"><em>Build it on Bitcoin.</em> Route it through Conduit.</p>
      <div className="final-actions" data-reveal data-rd="3">
        <Magnetic strength={8}>
          <a className="btn btn-primary" href="#"><span>Request Early Access</span> <span className="btn-arrow">→</span></a>
        </Magnetic>
        <Magnetic strength={8}>
          <a className="btn btn-ghost" href="#"><span>Read the Docs</span></a>
        </Magnetic>
      </div>
    </section>
  );
}

/* ----------------------- FOOTER ----------------------- */
function Footer() {
  return (
    <footer className="footer">
      <div className="brand">
        <LogoMark size={26} />
        <span className="nav-wordmark">CONDUIT</span>
      </div>
      <div className="copy">
        <div>conduit.energy</div>
        <div className="dim">Bitcoin payment infrastructure for autonomous machines</div>
        <div className="dim">© 2026 Conduit Labs</div>
      </div>
      <div className="links">
        <a href="#">GitHub</a>
        <a href="#">Docs</a>
        <a href="#">Whitepaper</a>
        <a href="#">X</a>
      </div>
    </footer>
  );
}

window.Cases = Cases;
window.Security = Security;
window.Vision = Vision;
window.Final = Final;
window.Footer = Footer;
