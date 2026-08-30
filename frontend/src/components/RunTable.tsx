import React, { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import type { RunSummary, MatchStatus } from '../api';
import { RunDetail } from './RunDetail';
import { submitHitlDecision } from '../api';

interface RunTableProps {
  runs: RunSummary[];
}

export const RunTable: React.FC<RunTableProps> = ({ runs }) => {
  const [selectedRunId, setSelectedRunId] = React.useState<string | null>(null);

  return (
    <div style={{ border: '1px solid #e5e7eb', borderRadius: '8px', backgroundColor: '#ffffff', overflow: 'hidden', boxShadow: '0 1px 3px rgba(0,0,0,0.05)' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', textAlign: 'left' }}>
        <thead style={{ backgroundColor: '#f9fafb', borderBottom: '1px solid #e5e7eb' }}>
          <tr>
            <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Date</th>
            <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Vendor</th>
            <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Invoice #</th>
            <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Status</th>
            <th style={{ padding: '12px 16px', fontSize: '12px', fontWeight: 600, color: '#6b7280', textTransform: 'uppercase', letterSpacing: '0.05em', textAlign: 'right' }}>Confidence</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((run, idx) => (
            <RowErrorBoundary key={run.run_id || idx}>
              <RunRow 
                run={run} 
                isSelected={selectedRunId === run.run_id}
                onSelect={() => setSelectedRunId(prev => prev === run.run_id ? null : run.run_id)} 
              />
              {selectedRunId === run.run_id && (
                <tr>
                  <td colSpan={5} style={{ padding: 0 }}>
                    <RunDetail runId={run.run_id} />
                    <HitlActionRow run={run} />
                  </td>
                </tr>
              )}
            </RowErrorBoundary>
          ))}
        </tbody>
      </table>
      {runs.length === 0 && (
        <div style={{ padding: '48px', textAlign: 'center', color: '#6b7280', fontSize: '14px' }}>No transactions found in this window.</div>
      )}
    </div>
  );
};

interface RunRowProps {
  run: RunSummary;
  isSelected: boolean;
  onSelect: () => void;
}

const RunRow: React.FC<RunRowProps> = ({ run, isSelected, onSelect }) => {
  if (!run || typeof run.run_id !== 'string') throw new Error('Malformed run record');
  const dateStr = run.created_at ? new Date(run.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }) : '—';
  
  return (
    <tr 
      onClick={onSelect}
      style={{ 
        cursor: 'pointer', 
        borderBottom: '1px solid #e5e7eb', 
        backgroundColor: isSelected ? '#f8fafc' : '#ffffff',
        transition: 'background-color 0.15s ease'
      }}
    >
      <td style={{ padding: '14px 16px', fontSize: '13px', color: '#4b5563', fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{dateStr}</td>
      <td style={{ padding: '14px 16px', fontSize: '13px', fontWeight: 500, color: '#111827' }}>
        {run.vendor_name || '—'}
        <TrustBadge tier={run.vendor_tier} />
      </td>
      <td style={{ padding: '14px 16px', fontSize: '13px', color: '#4b5563', fontFamily: 'ui-monospace, SFMono-Regular, monospace' }}>{run.invoice_number || '—'}</td>
      <td style={{ padding: '14px 16px' }}>
        <StatusBadge status={run.match_status} />
      </td>
      <td style={{ padding: '14px 16px', fontSize: '13px', fontWeight: 600, color: '#111827', textAlign: 'right' }}>
        {run.confidence != null ? `${(run.confidence * 100).toFixed(0)}%` : '—'}
      </td>
    </tr>
  );
};

const StatusBadge: React.FC<{ status: MatchStatus }> = ({ status }) => {
  let bg = '#f3f4f6', color = '#374151', dot = '#9ca3af';
  
  if (status === 'MATCH') { bg = '#ecfdf5'; color = '#065f46'; dot = '#10b981'; }
  else if (status === 'PARTIAL_MATCH') { bg = '#fffbeb'; color = '#92400e'; dot = '#f59e0b'; }
  else if (status === 'MISMATCH') { bg = '#fef2f2'; color = '#991b1b'; dot = '#ef4444'; }
  else if (status === 'SYSTEM_FAILURE') { bg = '#f3f4f6'; color = '#1f2937'; dot = '#4b5563'; }
  
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', padding: '2px 8px', borderRadius: '9999px', backgroundColor: bg, color: color, fontSize: '11px', fontWeight: 600, letterSpacing: '0.02em' }}>
      <span style={{ width: '6px', height: '6px', borderRadius: '50%', backgroundColor: dot, marginRight: '6px' }} />
      {status ? status.replace('_', ' ') : 'UNKNOWN'}
    </span>
  );
};

const TrustBadge: React.FC<{ tier?: string }> = ({ tier }) => {
  if (!tier || tier === 'STANDARD') return null;
  
  let bg = '#f3f4f6', color = '#4b5563', label = tier;
  if (tier === 'ENHANCED') { bg = '#fef9c3'; color = '#854d0e'; label = 'ENHANCED'; }
  else if (tier === 'MANDATORY_AUDIT') { bg = '#fee2e2'; color = '#991b1b'; label = 'HIGH RISK'; }

  return (
    <span style={{ marginLeft: '8px', padding: '2px 6px', borderRadius: '4px', backgroundColor: bg, color: color, fontSize: '10px', fontWeight: 600, letterSpacing: '0.02em', verticalAlign: 'middle' }}>
      {label}
    </span>
  );
};

class RowErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  constructor(props: { children: ReactNode }) { super(props); this.state = { hasError: false }; }
  static getDerivedStateFromError() { return { hasError: true }; }
  componentDidCatch(error: Error, errorInfo: ErrorInfo) { console.error("Row error:", error, errorInfo); }
  render() {
    if (this.state.hasError) return (<tr><td colSpan={5} style={{ padding: '16px', color: '#b91c1c', fontSize: '13px' }}>Record rendering failed.</td></tr>);
    return this.props.children;
  }
}

const HitlActionRow: React.FC<{ run: RunSummary }> = ({ run }) => {
  const [submitting, setSubmitting]       = React.useState(false);
  const [done, setDone]                   = React.useState(false);
  const [reason, setReason]               = React.useState('');
  const [activeDecision, setActiveDecision] =
    React.useState<'approve' | 'reject' | 'override' | null>(null);

  // Lazy-load the RunDetail to surface discrepancy context for the reviewer.
  const [detail, setDetail] = React.useState<any | null>(null);
  React.useEffect(() => {
    if (run.clearance_state !== 'PENDING_HUMAN_AUDIT' || done) return;
    import('../api').then(({ fetchRunDetail }) =>
      fetchRunDetail(run.run_id).then(setDetail).catch(() => {/* non-fatal */})
    );
  }, [run.run_id, run.clearance_state, done]);

  if (run.clearance_state !== 'PENDING_HUMAN_AUDIT' && !done) return null;

  // ── Confirmation success state ─────────────────────────────────────
  if (done) {
    return (
      <div style={{
        padding: '20px 28px',
        backgroundColor: '#f0fdf4',
        borderTop: '1px solid #e5e7eb',
        borderLeft: '3px solid #10b981',
        fontSize: '13px',
        color: '#065f46',
        fontWeight: 500,
        display: 'flex',
        alignItems: 'center',
        gap: '10px',
      }}>
        <span style={{ fontSize: '16px' }}>✓</span>
        Clearance decision permanently recorded to audit ledger.
      </div>
    );
  }

  // ── API call (no changes to logic) ────────────────────────────────
  const handleSubmit = async () => {
    if (!activeDecision || reason.length < 5) return;
    setSubmitting(true);
    try {
      await submitHitlDecision(run.run_id, activeDecision, reason);
      setDone(true);
    } catch (e: any) {
      alert('Error submitting decision: ' + e.message);
      setSubmitting(false);
    }
  };

  // ── Risk tier → left border color ─────────────────────────────────
  // MISMATCH = red, PARTIAL_MATCH = amber, SYSTEM_FAILURE/else = gray
  const riskBorderColor =
    run.match_status === 'MISMATCH'        ? '#ef4444' :
    run.match_status === 'PARTIAL_MATCH'   ? '#f59e0b' :
    run.match_status === 'SYSTEM_FAILURE'  ? '#6b7280' : '#6b7280';

  // ── Contextual reason surfaced from detail ─────────────────────────
  const discrepancySummary: string = (() => {
    if (!detail) return '';
    if (detail.discrepancies && detail.discrepancies.length > 0) {
      return detail.discrepancies
        .map((d: string) => d.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (c: string) => c.toUpperCase()))
        .join(', ');
    }
    if (detail.system_failure_reason) return detail.system_failure_reason;
    if (detail.exception_reason)      return detail.exception_reason;
    return '';
  })();

  // ── Recommended action copy based on status ───────────────────────
  const recommendation =
    run.match_status === 'MATCH'          ? 'Automated check passed. Approve if the underlying documents align.' :
    run.match_status === 'PARTIAL_MATCH'  ? 'Minor discrepancy detected. Review line items before approving.' :
    run.match_status === 'MISMATCH'       ? 'Significant discrepancy found. Rejection is recommended unless override is justified.' :
    run.match_status === 'SYSTEM_FAILURE' ? 'Automated pipeline could not produce a result. Manual review is mandatory.' :
    'Manual clearance required.';

  // ── Action label in the confirm button ────────────────────────────
  const decisionLabel: Record<NonNullable<typeof activeDecision>, string> = {
    approve:  'Confirm Approval',
    reject:   'Confirm Rejection',
    override: 'Confirm Force Override',
  };

  const isReady = activeDecision !== null && reason.length >= 5 && !submitting;

  return (
    <div style={{
      borderTop: '1px solid #e5e7eb',
      borderLeft: `3px solid ${riskBorderColor}`,
      backgroundColor: '#f8fafc',
      padding: '20px 28px',
      display: 'flex',
      flexDirection: 'column',
      gap: '0',
    }}>

      {/* ── Single-line Horizontal Flex Row ─────────────────────────── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        
        {/* Left Side: Text */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
          <div style={{ fontSize: '1.25rem', fontWeight: 'bold', fontFamily: "'Space Grotesk', sans-serif", color: '#111827' }}>
            PENDING HUMAN AUDIT
          </div>
          <div style={{ fontSize: '13px', color: '#374151' }}>
            {recommendation}
            {discrepancySummary && (
              <span style={{ color: '#6b7280', display: 'block', marginTop: '4px', fontSize: '12px' }}>
                <strong style={{ fontWeight: 600 }}>Detected: </strong>{discrepancySummary}
              </span>
            )}
          </div>
        </div>

        {/* Right Side: Equal Buttons */}
        <div style={{ display: 'flex', gap: '12px' }}>
          
          <button
            onClick={() => { setActiveDecision('approve'); setReason(''); }}
            disabled={submitting}
            style={{
              width: '140px',
              padding: '10px 0',
              textAlign: 'center',
              borderRadius: '6px',
              fontSize: '13px',
              fontWeight: 500,
              border: '1px solid #22c55e',
              backgroundColor: activeDecision === 'approve' ? '#d1fae5' : 'transparent',
              color: '#166534',
              cursor: submitting ? 'not-allowed' : 'pointer',
              opacity: submitting ? 0.5 : 1,
              transition: 'background-color 0.15s ease, opacity 0.15s ease',
            }}
          >
            Approve
          </button>

          <button
            onClick={() => { setActiveDecision('override'); setReason(''); }}
            disabled={submitting}
            style={{
              width: '140px',
              padding: '10px 0',
              textAlign: 'center',
              borderRadius: '6px',
              fontSize: '13px',
              fontWeight: 500,
              border: '1px solid #f59e0b',
              backgroundColor: activeDecision === 'override' ? '#fef3c7' : 'transparent',
              color: '#b45309',
              cursor: submitting ? 'not-allowed' : 'pointer',
              opacity: submitting ? 0.5 : 1,
              transition: 'background-color 0.15s ease, opacity 0.15s ease',
            }}
          >
            Force Override
          </button>

          <button
            onClick={() => { setActiveDecision('reject'); setReason(''); }}
            disabled={submitting}
            style={{
              width: '140px',
              padding: '10px 0',
              textAlign: 'center',
              borderRadius: '6px',
              fontSize: '13px',
              fontWeight: 500,
              border: '1px solid #ef4444',
              backgroundColor: activeDecision === 'reject' ? '#fee2e2' : 'transparent',
              color: '#991b1b',
              cursor: submitting ? 'not-allowed' : 'pointer',
              opacity: submitting ? 0.5 : 1,
              transition: 'background-color 0.15s ease, opacity 0.15s ease',
            }}
          >
            Reject
          </button>

        </div>
      </div>

      {/* ── Inline audit form — expands below on decision selection ─── */}
      {activeDecision && (
        <div style={{
          marginTop: '16px',
          padding: '16px',
          backgroundColor: '#ffffff',
          border: '1px solid #e5e7eb',
          borderRadius: '6px',
          display: 'flex',
          flexDirection: 'column',
          gap: '12px',
        }}>

          {/* Decision context label */}
          <div style={{ fontSize: '12px', color: '#6b7280', fontWeight: 500 }}>
            {activeDecision === 'approve'  && 'Recording approval justification:'}
            {activeDecision === 'reject'   && 'Recording rejection justification:'}
            {activeDecision === 'override' && (
              <span style={{ color: '#b45309' }}>
                ⚠ Force Override — this will permanently supersede the automated result.
              </span>
            )}
          </div>

          {/* Reason textarea */}
          <textarea
            rows={3}
            placeholder="Enter justification for this decision (minimum 5 characters)…"
            value={reason}
            onChange={e => setReason(e.target.value)}
            disabled={submitting}
            style={{
              width: '100%',
              padding: '10px 12px',
              fontSize: '13px',
              borderRadius: '6px',
              border: '1px solid #d1d5db',
              outline: 'none',
              resize: 'vertical',
              fontFamily: 'inherit',
              color: '#111827',
              backgroundColor: '#fafafa',
              lineHeight: '1.5',
              boxSizing: 'border-box',
              opacity: submitting ? 0.5 : 1,
            }}
          />

          {/* Confirm button */}
          <button
            onClick={handleSubmit}
            disabled={!isReady}
            style={{
              alignSelf: 'flex-end',
              padding: '10px 24px',
              fontSize: '13px',
              fontWeight: 600,
              borderRadius: '6px',
              backgroundColor: isReady ? '#111827' : '#e5e7eb',
              color: isReady ? '#ffffff' : '#9ca3af',
              border: 'none',
              cursor: isReady ? 'pointer' : 'not-allowed',
              transition: 'background-color 0.15s ease',
              whiteSpace: 'nowrap',
            }}
          >
            {submitting ? 'Recording…' : (activeDecision ? decisionLabel[activeDecision] : 'Confirm')}
          </button>

          {/* Immutability attestation cue */}
          <p style={{
            margin: 0,
            fontSize: '11px',
            color: '#9ca3af',
            lineHeight: '1.5',
            display: 'flex',
            alignItems: 'flex-start',
            gap: '6px',
          }}>
            <span style={{ flexShrink: 0 }}>🔒</span>
            <span>
              Action will be permanently recorded to the audit ledger as{' '}
              <strong style={{ fontWeight: 600, color: '#6b7280' }}>demo_user</strong>.
              This entry is immutable and cannot be modified after submission.
            </span>
          </p>
        </div>
      )}
    </div>
  );
};
