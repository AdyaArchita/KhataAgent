import React, { useEffect, useState } from 'react';

interface TierDistribution {
  STANDARD: number;
  ENHANCED: number;
  MANDATORY_AUDIT: number;
}

interface CalibrationBucket {
  total: number;
  matches: number;
}

interface Calibration {
  "0.0-0.3": CalibrationBucket;
  "0.3-0.6": CalibrationBucket;
  "0.6-0.9": CalibrationBucket;
  "0.9-1.0": CalibrationBucket;
}

interface Metrics {
  match_rate: number;
  partial_rate: number;
  exception_rate: number;
  open_exception_rate: number;
  human_resolved_rate: number;
  self_consistency_rate: number;
  avg_confidence: number;
  calibration: Calibration;
  p50_latency_ms: number;
  p95_latency_ms: number;
  vendor_tier_distribution: TierDistribution;
  records_processed: number;
  window: string;
}

export const MetricsPanel: React.FC = () => {
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [connected, setConnected] = useState<boolean>(false);

  useEffect(() => {
    let timeoutId: NodeJS.Timeout;
    const eventSource = new EventSource('/api/metrics/stream');

    eventSource.onmessage = (event) => {
      try {
        const data: Metrics = JSON.parse(event.data);
        setMetrics(data);
        setConnected(true);
        clearTimeout(timeoutId);
        timeoutId = setTimeout(() => setConnected(false), 5000); // Degrade if no events for 5s
      } catch (err) {
        console.error("Failed to parse metrics:", err);
      }
    };

    eventSource.onerror = () => {
      setConnected(false);
    };

    return () => {
      clearTimeout(timeoutId);
      eventSource.close();
    };
  }, []);

  if (!metrics) {
    return <div style={{ padding: '48px', textAlign: 'center', color: '#6b7280', fontSize: '14px' }}>Waiting for metrics stream...</div>;
  }

  const { STANDARD, ENHANCED, MANDATORY_AUDIT } = metrics.vendor_tier_distribution;
  const totalTiers = STANDARD + ENHANCED + MANDATORY_AUDIT || 1;

  return (
    <section style={{ display: 'flex', flexDirection: 'column', gap: '24px', marginBottom: '32px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <h2 style={{ fontSize: '14px', fontWeight: 600, color: '#111827', textTransform: 'uppercase', letterSpacing: '0.05em', margin: 0 }}>
          Live Metrics Stream
          <span style={{ 
            fontSize: '9px', 
            background: '#f3f4f6', 
            color: '#4b5563', 
            padding: '2px 6px', 
            borderRadius: '4px', 
            marginLeft: '8px',
            border: '1px solid #e5e7eb',
            verticalAlign: 'middle',
            fontWeight: 600
          }}>
            SIMULATED 3-WAY MATCH
          </span>
        </h2>
        {connected ? (
          <span style={{ fontSize: '11px', fontWeight: 600, color: '#059669', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#10b981' }} />
            LIVE ({metrics.window.toUpperCase()})
          </span>
        ) : (
          <span style={{ fontSize: '11px', fontWeight: 600, color: '#d97706', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: '#f59e0b' }} />
            Connection Lost — Displaying Stale Data
          </span>
        )}
      </div>
      
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px' }}>
        {[
          { label: 'Match Rate', value: `${(metrics.match_rate * 100).toFixed(1)}%` },
          { label: 'Open Exceptions', value: `${(metrics.open_exception_rate * 100).toFixed(1)}%`, sub: `${(metrics.human_resolved_rate * 100).toFixed(0)}% resolved by human` },
          { label: 'Self-Consistency', value: `${(metrics.self_consistency_rate * 100).toFixed(1)}%` },
          { label: 'Avg Confidence', value: `${(metrics.avg_confidence * 100).toFixed(0)}%` },
          { label: 'p95 Latency', value: `${metrics.p95_latency_ms.toFixed(0)}ms` },
          { label: 'Total Records', value: metrics.records_processed }
        ].map((m, i) => (
          <div key={i} style={{ padding: '16px', backgroundColor: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 1px 2px rgba(0,0,0,0.02)' }}>
            <div style={{ fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' }}>{m.label}</div>
            <div style={{ fontSize: '18px', fontWeight: 500, color: '#111827' }}>{m.value}</div>
            {m.sub && <div style={{ fontSize: '10px', color: '#9ca3af', marginTop: '4px' }}>{m.sub}</div>}
          </div>
        ))}

        <div style={{ padding: '16px', backgroundColor: '#ffffff', border: '1px solid #e5e7eb', borderRadius: '8px', boxShadow: '0 1px 2px rgba(0,0,0,0.02)', gridColumn: 'span 2' }}>
          <div style={{ fontSize: '11px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '12px' }}>Tier Distribution</div>
          <div style={{ display: 'flex', height: '8px', borderRadius: '4px', overflow: 'hidden', backgroundColor: '#f3f4f6', marginBottom: '12px' }}>
            <div style={{ width: `${(STANDARD / totalTiers) * 100}%`, backgroundColor: '#9ca3af' }} title={`Standard: ${STANDARD}`} />
            <div style={{ width: `${(ENHANCED / totalTiers) * 100}%`, backgroundColor: '#fcd34d' }} title={`Enhanced: ${ENHANCED}`} />
            <div style={{ width: `${(MANDATORY_AUDIT / totalTiers) * 100}%`, backgroundColor: '#f87171' }} title={`Mandatory Audit: ${MANDATORY_AUDIT}`} />
          </div>
          <div style={{ display: 'flex', gap: '16px', fontSize: '11px', color: '#4b5563', fontWeight: 500 }}>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#9ca3af' }} />{STANDARD}</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#fcd34d' }} />{ENHANCED}</span>
            <span style={{ display: 'flex', alignItems: 'center', gap: '4px' }}><span style={{ width: '8px', height: '8px', borderRadius: '50%', backgroundColor: '#f87171' }} />{MANDATORY_AUDIT}</span>
          </div>
        </div>
      </div>

      <div style={{ border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#ffffff', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
        <div style={{ padding: '16px', backgroundColor: '#f9fafb', borderBottom: '1px solid #e5e7eb', fontSize: '12px', fontWeight: 600, color: '#374151', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Confidence Calibration
        </div>
        <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
          <thead style={{ backgroundColor: '#ffffff', borderBottom: '1px solid #e5e7eb' }}>
            <tr>
              <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280' }}>Bucket</th>
              <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280' }}>Total Records</th>
              <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 500, color: '#6b7280' }}>Match Rate</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(metrics.calibration || {}).map(([bucket, data]: [string, any], idx) => (
              <tr key={bucket} style={{ borderBottom: '1px solid #e5e7eb', backgroundColor: idx % 2 === 0 ? '#ffffff' : '#f9fafb' }}>
                <td style={{ padding: '12px 16px', fontSize: '13px', color: '#111827', fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{bucket}</td>
                <td style={{ padding: '12px 16px', fontSize: '13px', color: '#4b5563' }}>{data.total}</td>
                <td style={{ padding: '12px 16px', fontSize: '13px', color: '#4b5563' }}>{data.total > 0 ? ((data.matches / data.total) * 100).toFixed(1) + '%' : 'N/A'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
};
