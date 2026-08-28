import React, { useEffect, useState } from 'react';

interface MetricSet {
  precision: number;
  recall: number;
  f1: number;
  support: number;
}

interface EvaluationStats {
  batch_id: string;
  timestamp: string;
  total_processed: number;
  correct_count: number;
  accuracy: number;
  total_batch_time_seconds: number;
  avg_seconds_per_record: number;
  discrepancy_matrix: Record<string, MetricSet>;
  macro_f1: number;
  exceptions: Array<{
    ledger_id: string;
    expected_status: string;
    actual_status: string;
    reason: string;
    confidence: number;
  }>;
}

export const EvaluationPanel: React.FC = () => {
  const [stats, setStats] = useState<EvaluationStats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    const fetchStats = async () => {
      try {
        const res = await fetch('/api/evaluation/baseline');
        if (!res.ok) {
          if (res.status === 404) {
            throw new Error('No baseline evaluation found. Run `uv run python scripts/evaluate.py` first.');
          }
          throw new Error('Failed to fetch evaluation stats.');
        }
        const data = await res.json();
        if (mounted) {
          setStats(data);
          setError(null);
        }
      } catch (err: any) {
        if (mounted) {
          setError(err.message);
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    };
    fetchStats();
    return () => { mounted = false; };
  }, []);

  if (loading) return <main className="dashboard-main"><div className="loading-state">Loading evaluation data...</div></main>;
  if (error) return <main className="dashboard-main"><div className="global-error"><h2>Evaluation Not Ready</h2><p>{error}</p></div></main>;
  if (!stats) return null;

  return (
    <main className="dashboard-main">
      <div className="metrics-panel">
        <div className="metrics-header">
          <h2>Batch Evaluation & Throughput Summary</h2>
        </div>
        
        <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(5, 1fr)', marginBottom: '30px' }}>
          <div className="metric-card">
            <div className="metric-label">Batch ID</div>
            <div className="metric-value" style={{ fontSize: '1rem', marginTop: 'auto' }}>
              {stats.batch_id}
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Total Processed</div>
            <div className="metric-value">{stats.total_processed}</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Accuracy</div>
            <div className="metric-value" style={{ color: stats.accuracy >= 0.8 ? 'var(--status-match)' : 'var(--status-partial)' }}>
              {(stats.accuracy * 100).toFixed(1)}%
            </div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Total Time</div>
            <div className="metric-value">{stats.total_batch_time_seconds.toFixed(1)}s</div>
          </div>
          <div className="metric-card">
            <div className="metric-label">Avg/Record</div>
            <div className="metric-value">{stats.avg_seconds_per_record.toFixed(1)}s</div>
          </div>
        </div>

        <div className="metrics-header" style={{ marginTop: '2rem' }}>
          <h2>Per-Discrepancy Precision/Recall Matrix</h2>
        </div>
        
        {Object.keys(stats.discrepancy_matrix || {}).length === 0 ? (
          <div className="empty-text" style={{ padding: '2rem 0', textAlign: 'center' }}>No discrepancies predicted.</div>
        ) : (
          <table className="run-table" style={{ marginBottom: '30px' }}>
            <thead>
              <tr>
                <th style={{ textAlign: 'left' }}>Discrepancy Type</th>
                <th style={{ textAlign: 'right' }}>Precision</th>
                <th style={{ textAlign: 'right' }}>Recall</th>
                <th style={{ textAlign: 'right' }}>F1 Score</th>
                <th style={{ textAlign: 'right' }}>Support</th>
              </tr>
            </thead>
            <tbody>
              {Object.entries(stats.discrepancy_matrix)
                .sort((a, b) => b[1].support - a[1].support)
                .map(([type, metrics]) => (
                <tr key={type} className="run-row">
                  <td className="cell-status" style={{ textAlign: 'left' }}>
                    <span className="status-marker badge-mismatch">{type}</span>
                  </td>
                  <td style={{ textAlign: 'right' }}>{(metrics.precision * 100).toFixed(1)}%</td>
                  <td style={{ textAlign: 'right' }}>{(metrics.recall * 100).toFixed(1)}%</td>
                  <td style={{ textAlign: 'right' }}>{metrics.f1.toFixed(3)}</td>
                  <td style={{ textAlign: 'right', fontWeight: 'bold' }}>{metrics.support}</td>
                </tr>
              ))}
              <tr className="run-row" style={{ backgroundColor: 'rgba(0,0,0,0.02)' }}>
                <td style={{ fontWeight: 'bold', textAlign: 'left' }}>MACRO AVERAGE</td>
                <td colSpan={2}></td>
                <td style={{ textAlign: 'right', fontWeight: 'bold' }}>{stats.macro_f1.toFixed(3)}</td>
                <td></td>
              </tr>
            </tbody>
          </table>
        )}

        <div className="metrics-header" style={{ marginTop: '2rem' }}>
          <h2>Honest Exceptions View</h2>
        </div>
        
        {stats.exceptions.length === 0 ? (
          <div className="empty-text" style={{ padding: '2rem 0', textAlign: 'center' }}>No exceptions found in this batch!</div>
        ) : (
          <table className="run-table">
            <thead>
              <tr>
                <th style={{ textAlign: 'left', width: '20%' }}>Ledger ID</th>
                <th style={{ textAlign: 'left', width: '15%' }}>Expected</th>
                <th style={{ textAlign: 'left', width: '15%' }}>Actual</th>
                <th style={{ textAlign: 'left', width: '40%' }}>Reason</th>
                <th style={{ textAlign: 'right', width: '10%' }}>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {stats.exceptions.map((exc, idx) => (
                <tr key={idx} className="run-row">
                  <td style={{ fontFamily: 'monospace', fontSize: '0.8rem' }}>{exc.ledger_id.split('-')[0]}...</td>
                  <td>
                    <span className={`status-marker ${exc.expected_status === 'MATCH' ? 'badge-match' : 'badge-mismatch'}`}>
                      {exc.expected_status}
                    </span>
                  </td>
                  <td>
                    <span className={`status-marker ${exc.actual_status === 'MATCH' ? 'badge-match' : 'badge-mismatch'}`}>
                      {exc.actual_status}
                    </span>
                  </td>
                  <td style={{ fontSize: '0.85rem', color: '#555' }}>{exc.reason}</td>
                  <td style={{ textAlign: 'right' }}>{(exc.confidence * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </main>
  );
};

