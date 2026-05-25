from pydantic import BaseModel

class CmdResult(BaseModel):
    stdout: str
    stderr: str
    return_code: int

class SshConnection(BaseModel):
    host: str
    port: int
    username: str
    password: str
