with open('src/controller/state.py', 'r', encoding='utf-8') as f:
    content = f.read()

content = content.replace('SYSTEM_FAILURE = "SYSTEM_FAILURE"', 'SYSTEM_FAILURE = "SYSTEM_FAILURE"\n    NON_DETERMINISTIC_FAILURE = "NON_DETERMINISTIC_FAILURE"')

with open('src/controller/state.py', 'w', encoding='utf-8') as f:
    f.write(content)
