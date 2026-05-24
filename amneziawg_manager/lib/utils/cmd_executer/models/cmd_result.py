from pydantic import BaseModel

class CmdResult(BaseModel):
    stdout: str
    stderr: str
    return_code: int

