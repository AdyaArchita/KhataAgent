def validate_gstin(gstin: str) -> dict:
    """
    Validates GSTIN format and checksum. Returns:
    {"valid": bool, "reason": str | None, "state_code": str | None}
    Does NOT call any external API (no live GST portal lookup) — this is 
    pure structural/checksum validation, and must be labeled as such 
    wherever it's surfaced.
    """
    if not isinstance(gstin, str) or len(gstin) != 15:
        return {"valid": False, "reason": "Invalid length, must be 15 characters", "state_code": None}

    gstin = gstin.upper()
    charset = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    
    # Structural check
    state_code = gstin[0:2]
    if not state_code.isdigit():
        return {"valid": False, "reason": "State code must be digits", "state_code": None}
    if not gstin[2:7].isalpha():
        return {"valid": False, "reason": "Characters 3-7 must be letters", "state_code": state_code}
    if not gstin[7:11].isdigit():
        return {"valid": False, "reason": "Characters 8-11 must be digits", "state_code": state_code}
    if not gstin[11:12].isalpha():
        return {"valid": False, "reason": "Character 12 must be a letter", "state_code": state_code}
    if gstin[12] not in charset:
        return {"valid": False, "reason": "Character 13 must be alphanumeric", "state_code": state_code}
    if gstin[13] != 'Z':
        return {"valid": False, "reason": "Character 14 must be 'Z'", "state_code": state_code}
    if gstin[14] not in charset:
        return {"valid": False, "reason": "Checksum character must be alphanumeric", "state_code": state_code}

    # Checksum: Luhn mod-36
    total = 0
    for i in range(14):
        char_value = charset.index(gstin[i])
        weight = 1 if i % 2 == 0 else 2
        product = char_value * weight
        hash_val = (product // 36) + (product % 36)
        total += hash_val
    
    expected_checksum_index = (36 - (total % 36)) % 36
    expected_checksum_char = charset[expected_checksum_index]

    if gstin[14] != expected_checksum_char:
        return {"valid": False, "reason": f"Invalid checksum (expected {expected_checksum_char}, got {gstin[14]})", "state_code": state_code}

    return {"valid": True, "reason": None, "state_code": state_code}
