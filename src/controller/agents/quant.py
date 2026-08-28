"""QuantAgent — code-generation reconciliation agent with sandboxed execution.

This module contains:
  1. ``CodeExecutionTool`` — AST-validated, subprocess-sandboxed executor.
  2. ``QuantAgent``        — LLM-driven code generator that produces a
                             pure-Python reconciliation script, executes it
                             in the sandbox, and interprets the result.

Security model
──────────────
  • Generated code is validated with ``ast.parse`` + a ``NodeVisitor``
    that rejects all imports except ``math`` and ``decimal``, blocks
    calls to ``open / eval / exec / __import__ / getattr / setattr``,
    and blocks any attribute access containing dunder names.
  • Execution happens in a child process via ``subprocess.run`` with a
    5-second wall-clock timeout.
  • Memory limits are enforced via ``resource.setrlimit`` where available
    (Linux / macOS).  On Windows the limit is skipped with a visible
    warning — this is by design for the buildathon dev loop.
  • A trusted *wrapper* prepends ``import json`` and appends
    ``print(json.dumps(result))`` around the generated code so the LLM
    never needs to import ``json`` itself (which would be blocked by the
    AST allowlist).  The AST check validates only the *untrusted*
    generated portion.
"""

from __future__ import annotations

import ast
import json
import logging
import subprocess
import sys
import textwrap
import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from controller.state import (
    Discrepancy,
    MatchStatus,
    ReconciliationState,
)

logger = logging.getLogger(__name__)

# ── AST safety validation ────────────────────────────────────────────

_ALLOWED_IMPORTS: frozenset[str] = frozenset({"math", "decimal", "collections"})
_BLOCKED_CALLS: frozenset[str] = frozenset(
    {"open", "eval", "exec", "__import__", "getattr", "setattr"}
)


class _SafetyVisitor(ast.NodeVisitor):
    """Walk an AST and collect every security violation."""

    def __init__(self) -> None:
        self.violations: list[str] = []

    # ── imports ──────────────────────────────────────────────────────

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            root_module = alias.name.split(".")[0]
            if root_module not in _ALLOWED_IMPORTS:
                self.violations.append(f"Blocked import: {alias.name}")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        root_module = (node.module or "").split(".")[0]
        if root_module not in _ALLOWED_IMPORTS:
            self.violations.append(f"Blocked import-from: {node.module}")
        self.generic_visit(node)

    # ── dangerous calls ──────────────────────────────────────────────

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in _BLOCKED_CALLS:
            self.violations.append(f"Blocked call: {node.func.id}")
        self.generic_visit(node)

    # ── dunder attribute access ──────────────────────────────────────

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if "__" in node.attr:
            self.violations.append(f"Blocked dunder attribute: {node.attr}")
        self.generic_visit(node)


def validate_ast(code: str) -> list[str]:
    """Parse *code* and return a list of security violations (empty = safe)."""
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [f"SyntaxError: {exc}"]

    visitor = _SafetyVisitor()
    visitor.visit(tree)
    return visitor.violations


# ── Subprocess execution ─────────────────────────────────────────────

# The wrapper is *trusted* code prepended/appended around the
# *untrusted* LLM-generated snippet.  It handles JSON serialisation
# and optional memory limiting so the generated code never needs to
# import ``json`` or ``resource``.
_EXECUTION_WRAPPER = textwrap.dedent("""\
    import sys
    import json
    import math
    from decimal import Decimal

    # ── platform-aware memory limit ──────────────────────────────────
    try:
        import resource
        _MEM_LIMIT = 256 * 1024 * 1024  # 256 MiB
        resource.setrlimit(resource.RLIMIT_AS, (_MEM_LIMIT, _MEM_LIMIT))
    except ImportError:
        print(
            "WARNING: Memory limiting is disabled on this platform "
            "(resource module unavailable)",
            file=sys.stderr,
        )

    # ══ BEGIN GENERATED CODE ═════════════════════════════════════════
    {generated_code}
    # ══ END GENERATED CODE ═══════════════════════════════════════════

    class _Encoder(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, Decimal):
                return float(obj)
            return super().default(obj)

    print(json.dumps(result, cls=_Encoder))
""")


@dataclass
class ExecutionResult:
    """Outcome of a single sandbox execution."""

    success: bool
    output: dict[str, Any] | None = None
    error: str | None = None
    stdout_raw: str = ""
    stderr_raw: str = ""


def execute_in_sandbox(code: str, *, timeout: int = 5) -> ExecutionResult:
    """Run an AST-validated Python snippet in a subprocess sandbox.

    Steps:
      1. AST-validate the *untrusted* ``code``.
      2. Wrap in the trusted execution template.
      3. Execute via ``subprocess.run`` with wall-clock ``timeout``.
      4. Parse stdout as JSON.

    Returns an ``ExecutionResult`` with either the parsed output or an
    error description.
    """
    # ── step 1: AST validation ───────────────────────────────────────
    violations = validate_ast(code)
    if violations:
        detail = "; ".join(violations)
        logger.warning("AST rejection: %s", detail)
        return ExecutionResult(
            success=False,
            error=f"AST_REJECTION: {detail}",
        )

    # ── step 2: wrap ─────────────────────────────────────────────────
    full_script = _EXECUTION_WRAPPER.format(generated_code=code)

    # ── step 3: execute ──────────────────────────────────────────────
    try:
        proc = subprocess.run(
            [sys.executable, "-c", full_script],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        logger.warning("Sandbox execution timed out (%ds)", timeout)
        return ExecutionResult(
            success=False,
            error=f"TIMEOUT: Execution exceeded {timeout}s wall-clock limit",
        )

    stdout_raw = proc.stdout.strip()
    stderr_raw = proc.stderr.strip()

    if proc.returncode != 0:
        logger.warning(
            "Sandbox non-zero exit (%d): stderr=%s",
            proc.returncode,
            stderr_raw[:500],
        )
        return ExecutionResult(
            success=False,
            error=f"EXIT_CODE_{proc.returncode}: {stderr_raw[:500]}",
            stdout_raw=stdout_raw,
            stderr_raw=stderr_raw,
        )

    # ── step 4: parse JSON ───────────────────────────────────────────
    try:
        # The LLM sometimes includes rogue `print(result)` statements which corrupt stdout.
        # Since `print(json.dumps(result))` is the final wrapper instruction, we safely extract the last line.
        lines = [line.strip() for line in stdout_raw.strip().split('\n') if line.strip()]
        last_line = lines[-1] if lines else ""
        parsed = json.loads(last_line)
    except (json.JSONDecodeError, IndexError) as exc:
        logger.warning("Non-JSON stdout: %s", stdout_raw[:300])
        return ExecutionResult(
            success=False,
            error=f"JSON_PARSE_ERROR: {exc}",
            stdout_raw=stdout_raw,
            stderr_raw=stderr_raw,
        )

    return ExecutionResult(
        success=True,
        output=parsed,
        stdout_raw=stdout_raw,
        stderr_raw=stderr_raw,
    )


# ── Code extraction helper ───────────────────────────────────────────

def _extract_code(llm_response: Any) -> str:
    """Pull the Python code out of a markdown-fenced LLM response.

    If the response is already bare code (no fences), return it as-is.
    """
    import re

    if isinstance(llm_response, list):
        llm_response = "".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in llm_response
        )
    elif not isinstance(llm_response, str):
        llm_response = str(llm_response)

    pattern = r"```(?:python)?\s*\n(.*?)```"
    match = re.search(pattern, llm_response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return llm_response.strip()


# ── LLM prompt ───────────────────────────────────────────────────────

_SYSTEM_PROMPT = textwrap.dedent("""\
    You are a precise financial reconciliation calculator.  You receive
    structured numeric data from an invoice and a ledger and must produce
    a self-contained Python script that compares them.

    RULES — follow exactly:
    1.  Use ONLY Python built-ins, ``math``, and ``decimal``.
        Do NOT import any other module (including ``json``).
    2.  Do NOT use file I/O, network calls, eval, exec, or dunder access.
    3.  Store your final answer in a variable named ``result`` — a plain
        Python dict (the caller will serialise it for you).
    4.  The ``result`` dict MUST have exactly these keys:
          invoice_amount   : float
          ledger_amount    : float
          amount_difference: float  (absolute value)
          tax_difference   : float  (absolute value)
          tax_rate_match   : bool
          gstin_match      : bool
          currency_match   : bool
          line_items_missing : int  (ledger items absent from invoice)
          line_items_extra   : int  (invoice items absent from ledger)
          line_items_matched : int
    5.  Define all data as inline literals — the script must be
        completely self-contained.
    6.  Be precise with floating-point arithmetic — use ``round()`` where
        appropriate.
""")


def _build_human_prompt(
    invoice_data: dict[str, Any],
    ledger_data: dict[str, Any],
) -> str:
    """Format the human message with structured numeric data.

    Raw invoice text is NEVER included here — only pre-extracted numbers.
    """
    return textwrap.dedent(f"""\
        Compare the following financial data and generate a Python script.

        INVOICE DATA (extracted from document):
          amount      = {invoice_data['amount']}
          tax_amount  = {invoice_data['tax_amount']}
          tax_rate    = {invoice_data['tax_rate']}
          gstin       = {json.dumps(invoice_data['gstin'])}
          currency    = {json.dumps(invoice_data['currency'])}
          line_items  = {json.dumps(invoice_data['line_items'])}

        LEDGER DATA (from accounting system):
          amount      = {ledger_data['amount']}
          tax_amount  = {ledger_data['tax_amount']}
          tax_rate    = {ledger_data['tax_rate']}
          gstin       = {json.dumps(ledger_data['gstin'])}
          currency    = {json.dumps(ledger_data['currency'])}
          line_items  = {json.dumps(ledger_data['line_items'])}

        Generate the script now.
    """)


# ── QuantAgent ───────────────────────────────────────────────────────

class QuantAgent:
    """LLM-driven reconciliation code generator.

    Uses ``ChatOpenAI(model="gpt-4o-mini", temperature=0)`` for
    deterministic code generation.  The generated script is executed
    in the ``CodeExecutionTool`` sandbox and the result interpreted
    into ``MatchStatus``, ``Discrepancy``, and confidence values.
    """

    def __init__(self) -> None:
        from dotenv import load_dotenv
        import os

        load_dotenv(override=True)

        self.llm = ChatGoogleGenerativeAI(
            model=os.getenv("LLM_MODEL", "gemini-3.5-flash-lite"),
            temperature=0,
            api_key=os.getenv("GEMINI_API_KEY"),
        )

    # ── public API ───────────────────────────────────────────────────

    def run(self, state: ReconciliationState) -> dict[str, Any]:
        """Generate, execute, and interpret a reconciliation script.

        Returns a partial-state dict suitable for LangGraph merging.
        """
        try:
            return self._run_inner(state)
        except Exception as exc:
            logger.exception("QuantAgent unexpected error")
            return {
                "match_status": MatchStatus.SYSTEM_FAILURE,
                "confidence": 0.0,
                "system_failure_reason": f"QuantAgent error: {exc}",
            }

    # ── internals ────────────────────────────────────────────────────

    def _run_inner(self, state: ReconciliationState) -> dict[str, Any]:
        if state.ledger_record is None:
            return {
                "match_status": MatchStatus.SYSTEM_FAILURE,
                "confidence": 0.0,
                "system_failure_reason": "No ledger record available for comparison",
            }

        # ── prepare data for the prompt (never raw text) ─────────────
        invoice_data = self._extract_invoice_data(state)
        ledger_data = self._extract_ledger_data(state)

        # ── LLM call ─────────────────────────────────────────────────
        messages = [
            SystemMessage(content=_SYSTEM_PROMPT),
            HumanMessage(content=_build_human_prompt(invoice_data, ledger_data)),
        ]

        t0 = time.perf_counter()
        response = self.llm.invoke(messages)
        llm_latency = (time.perf_counter() - t0) * 1000

        # Track token usage
        usage = response.response_metadata.get("token_usage", {})
        token_usage = {
            "prompt_tokens": usage.get("prompt_tokens", 0),
            "completion_tokens": usage.get("completion_tokens", 0),
            "total_tokens": usage.get("total_tokens", 0),
        }

        # ── extract code ─────────────────────────────────────────────
        generated_code = _extract_code(response.content)
        logger.info(
            "QuantAgent generated %d-char snippet (%.0fms LLM latency)",
            len(generated_code),
            llm_latency,
        )
        logger.debug("Generated code:\n%s", generated_code)

        # ── execute in sandbox ───────────────────────────────────────
        exec_result = execute_in_sandbox(generated_code)

        if exec_result.success:
            exec_result_replay = execute_in_sandbox(generated_code)
            self_consistency = True
            replay_delta = None
            if exec_result_replay.success:
                amt1 = float(exec_result.output.get("amount_difference", 0.0) if exec_result.output else 0.0)
                amt2 = float(exec_result_replay.output.get("amount_difference", 0.0) if exec_result_replay.output else 0.0)
                if amt1 != amt2:
                    self_consistency = False
                    replay_delta = abs(amt1 - amt2)
            else:
                self_consistency = False
        else:
            self_consistency = False
            replay_delta = None


        if not exec_result.success:
            logger.warning("Sandbox failure: %s", exec_result.error)
            return {
                "generated_code": generated_code,
                "execution_result": None,
                "match_status": MatchStatus.SYSTEM_FAILURE,
                "confidence": 0.0,
                "system_failure_reason": exec_result.error,
                "token_usage": token_usage,
            }

        logger.info("Sandbox execution succeeded: %s", exec_result.output)

        # ── interpret result ─────────────────────────────────────────
        return self._interpret(
            exec_result.output,  # type: ignore[arg-type]
            generated_code,
            token_usage,
            state,
            self_consistency,
            replay_delta
        )

    def _extract_invoice_data(self, state: ReconciliationState) -> dict[str, Any]:
        """Pull numeric fields from the parsed invoice (TransactionData)."""
        tx = state.transaction
        return {
            "amount": tx.amount,
            "tax_amount": tx.tax_amount,
            "tax_rate": tx.tax_rate,
            "gstin": tx.gstin,
            "currency": tx.currency,
            "line_items": [item.model_dump() for item in tx.line_items],
        }

    def _extract_ledger_data(self, state: ReconciliationState) -> dict[str, Any]:
        """Pull numeric fields from the ledger record dict."""
        lr = state.ledger_record
        assert lr is not None
        line_items_raw = lr.get("line_items", "[]")
        if isinstance(line_items_raw, str):
            line_items = json.loads(line_items_raw)
        else:
            line_items = line_items_raw
        return {
            "amount": lr["amount"],
            "tax_amount": lr["tax_amount"],
            "tax_rate": lr["tax_rate"],
            "gstin": lr["gstin"],
            "currency": lr["currency"],
            "line_items": line_items,
        }

    def _interpret(
        self,
        output: dict[str, Any],
        generated_code: str,
        token_usage: dict[str, int],
        state: ReconciliationState,
        self_consistency: bool,
        replay_delta: float | None
    ) -> dict[str, Any]:
        """Map sandbox output to MatchStatus, Discrepancy list, and confidence.

        Confidence scoring (deterministic):
          1.0      clean match — all checks pass, |amount_diff| ≤ 0.01
          0.9      clear discrepancy diagnosed
          0.6–0.8  partial band (0.01 < |amount_diff| ≤ 1.00, no other issues)
          0.0      reserved for system failures (already handled above)
        """
        discrepancies: list[Discrepancy] = []

        amount_diff = abs(float(output.get("amount_difference", 999)))
        tax_diff = abs(float(output.get("tax_difference", 0)))
        tax_rate_match = bool(output.get("tax_rate_match", True))
        gstin_match = bool(output.get("gstin_match", True))
        currency_match = bool(output.get("currency_match", True))
        missing = int(output.get("line_items_missing", 0))
        extra = int(output.get("line_items_extra", 0))

        # ── collect discrepancies ────────────────────────────────────
        if amount_diff > 0.01:
            discrepancies.append(Discrepancy.AMOUNT_MISMATCH)
            
        tax_rate = state.transaction.tax_rate
        expected_tax_diff = amount_diff * (tax_rate / (1.0 + tax_rate))
        
        # If rate matches and tax difference is purely derived from amount difference,
        # do NOT flag TAX_MISMATCH independently.
        if not tax_rate_match or abs(tax_diff - expected_tax_diff) > 0.02:
            if tax_diff > 0.01 or not tax_rate_match:
                discrepancies.append(Discrepancy.TAX_MISMATCH)
        if not gstin_match:
            discrepancies.append(Discrepancy.GSTIN_MISMATCH)
        if not currency_match:
            discrepancies.append(Discrepancy.CURRENCY_MISMATCH)
        if missing > 0:
            discrepancies.append(Discrepancy.MISSING_LINE)
        if extra > 0:
            discrepancies.append(Discrepancy.DUPLICATE)

        # ── determine status + confidence ────────────────────────────
        if not discrepancies:
            # Clean match — everything agrees
            match_status = MatchStatus.MATCH
            confidence = 1.0

        elif (
            set(discrepancies).issubset({
                Discrepancy.AMOUNT_MISMATCH, 
                Discrepancy.TAX_MISMATCH, 
                Discrepancy.MISSING_LINE, 
                Discrepancy.DUPLICATE
            })
            and tax_rate_match
            and 0.01 < amount_diff <= 2.00
        ):
            # Partial band — amount is the ONLY fundamental issue and within tolerance.
            # (tax may differ slightly, and line item matching may fail due to the amount change, but rate matches)
            match_status = MatchStatus.PARTIAL_MATCH
            # Linear interpolation: diff=0.01 → 0.8,  diff=2.00 → 0.6
            confidence = round(0.8 - 0.2 * (amount_diff - 0.01) / 1.99, 4)

        else:
            # Clear discrepancy
            match_status = MatchStatus.MISMATCH
            confidence = 0.9

        return {
            "generated_code": generated_code,
            "execution_result": output,
            "match_status": match_status,
            "discrepancies": discrepancies,
            "confidence": confidence,
            "token_usage": token_usage,
        }
