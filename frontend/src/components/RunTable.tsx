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
  if (!tier || tier === 'STANDARD') return null; // Keep standard silent to reduce visual noise
  
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
