import { useEffect, useState } from 'react';
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom';
import type { RunSummary } from './api';
import { fetchRuns } from './api';
import { RunTable } from './components/RunTable';
import { MetricsPanel } from './components/MetricsPanel';
import { EvaluationPanel } from './components/EvaluationPanel';
import './App.css';

function Dashboard() {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;

    const loadRuns = async () => {
      try {
        const data = await fetchRuns();
        if (mounted) {
          setRuns(data);
          setError(null);
        }
      } catch (err: any) {
        if (mounted) {
          setError(err.message || 'Backend not connected');
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };

    // Initial load
    loadRuns();

    // Poll every 5 seconds
    const intervalId = setInterval(loadRuns, 5000);

    return () => {
      mounted = false;
      clearInterval(intervalId);
    };
  }, []);

  return (
    <>
      {error ? (
        <div className="global-error">
          <h2>Connection Error</h2>
          <p>{error}</p>
        </div>
      ) : (
        <>
          <MetricsPanel />

          <main className="dashboard-main">
            {loading && runs.length === 0 ? (
              <div className="loading-state">Loading runs...</div>
            ) : (
              <RunTable runs={runs} />
            )}
          </main>
        </>
      )}
    </>
  );
}

function Header() {
  const location = useLocation();
  return (
    <header className="dashboard-header">
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1>KhataAgent Reconciliation Queue</h1>
          <p className="subtitle">Real-time audit log monitor</p>
        </div>
        <nav className="header-nav">
          <Link to="/" className={`nav-link ${location.pathname === '/' ? 'active' : ''}`}>Dashboard</Link>
          <Link to="/evaluation" className={`nav-link ${location.pathname === '/evaluation' ? 'active' : ''}`}>Evaluation Batch</Link>
        </nav>
      </div>
    </header>
  );
}

function App() {
  return (
    <BrowserRouter>
      <div className="dashboard-container">
        <Header />
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/evaluation" element={<EvaluationPanel />} />
        </Routes>
      </div>
    </BrowserRouter>
  );
}

export default App;
