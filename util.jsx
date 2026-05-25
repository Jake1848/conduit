/* ============================================================
   CONDUIT — util.jsx
   Hooks + small primitive components
   ============================================================ */

const { useState, useEffect, useRef, useMemo, useCallback } = React;

// ---------- reveal on scroll ----------
function useReveal() {
  useEffect(() => {
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        if (e.isIntersecting) { e.target.classList.add('in'); io.unobserve(e.target); }
      }
    }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });
    document.querySelectorAll('[data-reveal]:not(.in)').forEach(el => io.observe(el));
    return () => io.disconnect();
  });
}

// ---------- nav scrolled state ----------
function useScrolled(threshold) {
  const [s, setS] = useState(false);
  useEffect(() => {
    function on() { setS(window.scrollY > (threshold || 24)); }
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, [threshold]);
  return s;
}

// ---------- scroll progress ----------
function useScrollProgress() {
  const [p, setP] = useState(0);
  useEffect(() => {
    function on() {
      const h = document.documentElement.scrollHeight - window.innerHeight;
      setP(h > 0 ? (window.scrollY / h) * 100 : 0);
    }
    on();
    window.addEventListener('scroll', on, { passive: true });
    return () => window.removeEventListener('scroll', on);
  }, []);
  return p;
}

// ---------- intersection visibility hook ----------
function useInView(opts) {
  const ref = useRef(null);
  const [v, setV] = useState(false);
  useEffect(() => {
    if (!ref.current) return;
    const io = new IntersectionObserver(([e]) => {
      if (e.isIntersecting) { setV(true); io.disconnect(); }
    }, opts || { threshold: 0.3 });
    io.observe(ref.current);
    return () => io.disconnect();
  }, []);
  return [ref, v];
}

// ---------- count up ----------
function useCountUp(target, duration) {
  const [ref, inView] = useInView({ threshold: 0.4 });
  const [v, setV] = useState(0);
  useEffect(() => {
    if (!inView) return;
    let raf, t0;
    function tick(t) {
      if (!t0) t0 = t;
      const p = Math.min(1, (t - t0) / (duration || 1600));
      const eased = 1 - Math.pow(1 - p, 3);
      setV(target * eased);
      if (p < 1) raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [inView, target, duration]);
  return [ref, v];
}

// ---------- format number ----------
function fmt(n, opts) {
  opts = opts || {};
  const { compact, decimals = 0, prefix = '', suffix = '' } = opts;
  if (compact) {
    if (n >= 1e9) return prefix + (n / 1e9).toFixed(decimals || 2) + 'B' + suffix;
    if (n >= 1e6) return prefix + (n / 1e6).toFixed(decimals || 1) + 'M' + suffix;
    if (n >= 1e3) return prefix + (n / 1e3).toFixed(decimals || 1) + 'K' + suffix;
    return prefix + Math.round(n) + suffix;
  }
  return prefix + n.toLocaleString(undefined, { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) + suffix;
}

// ---------- seeded series (deterministic) ----------
function makeSeries(n, seed, opts) {
  opts = opts || {};
  const { trend = 0, vol = 0.2, base = 0.5 } = opts;
  let r = seed;
  const out = [];
  let y = base;
  for (let i = 0; i < n; i++) {
    r = (r * 9301 + 49297) % 233280;
    const rand = r / 233280;
    y += (rand - 0.5) * vol;
    y += trend / n;
    y = Math.max(0.05, Math.min(0.95, y));
    out.push(y);
  }
  return out;
}

// ---------- Sparkline ----------
function Sparkline({ data, width = 200, height = 36, smooth = true }) {
  const path = useMemo(() => {
    if (!data || !data.length) return { line: '', area: '' };
    const stepX = width / (data.length - 1);
    const min = Math.min(...data), max = Math.max(...data);
    const range = max - min || 1;
    const pts = data.map((v, i) => [i * stepX, height - ((v - min) / range) * (height - 4) - 2]);
    let d = '';
    if (smooth) {
      d = pts.reduce((acc, [px, py], i) => {
        if (i === 0) return `M ${px} ${py}`;
        const [ppx, ppy] = pts[i - 1];
        const cx1 = ppx + (px - ppx) * 0.5;
        const cx2 = ppx + (px - ppx) * 0.5;
        return acc + ` C ${cx1} ${ppy} ${cx2} ${py} ${px} ${py}`;
      }, '');
    } else {
      d = pts.map(([x, y], i) => (i === 0 ? `M ${x} ${y}` : `L ${x} ${y}`)).join(' ');
    }
    const area = d + ` L ${width} ${height} L 0 ${height} Z`;
    return { line: d, area };
  }, [data, width, height, smooth]);
  return (
    <svg viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none" style={{ display: 'block', width: '100%', height: '100%' }}>
      <path d={path.area} fill="url(#chartFill)" />
      <path d={path.line} fill="none" stroke="url(#chartLine)" strokeWidth="1.5" strokeLinecap="round"
        style={{ filter: 'drop-shadow(0 0 3px rgba(212,160,23,0.5))' }} />
    </svg>
  );
}

// ---------- CountUp text ----------
function CountUp({ to, decimals = 0, compact = false, prefix = '', suffix = '', duration = 1600 }) {
  const [ref, v] = useCountUp(to, duration);
  return <span ref={ref}>{fmt(v, { decimals, compact, prefix, suffix })}</span>;
}

// ---------- Cursor follower + dot ----------
function Cursor() {
  const ringRef = useRef(null);
  const dotRef = useRef(null);
  useEffect(() => {
    if (window.matchMedia('(hover: none), (pointer: coarse)').matches) return;
    let rx = window.innerWidth / 2, ry = window.innerHeight / 2;
    let mx = rx, my = ry;
    let raf;
    function move(e) {
      mx = e.clientX; my = e.clientY;
      if (dotRef.current) dotRef.current.style.transform = `translate3d(${mx}px, ${my}px, 0) translate(-50%, -50%)`;
    }
    function loop() {
      rx += (mx - rx) * 0.18;
      ry += (my - ry) * 0.18;
      if (ringRef.current) ringRef.current.style.transform = `translate3d(${rx}px, ${ry}px, 0) translate(-50%, -50%)`;
      raf = requestAnimationFrame(loop);
    }
    function over(e) {
      const t = e.target.closest('a, button, .case-card, .feature-card, .problem-cell, .kpi, .panel, [data-cursor=hover]');
      if (ringRef.current) ringRef.current.classList.toggle('hover', !!t);
    }
    window.addEventListener('mousemove', move);
    window.addEventListener('mouseover', over);
    loop();
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener('mousemove', move);
      window.removeEventListener('mouseover', over);
    };
  }, []);
  return (
    <>
      <div ref={ringRef} className="cursor" aria-hidden="true" />
      <div ref={dotRef} className="cursor-dot" aria-hidden="true" />
    </>
  );
}

// ---------- Starfield canvas ----------
function Starfield() {
  const ref = useRef(null);
  useEffect(() => {
    const c = ref.current; if (!c) return;
    const ctx = c.getContext('2d');
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    let W, H, stars, raf;
    function resize() {
      W = window.innerWidth; H = window.innerHeight;
      c.width = W * dpr; c.height = H * dpr;
      c.style.width = W + 'px'; c.style.height = H + 'px';
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      const N = Math.min(110, Math.floor(W * H / 22000));
      stars = Array.from({ length: N }, () => ({
        x: Math.random() * W, y: Math.random() * H,
        z: Math.random() * 0.8 + 0.2,
        r: Math.random() * 1.1 + 0.3,
        tw: Math.random() * Math.PI * 2,
        spd: 0.008 + Math.random() * 0.014,
        vx: (Math.random() - 0.5) * 0.04,
        vy: (Math.random() - 0.5) * 0.04,
      }));
    }
    resize();
    window.addEventListener('resize', resize);
    function draw() {
      ctx.clearRect(0, 0, W, H);
      for (const s of stars) {
        s.tw += s.spd;
        s.x += s.vx; s.y += s.vy;
        if (s.x < 0 || s.x > W) s.vx *= -1;
        if (s.y < 0 || s.y > H) s.vy *= -1;
        const a = (Math.sin(s.tw) + 1) * 0.5 * s.z;
        ctx.fillStyle = `rgba(255,224,138,${0.06 + a * 0.4})`;
        ctx.beginPath();
        ctx.arc(s.x, s.y, s.r * s.z, 0, Math.PI * 2);
        ctx.fill();
      }
      // sparse links
      for (let i = 0; i < stars.length; i++) {
        for (let j = i + 1; j < stars.length; j++) {
          const a = stars[i], b = stars[j];
          const dx = a.x - b.x, dy = a.y - b.y;
          const d2 = dx * dx + dy * dy;
          if (d2 < 16000) {
            const o = (1 - d2 / 16000) * 0.10;
            ctx.strokeStyle = `rgba(212,160,23,${o})`;
            ctx.lineWidth = 0.5;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        }
      }
      raf = requestAnimationFrame(draw);
    }
    draw();
    return () => { cancelAnimationFrame(raf); window.removeEventListener('resize', resize); };
  }, []);
  return <canvas ref={ref} className="starfield" aria-hidden="true" />;
}

// ---------- Magnetic wrapper ----------
function Magnetic({ children, strength = 12 }) {
  const ref = useRef(null);
  function move(e) {
    const el = ref.current; if (!el) return;
    const r = el.getBoundingClientRect();
    const x = (e.clientX - (r.left + r.width / 2)) / r.width;
    const y = (e.clientY - (r.top + r.height / 2)) / r.height;
    el.style.transform = `translate3d(${x * strength}px, ${y * strength}px, 0)`;
  }
  function leave() {
    if (ref.current) ref.current.style.transform = 'translate3d(0,0,0)';
  }
  return (
    <span ref={ref} onMouseMove={move} onMouseLeave={leave}
      style={{ display: 'inline-flex', transition: 'transform 320ms cubic-bezier(.2,.7,.2,1)' }}>
      {children}
    </span>
  );
}

Object.assign(window, {
  useReveal, useScrolled, useScrollProgress, useInView, useCountUp,
  fmt, makeSeries, Sparkline, CountUp, Cursor, Starfield, Magnetic
});
