export type MatchStatus = 'MATCH' | 'MISMATCH' | 'PARTIAL_MATCH' | 'PENDING' | 'SYSTEM_FAILURE' | 'PENDING REVIEW' | 'NON_DETERMINISTIC_FAILURE';

export interface RunSummary {
  run_id: string;
  ledger_id: string;
  vendor_name: string;
  invoice_number: string;
  match_status: MatchStatus;
  confidence: number;
  latency_ms: number;
  created_at: string;
  vendor_tier?: string;
  requires_human_review?: boolean;
  evidence_contract?: any;
  clearance_state?: string;
}

export interface RunDetail extends RunSummary {
  discrepancies: string[];
  exception_reason: string | null;
  system_failure_reason: string | null;
  generated_code: string;
  execution_result: any;
}



export async function fetchRuns(): Promise<RunSummary[]> {
  const response = await fetch('/api/runs');
  if (!response.ok) {
    throw new Error('Backend not connected or returned an error.');
  }
  const contentType = response.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    throw new Error('Backend not connected (received HTML instead of JSON).');
  }
  return response.json();
}

export async function fetchRunDetail(run_id: string): Promise<RunDetail> {
  const response = await fetch(`/api/runs/${run_id}`);
  if (!response.ok) {
    throw new Error(`Failed to fetch details for run ${run_id}`);
  }
  const contentType = response.headers.get('content-type');
  if (!contentType || !contentType.includes('application/json')) {
    throw new Error('Backend not connected (received HTML instead of JSON).');
  }
  return response.json();
}

export async function submitHitlDecision(runId: string, decision: 'approve' | 'reject' | 'override', reason: string): Promise<any> {
  const response = await fetch(`/api/reconciliation/${runId}/clearance`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ decision, reason, reviewed_by: 'demo_user' })
  });

  if (!response.ok) {
    const errorData = await response.json().catch(() => null);
    throw new Error(errorData?.detail || `Failed to submit decision for run ${runId}`);
  }

  return response.json();
}
