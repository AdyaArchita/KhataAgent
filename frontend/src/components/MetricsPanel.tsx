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
    const eventSource = new EventSource('/api/metrics/stream');

    eventSource.onmessage = (event) => {
      try {
        const data: Metrics = JSON.parse(event.data);
        setMetrics(data);
        setConnected(true);
      } catch (err) {
        console.error("Failed to parse metrics:", err);
      }
    };

    eventSource.onerror = () => {
      setConnected(false);
      // EventSource handles reconnection natively.
    };

    return () => {
      eventSource.close();
    };
  }, []);

  if (!metrics) {
    return <div className="metrics-panel-loading">Waiting for metrics stream...</div>;
  }

  const { STANDARD, ENHANCED, MANDATORY_AUDIT } = metrics.vendor_tier_distribution;
  const totalTiers = STANDARD + ENHANCED + MANDATORY_AUDIT || 1;

  return (
    <section className="metrics-panel">
      <div className="metrics-header">
        <h2>
          Live Metrics Stream
          <span style={{ 
            fontSize: '0.6em', 
            background: 'var(--accent-teal)', 
            color: 'white', 
            padding: '2px 8px', 
            borderRadius: '4px', 
            marginLeft: '12px',
            verticalAlign: 'middle',
            fontWeight: 'normal'
          }}>
            SIMULATED 3-WAY MATCH
          </span>
        </h2>
        <span className={`connection-status ${connected ? 'connected' : 'disconnected'}`}>
          {connected ? `LIVE (${metrics.window.toUpperCase()})` : 'Reconnecting...'}
        </span>
      </div>
      
      <div className="metrics-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))' }}>
        <div className="metric-card">
          <div className="metric-label">Match Rate</div>
          <div className="metric-value">{(metrics.match_rate * 100).toFixed(1)}%</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Open Exceptions</div>
          <div className="metric-value">{(metrics.open_exception_rate * 100).toFixed(1)}%</div>
          <div style={{ fontSize: '10px', color: '#6b7280' }}>{(metrics.human_resolved_rate * 100).toFixed(0)}% resolved by human</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Self-Consistency</div>
          <div className="metric-value">{(metrics.self_consistency_rate * 100).toFixed(1)}%</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Avg Confidence</div>
          <div className="metric-value">{(metrics.avg_confidence * 100).toFixed(0)}%</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">p95 Latency</div>
          <div className="metric-value">{metrics.p95_latency_ms.toFixed(0)}ms</div>
        </div>
        <div className="metric-card">
          <div className="metric-label">Total Records</div>
          <div className="metric-value">{metrics.records_processed}</div>
        </div>
        
        <div className="metric-card tier-card">
          <div className="metric-label">Tier Distribution</div>
          <div className="tier-bar-container">
            <div className="tier-bar segment-standard" style={{ width: `${(STANDARD / totalTiers) * 100}%` }} title={`Standard: ${STANDARD}`} />
            <div className="tier-bar segment-enhanced" style={{ width: `${(ENHANCED / totalTiers) * 100}%` }} title={`Enhanced: ${ENHANCED}`} />
            <div className="tier-bar segment-mandatory" style={{ width: `${(MANDATORY_AUDIT / totalTiers) * 100}%` }} title={`Mandatory Audit: ${MANDATORY_AUDIT}`} />
          </div>
          <div className="tier-legend">
            <span><span className="legend-dot dot-standard"></span>{STANDARD}</span>
            <span><span className="legend-dot dot-enhanced"></span>{ENHANCED}</span>
            <span><span className="legend-dot dot-mandatory"></span>{MANDATORY_AUDIT}</span>
          </div>
        </div>
      </div>

      <div className="calibration-panel" style={{ marginTop: '20px', background: 'white', padding: '15px', borderRadius: '4px', border: '1px solid #e5e7eb' }}>
        <h3 style={{ margin: '0 0 10px 0', fontSize: '14px', color: '#374151' }}>Confidence Calibration</h3>
        <table style={{ width: '100%', fontSize: '12px', textAlign: 'left', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid #e5e7eb' }}>
              <th style={{ padding: '8px' }}>Bucket</th>
              <th style={{ padding: '8px' }}>Total Records</th>
              <th style={{ padding: '8px' }}>Match Rate</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(metrics.calibration || {}).map(([bucket, data]: [string, any]) => (
              <tr key={bucket} style={{ borderBottom: '1px solid #f3f4f6' }}>
                <td style={{ padding: '8px' }}>{bucket}</td>
                <td style={{ padding: '8px' }}>{data.total}</td>
                <td style={{ padding: '8px' }}>{data.total > 0 ? ((data.matches / data.total) * 100).toFixed(1) + '%' : 'N/A'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
};
