from amneziawg_manager.lib.utils.cmd_executer.models import CmdResult, SshConnection
from amneziawg_manager.lib.utils.cmd_executer.protocols.cmd_executor import CmdExecutor
from amneziawg_manager.lib.utils.logger import Logger

import paramiko

_logger = Logger('SshCmdExecutor')

class _Client:

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._client = None

    @_logger.log_function()
    def connect(self):
        self._client = paramiko.SSHClient()
        self._client.connect(self._host, self._port, username=self._username, password=self._password)
    
    @_logger.log_function()
    def close(self):
        if not self._client:
            return
        self._client.close()
        self._client = None

    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc, tb):
        self.close()
    
    @_logger.log_function()
    def exec(self, cmd: str) -> CmdResult:
        if not self._client:
            raise RuntimeError('SSH connection is not opened')
        _, stdout, stderr = self._client.exec_command(cmd)
        code = 0 if not stderr else 1
        return CmdResult(
            stderr=stderr.read().decode('utf-8'),
            stdout=stdout.read().decode('utf-8'),
            return_code=code
        )

class SshCmdExecutor(CmdExecutor):
    def __init__(self, ssh_connection: SshConnection, docker_container: str | None = None) -> None:
        self._connection = ssh_connection
        self._docker_container = docker_container

    @_logger.log_function()
    def exec_cmd(self, cmd: str, check_result: bool = True) -> CmdResult:
        with _Client(host=self._connection.host, 
                     port=self._connection.port, 
                     username=self._connection.username, 
                     password=self._connection.password,
            ) as client:
            if self._docker_container:
                cmd = f'docker exec {self._docker_container} {cmd}'
            res = client.exec(cmd) 
        if check_result:
            if res.return_code != 0:
                raise RuntimeError(res.stderr)
        return res

    