import React, { useEffect, useState } from 'react';
import { fetchRunDetail } from '../api';
import type { RunDetail as RunDetailType } from '../api';

interface RunDetailProps {
  runId: string;
}

export const RunDetail: React.FC<RunDetailProps> = ({ runId }) => {
  const [detail, setDetail] = useState<RunDetailType | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;
    setLoading(true);
    setError(null);

    fetchRunDetail(runId)
      .then((data) => {
        if (mounted) {
          setDetail(data);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (mounted) {
          setError(err.message || 'Failed to load details');
          setLoading(false);
        }
      });

    return () => {
      mounted = false;
    };
  }, [runId]);

  if (loading) return <div className="detail-panel detail-loading">Loading details...</div>;
  if (error || !detail) return <div className="detail-panel detail-error">{error || 'Unknown error'}</div>;

  const ev = detail.evidence_contract || {};
  
  // Build Visual Audit Path
  const timelineSteps = [
    { title: 'Invoice', desc: `Ledger ID: ${detail.ledger_id}` },
    { title: 'Extracted Numbers', desc: 'Document parsed successfully' },
    { title: 'Generated Quant Code', desc: detail.generated_code ? 'Code generated' : 'Skipped' },
    { title: 'Execution Result', desc: detail.execution_result ? JSON.stringify(detail.execution_result) : 'N/A' },
    { title: 'Tolerance Check', desc: ev.tolerance_check ? 'Passed (<= 0.01)' : 'Failed' },
    { title: 'AI Diagnosis', desc: detail.match_status },
    { title: 'Vendor Trust Tier', desc: detail.vendor_tier || 'STANDARD' }
  ];
  
  if (ev.human_clearance) {
    timelineSteps.push({ 
      title: 'Human Decision', 
      desc: `${ev.human_clearance.decision.toUpperCase()} by ${ev.human_clearance.reviewed_by}` 
    });
  }

  const reason = detail.exception_reason || detail.system_failure_reason;

  return (
    <div className="detail-panel" style={{ display: 'flex', gap: '20px' }}>
      <div style={{ flex: 1 }}>
        <div className="detail-section">
          <h3>Self-Consistency Replay</h3>
          {ev.self_consistency !== undefined ? (
            <div style={{ padding: '10px', background: ev.self_consistency ? '#f0fdf4' : '#fef2f2', border: `1px solid ${ev.self_consistency ? '#bbf7d0' : '#fecaca'}`, borderRadius: '4px' }}>
              <strong>{ev.self_consistency ? 'PASS' : 'FAIL'}</strong> 
              {ev.replay_delta != null && ` (Delta: ${ev.replay_delta})`}
            </div>
          ) : (
            <div style={{ padding: '10px', background: '#f3f4f6', borderRadius: '4px' }}>Not evaluated</div>
          )}
        </div>

        <div className="detail-section">
          <h3>Discrepancies</h3>
          {detail.discrepancies?.length > 0 ? (
            <ul className="discrepancy-list">
              {detail.discrepancies.map((d, idx) => <li key={idx}>{d}</li>)}
            </ul>
          ) : <p className="empty-text">No discrepancies recorded.</p>}
        </div>

        {reason && (
          <div className="detail-section">
            <h3>Exception Reason</h3>
            <p className="reason-text">{reason}</p>
          </div>
        )}

        <div className="detail-section">
          <h3>Generated Code</h3>
          <pre className="code-block">{detail.generated_code || 'No code'}</pre>
        </div>
      </div>
      
      <div style={{ flex: 1, borderLeft: '1px solid #ddd', paddingLeft: '20px' }}>
        <h3>Visual Audit Path</h3>
        <div style={{ position: 'relative', paddingLeft: '15px', borderLeft: '2px solid #e5e7eb' }}>
          {timelineSteps.map((step, i) => (
            <div key={i} style={{ marginBottom: '15px', position: 'relative' }}>
              <div style={{ position: 'absolute', left: '-21px', top: '4px', width: '10px', height: '10px', borderRadius: '50%', background: '#6366f1', border: '2px solid white' }} />
              <div style={{ fontWeight: 'bold', fontSize: '13px', color: '#374151' }}>{step.title}</div>
              <div style={{ fontSize: '12px', color: '#6b7280', overflowWrap: 'break-word', whiteSpace: 'pre-wrap' }}>{step.desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
