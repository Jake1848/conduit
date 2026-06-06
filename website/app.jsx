/* ============================================================
   CONDUIT — app.jsx
   Root mount + smooth scroll
   ============================================================ */

function ScrollProgress() {
  const p = useScrollProgress();
  return <div className="scroll-progress" style={{ width: p + '%' }} />;
}

function App() {
  useReveal();

  // smooth in-page scroll for hash links
  React.useEffect(() => {
    function onClick(e) {
      const a = e.target.closest('a[href^="#"]');
      if (!a) return;
      const id = a.getAttribute('href').slice(1);
      if (!id) return;
      const t = document.getElementById(id);
      if (!t) return;
      e.preventDefault();
      const y = t.getBoundingClientRect().top + window.scrollY - 60;
      window.scrollTo({ top: y, behavior: 'smooth' });
    }
    document.addEventListener('click', onClick);
    return () => document.removeEventListener('click', onClick);
  }, []);

  return (
    <>
      <div className="ambient" aria-hidden="true" />
      <Starfield />
      <Cursor />
      <ScrollProgress />
      <Nav />
      <main>
        <Hero />
        <StatStrip />
        <Problem />
        <Layer />
        <SDK />
        <ConsoleSection />
        <Cases />
        <Pricing />
        <Security />
        <Vision />
        <Final />
      </main>
      <Footer />
    </>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
