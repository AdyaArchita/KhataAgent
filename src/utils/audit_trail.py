from pydantic import BaseModel
from typing import Optional

class LineageStep(BaseModel):
    step_name: str
    timestamp: str
    input_summary: str
    output_summary: str
    code_executed: Optional[str] = None
