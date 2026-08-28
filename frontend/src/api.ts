export type MatchStatus = 'MATCH' | 'MISMATCH' | 'PARTIAL_MATCH' | 'PENDING' | 'SYSTEM_FAILURE' | 'PENDING REVIEW';

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
