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
            throw new Error('Awaiting baseline evaluation. Please trigger the batch processor to generate metrics.');
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

  if (loading) return <div style={{ padding: '48px', textAlign: 'center', color: '#6b7280', fontSize: '14px' }}>Loading evaluation metrics...</div>;
  if (error) return (
    <div style={{ padding: '32px', textAlign: 'center', backgroundColor: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
      <p style={{ color: '#6b7280', fontSize: '14px' }}>{error}</p>
    </div>
  );
  if (!stats) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '16px' }}>
        {[
          { label: 'Batch ID', value: stats.batch_id.split('-')[0] },
          { label: 'Processed', value: stats.total_processed },
          { label: 'Accuracy', value: `${(stats.accuracy * 100).toFixed(1)}%`, color: stats.accuracy >= 0.8 ? '#059669' : '#d97706' },
          { label: 'Total Time', value: `${stats.total_batch_time_seconds.toFixed(1)}s` },
          { label: 'Avg/Record', value: `${stats.avg_seconds_per_record.toFixed(1)}s` }
        ].map((m, i) => (
          <div key={i} style={{ padding: '16px', backgroundColor: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 1px 2px rgba(0,0,0,0.02)' }}>
            <div style={{ fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' }}>{m.label}</div>
            <div style={{ fontSize: '18px', fontWeight: 500, color: m.color || '#111827' }}>{m.value}</div>
          </div>
        ))}
      </div>

      <div style={{ border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#ffffff', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
        <div style={{ padding: '16px', backgroundColor: '#f9fafb', borderBottom: '1px solid #e5e7eb', fontSize: '12px', fontWeight: 600, color: '#374151', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Per-Discrepancy Precision/Recall Matrix
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead style={{ backgroundColor: '#ffffff', borderBottom: '1px solid #e5e7eb' }}>
            <tr>
              <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280' }}>Type</th>
              <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280', textAlign: 'right' }}>Precision</th>
              <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280', textAlign: 'right' }}>Recall</th>
              <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280', textAlign: 'right' }}>F1 Score</th>
              <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280', textAlign: 'right' }}>Support</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stats.discrepancy_matrix)
              .sort((a, b) => b[1].support - a[1].support)
              .map(([type, metrics], idx) => (
              <tr key={type} style={{ borderBottom: '1px solid #e5e7eb', backgroundColor: idx % 2 === 0 ? '#ffffff' : '#f9fafb' }}>
                <td style={{ padding: '12px 16px', fontSize: '13px', color: '#111827', fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{type}</td>
                <td style={{ padding: '12px 16px', fontSize: '13px', color: '#4b5563', textAlign: 'right' }}>{(metrics.precision * 100).toFixed(1)}%</td>
                <td style={{ padding: '12px 16px', fontSize: '13px', color: '#4b5563', textAlign: 'right' }}>{(metrics.recall * 100).toFixed(1)}%</td>
                <td style={{ padding: '12px 16px', fontSize: '13px', color: '#4b5563', textAlign: 'right' }}>{metrics.f1.toFixed(3)}</td>
                <td style={{ padding: '12px 16px', fontSize: '13px', fontWeight: 500, color: '#111827', textAlign: 'right' }}>{metrics.support}</td>
              </tr>
            ))}
            <tr style={{ backgroundColor: '#f3f4f6' }}>
              <td style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 600, color: '#374151' }}>MACRO AVERAGE</td>
              <td colSpan={2}></td>
              <td style={{ padding: '12px 16px', fontSize: '13px', fontWeight: 600, color: '#111827', textAlign: 'right' }}>{stats.macro_f1.toFixed(3)}</td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>

      <div style={{ border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#ffffff', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
        <div style={{ padding: '16px', backgroundColor: '#f9fafb', borderBottom: '1px solid #e5e7eb', fontSize: '12px', fontWeight: 600, color: '#374151', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Honest Exceptions View
        </div>
        {stats.exceptions.length === 0 ? (
          <div style={{ padding: '32px', textAlign: 'center', color: '#6b7280', fontSize: '13px' }}>No exceptions found in this batch.</div>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
            <thead style={{ backgroundColor: '#ffffff', borderBottom: '1px solid #e5e7eb' }}>
              <tr>
                <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280' }}>Ledger ID</th>
                <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280' }}>Expected</th>
                <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280' }}>Actual</th>
                <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280' }}>Reason</th>
                <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280', textAlign: 'right' }}>Confidence</th>
              </tr>
            </thead>
            <tbody>
              {stats.exceptions.map((exc, idx) => (
                <tr key={idx} style={{ borderBottom: '1px solid #e5e7eb', backgroundColor: idx % 2 === 0 ? '#ffffff' : '#f9fafb' }}>
                  <td style={{ padding: '12px 16px', fontSize: '13px', color: '#6b7280', fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{exc.ledger_id.split('-')[0]}...</td>
                  <td style={{ padding: '12px 16px', fontSize: '12px', color: '#111827', fontWeight: 500 }}>{exc.expected_status}</td>
                  <td style={{ padding: '12px 16px', fontSize: '12px', color: '#111827', fontWeight: 500 }}>{exc.actual_status}</td>
                  <td style={{ padding: '12px 16px', fontSize: '13px', color: '#4b5563' }}>{exc.reason}</td>
                  <td style={{ padding: '12px 16px', fontSize: '13px', color: '#111827', textAlign: 'right' }}>{(exc.confidence * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
};
