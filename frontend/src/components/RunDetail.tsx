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
        if (mounted) { setDetail(data); setLoading(false); }
      })
      .catch((err) => {
        if (mounted) { setError(err.message || 'Failed to load details'); setLoading(false); }
      });
    return () => { mounted = false; };
  }, [runId]);

  if (loading) return <div style={{ padding: '40px', textAlign: 'center', color: '#6b7280', fontSize: '13px' }}>Loading transaction telemetry...</div>;
  if (error || !detail) return <div style={{ padding: '20px', color: '#b91c1c', backgroundColor: '#fef2f2', border: '1px solid #f87171', borderRadius: '6px' }}>{error || 'Unknown error'}</div>;

  const ev = detail.evidence_contract || {};
  
  const timelineSteps = [
    { title: 'Invoice Ingestion', desc: `Ledger ID: ${detail.ledger_id}` },
    { title: 'Extraction Matrix', desc: 'OCR & Layout Parsing Complete' },
    { title: 'QuantAgent Synthesis', desc: detail.generated_code ? 'Python AST Generated' : 'Bypassed' },
    { title: 'Sandbox Execution', desc: detail.execution_result ? 'Outputs Captured' : 'N/A' },
    { title: 'Reconciliation Engine', desc: detail.match_status },
    { title: 'Trust Profiling', desc: `Tier: ${detail.vendor_tier || 'STANDARD'}` }
  ];

  const reason = detail.exception_reason || detail.system_failure_reason;

  return (
    <div style={{ backgroundColor: '#ffffff', padding: '32px', borderTop: '1px solid #e5e7eb', boxShadow: 'inset 0 2px 4px rgba(0,0,0,0.02)' }}>
      
      <div style={{ display: 'grid', gridTemplateColumns: '3fr 2fr', gap: '48px', marginBottom: '32px' }}>
        <div>
          <h3 style={{ fontSize: '12px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '16px', borderBottom: '1px solid #e5e7eb', paddingBottom: '8px' }}>
            Pipeline Diagnostics
          </h3>
          
          <div style={{ marginBottom: '24px' }}>
            <span style={{ fontSize: '13px', fontWeight: 500, color: '#374151' }}>Detected Discrepancies</span>
            {detail.discrepancies?.length > 0 ? (
              <ul style={{ margin: '8px 0 0 0', paddingLeft: '20px', color: '#b91c1c', fontSize: '13px', fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>
                {detail.discrepancies.map((d, idx) => <li key={idx} style={{ marginBottom: '4px' }}>{d}</li>)}
              </ul>
            ) : <p style={{ margin: '8px 0 0 0', fontSize: '13px', color: '#9ca3af', fontStyle: 'italic' }}>Clean matching matrix.</p>}
          </div>

          {reason && (
            <div style={{ padding: '16px', backgroundColor: '#fffbeb', border: '1px solid #fde68a', borderRadius: '6px' }}>
              <span style={{ display: 'block', fontSize: '12px', fontWeight: 600, color: '#92400e', marginBottom: '4px', textTransform: 'uppercase' }}>System Halt Reason</span>
              <span style={{ fontSize: '13px', color: '#b45309', fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{reason}</span>
            </div>
          )}
        </div>
        
        <div>
          <h3 style={{ fontSize: '12px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '16px', borderBottom: '1px solid #e5e7eb', paddingBottom: '8px' }}>
            Audit Lineage
          </h3>
          <div style={{ position: 'relative', paddingLeft: '20px', borderLeft: '2px solid #e5e7eb' }}>
            {timelineSteps.map((step, i) => (
              <div key={i} style={{ marginBottom: '16px', position: 'relative' }}>
                <div style={{ position: 'absolute', left: '-25px', top: '4px', width: '8px', height: '8px', borderRadius: '50%', background: '#d1d5db', border: '2px solid #fff' }} />
                <div style={{ fontWeight: 500, fontSize: '13px', color: '#111827' }}>{step.title}</div>
                <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '2px' }}>{step.desc}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '24px' }}>
        <div style={{ border: '1px solid #e5e7eb', borderRadius: '6px', overflow: 'hidden' }}>
          <div style={{ backgroundColor: '#f9fafb', padding: '8px 16px', borderBottom: '1px solid #e5e7eb', fontSize: '12px', fontWeight: 500, color: '#4b5563', display: 'flex', justifyContent: 'space-between' }}>
            <span>quant_agent.py</span>
            <span style={{ color: '#9ca3af' }}>Python AST</span>
          </div>
          <pre style={{ margin: 0, padding: '16px', overflowX: 'auto', backgroundColor: '#ffffff', color: '#1f2937', fontSize: '12px', fontFamily: 'ui-monospace, SFMono-Regular, monospace', maxHeight: '300px' }}>
            {detail.generated_code || '# Execution bypassed for this transaction.'}
          </pre>
        </div>

        <div style={{ border: '1px solid #e5e7eb', borderRadius: '6px', overflow: 'hidden' }}>
          <div style={{ backgroundColor: '#f9fafb', padding: '8px 16px', borderBottom: '1px solid #e5e7eb', fontSize: '12px', fontWeight: 500, color: '#4b5563', display: 'flex', justifyContent: 'space-between' }}>
            <span>evidence_contract.json</span>
            <span style={{ color: '#9ca3af' }}>JSON Payload</span>
          </div>
          <pre style={{ margin: 0, padding: '16px', overflowX: 'auto', backgroundColor: '#ffffff', color: '#1f2937', fontSize: '12px', fontFamily: 'ui-monospace, SFMono-Regular, monospace', maxHeight: '300px' }}>
            {Object.keys(ev).length > 0 ? JSON.stringify(ev, null, 2) : '{\n  "status": "No contract generated"\n}'}
          </pre>
        </div>
      </div>
    </div>
  );
};
