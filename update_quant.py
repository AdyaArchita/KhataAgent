import re

with open('src/controller/agents/quant.py', 'r', encoding='utf-8') as f:
    content = f.read()

replacement = '''
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

        if not self_consistency:
            logger.warning("Sandbox failure: NON_DETERMINISTIC_FAILURE")
            return {
                "generated_code": generated_code,
                "execution_result": None,
                "match_status": MatchStatus.NON_DETERMINISTIC_FAILURE,
                "confidence": 0.0,
                "system_failure_reason": f"Self-Consistency Replay Failed. Delta: {replay_delta}",
                "token_usage": token_usage,
            }
'''

content = re.sub(r'\n        if not exec_result\.success:.*?\n                "token_usage": token_usage,\n            }', replacement, content, flags=re.DOTALL)

with open('src/controller/agents/quant.py', 'w', encoding='utf-8') as f:
    f.write(content)
