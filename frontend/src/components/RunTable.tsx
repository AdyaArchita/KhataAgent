import React, { Component } from 'react';
import type { ErrorInfo, ReactNode } from 'react';
import type { RunSummary, MatchStatus } from '../api';
import { RunDetail } from './RunDetail';

interface RunTableProps {
  runs: RunSummary[];
}

export const RunTable: React.FC<RunTableProps> = ({ runs }) => {
  const [selectedRunId, setSelectedRunId] = React.useState<string | null>(null);

  return (
    <div className="table-container">
      <table className="run-table">
        <thead>
          <tr>
            <th>Date</th>
            <th>Vendor</th>
            <th>Invoice #</th>
            <th>Status</th>
            <th>Confidence</th>
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
              {(run.clearance_state === 'PENDING_HUMAN_AUDIT' || run.vendor_tier === 'MANDATORY_AUDIT' || (run.confidence !== undefined && run.confidence < 0.70)) && run.clearance_state !== 'MANUALLY_RELEASED' && run.clearance_state !== 'BLOCKED' && (
                <HitlActionRow run={run} />
              )}
              {selectedRunId === run.run_id && (
                <tr className="detail-row-wrapper">
                  <td colSpan={5}>
                    <RunDetail runId={run.run_id} />
                  </td>
                </tr>
              )}
            </RowErrorBoundary>
          ))}
        </tbody>
      </table>
      {runs.length === 0 && (
        <div className="empty-table">No runs available.</div>
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
  // Defensive checks to throw if malformed, triggering the ErrorBoundary
  if (!run || typeof run.run_id !== 'string') {
    throw new Error('Malformed run record');
  }

  const dateStr = run.created_at ? new Date(run.created_at).toLocaleString() : 'Unknown';
  
  return (
    <tr 
      className={`run-row ${isSelected ? 'selected' : ''}`}
      onClick={onSelect}
    >
      <td className="cell-date">{dateStr}</td>
      <td className="cell-vendor">
        {run.vendor_name || '—'}
        <TrustBadge tier={run.vendor_tier} />
      </td>
      <td className="cell-invoice">{run.invoice_number || '—'}</td>
      <td className="cell-status">
        <StatusBadge status={run.match_status} />
        <DuplicateBadge duplicateRisk={run.evidence_contract?.duplicate_risk} />
        <GstinBadge gstinValidation={run.evidence_contract?.gstin_validation} />
        <AnomalyBadge anomalyFlag={run.evidence_contract?.anomaly_flag} />
      </td>
      <td className="cell-confidence">
        {run.confidence != null ? `${(run.confidence * 100).toFixed(0)}%` : '—'}
      </td>
    </tr>
  );
};

const StatusBadge: React.FC<{ status: MatchStatus }> = ({ status }) => {
  let badgeClass = 'badge-default';
  if (status === 'MATCH') badgeClass = 'badge-match';
  else if (status === 'PARTIAL_MATCH') badgeClass = 'badge-partial';
  else if (status === 'MISMATCH') badgeClass = 'badge-mismatch';
  else if (status === 'SYSTEM_FAILURE' || status === 'NON_DETERMINISTIC_FAILURE') badgeClass = 'badge-failure';
  else if (status === 'PENDING REVIEW') badgeClass = 'badge-mismatch';
  
  return (
    <span className={`status-marker ${badgeClass}`}>
      {status || 'UNKNOWN'}
    </span>
  );
};

const TrustBadge: React.FC<{ tier?: string }> = ({ tier }) => {
  if (!tier) return null;
  
  let className = "trust-indicator ";
  if (tier === 'STANDARD') className += "trust-standard";
  else if (tier === 'ENHANCED') className += "trust-enhanced";
  else if (tier === 'MANDATORY_AUDIT') className += "trust-mandatory";
  else return null;

  return (
    <span className={className}>
      {tier.replace('_', ' ')}
    </span>
  );
};

const DuplicateBadge: React.FC<{ duplicateRisk?: any }> = ({ duplicateRisk }) => {
  if (!duplicateRisk) return null;
  const isCritical = duplicateRisk.risk_level === 'CRITICAL';
  return (
    <span 
      className={`status-marker ${isCritical ? 'badge-failure' : 'badge-mismatch'}`} 
      style={{ marginLeft: '6px' }} 
      title={duplicateRisk.reason}
    >
      ⚠️ Suspected Duplicate
    </span>
  );
};

const GstinBadge: React.FC<{ gstinValidation?: any }> = ({ gstinValidation }) => {
  if (!gstinValidation || gstinValidation.valid === true) return null;
  return (
    <span 
      className="status-marker badge-failure" 
      style={{ marginLeft: '6px' }} 
      title={gstinValidation.reason}
    >
      🛑 Invalid GSTIN
    </span>
  );
};

const AnomalyBadge: React.FC<{ anomalyFlag?: any }> = ({ anomalyFlag }) => {
  if (!anomalyFlag || anomalyFlag.is_anomaly !== true) return null;
  return (
    <span 
      className="status-marker badge-mismatch" 
      style={{ marginLeft: '6px' }} 
      title={anomalyFlag.reason}
    >
      📈 Statistical Outlier
    </span>
  );
};

// Error Boundary for individual rows
class RowErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  constructor(props: { children: ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(_: Error) {
    return { hasError: true };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error("Row parsing error:", error, errorInfo);
  }

  render() {
    if (this.state.hasError) {
      return (
        <tr className="run-row error-row">
          <td colSpan={5} className="unparseable-cell">Unparseable record</td>
        </tr>
      );
    }
    return this.props.children;
  }
}

const HitlActionRow: React.FC<{ run: RunSummary }> = ({ run }) => {
  const [cleared, setCleared] = React.useState<string | null>(null);
  const [modalOpen, setModalOpen] = React.useState(false);
  const [actionType, setActionType] = React.useState<'approve' | 'override' | 'reject'>('approve');
  const [reason, setReason] = React.useState('');
  const [error, setError] = React.useState('');

  const runId = run.run_id;

  const handleAction = async () => {
    if (reason.length < 5) {
      setError('Reason must be at least 5 characters');
      return;
    }
    try {
      const res = await fetch(`http://localhost:8000/api/reconciliation/${runId}/clearance`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ decision: actionType, reason, reviewed_by: 'demo_user' })
      });
      if (res.ok) {
        setCleared(actionType);
        setModalOpen(false);
      } else {
        setError('Failed to update clearance');
      }
    } catch (err) {
      setError('Network error');
      console.error(err);
    }
  };

  const promptModal = (action: 'approve' | 'override' | 'reject') => {
    setActionType(action);
    setReason('');
    setError('');
    setModalOpen(true);
  };

  if (cleared) {
    return (
      <tr className="hitl-action-row">
        <td colSpan={5} style={{ padding: '8px', textAlign: 'center', backgroundColor: '#f0fdf4' }}>
          State updated to: <strong>{cleared}</strong>
        </td>
      </tr>
    );
  }

  return (
    <>
      <tr className="hitl-action-row">
        <td colSpan={5} style={{ padding: '10px', backgroundColor: '#fffbe1', textAlign: 'center', borderBottom: '1px solid #ddd' }}>
          <strong style={{ marginRight: '15px' }}>Action Required:</strong>
          <button 
            onClick={() => promptModal('approve')} 
            style={{ marginRight: '10px', padding: '6px 12px', background: '#22c55e', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
          >
            Approve
          </button>
          <button 
            onClick={() => promptModal('override')} 
            style={{ marginRight: '10px', padding: '6px 12px', background: '#eab308', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
          >
            Override
          </button>
          <button 
            onClick={() => promptModal('reject')} 
            style={{ padding: '6px 12px', background: '#ef4444', color: '#fff', border: 'none', borderRadius: '4px', cursor: 'pointer' }}
          >
            Reject
          </button>
        </td>
      </tr>
      {modalOpen && (
        <tr className="hitl-modal-row">
          <td colSpan={5} style={{ padding: '15px', backgroundColor: '#f9fafb', borderBottom: '1px solid #ddd' }}>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxWidth: '400px', margin: '0 auto' }}>
              <strong>Confirm {actionType.toUpperCase()}</strong>
              <input 
                type="text" 
                value={reason} 
                onChange={(e) => setReason(e.target.value)} 
                placeholder="Reason (min 5 chars)"
                style={{ padding: '8px', borderRadius: '4px', border: '1px solid #ccc' }}
              />
              {error && <div style={{ color: 'red', fontSize: '12px' }}>{error}</div>}
              <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
                <button onClick={() => setModalOpen(false)} style={{ padding: '6px 12px', borderRadius: '4px', border: '1px solid #ccc', background: '#fff', cursor: 'pointer' }}>Cancel</button>
                <button onClick={handleAction} style={{ padding: '6px 12px', borderRadius: '4px', border: 'none', background: '#3b82f6', color: '#fff', cursor: 'pointer' }}>Submit</button>
              </div>
            </div>
          </td>
        </tr>
      )}
    </>
  );
};
