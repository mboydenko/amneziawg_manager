import paramiko

from amneziawg_manager.lib.utils.cmd_executer.models import (
    CmdResult,
    SshConnection,
)
from amneziawg_manager.lib.utils.cmd_executer.protocols.cmd_executor import (
    CmdExecutor,
)
from amneziawg_manager.lib.utils.logger import Logger


_logger = Logger("SshCmdExecutor")


class _Client:

    def __init__(
        self,
        host: str,
        port: int,
        username: str,
        password: str,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._client: paramiko.SSHClient | None = None

    @_logger.log_function(level="trace")
    def connect(self):
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(
            paramiko.AutoAddPolicy()
        )

        self._client.connect(
            hostname=self._host,
            port=self._port,
            username=self._username,
            password=self._password,
        )

    @_logger.log_function(level="trace")
    def close(self):
        if self._client:
            self._client.close()
            self._client = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    @_logger.log_function(level="trace")
    def exec(
        self,
        cmd: str,
        stdin: str | None = None,
    ) -> CmdResult:

        if not self._client:
            raise RuntimeError(
                "SSH connection is not opened"
            )

        stdin_pipe, stdout_pipe, stderr_pipe = (
            self._client.exec_command(cmd)
        )

        if stdin:
            stdin_pipe.write(stdin)
            stdin_pipe.flush()
            stdin_pipe.channel.shutdown_write()

        stdout = stdout_pipe.read().decode("utf-8")
        stderr = stderr_pipe.read().decode("utf-8")

        return_code = stdout_pipe.channel.recv_exit_status()

        return CmdResult(
            stdout=stdout,
            stderr=stderr,
            return_code=return_code,
        )


class SshCmdExecutor(CmdExecutor):

    def __init__(
        self,
        ssh_connection: SshConnection,
        docker_container: str | None = None,
    ) -> None:
        self._connection = ssh_connection
        self._docker_container = docker_container

    @_logger.log_function()
    def exec_cmd(
        self,
        cmd: str,
        stdin: str | None = None,
        check_result: bool = True,
    ) -> CmdResult:

        if self._docker_container:
            cmd = (
                f"docker exec -i "
                f"{self._docker_container} "
                f"sh -c {cmd!r}"
            )

        with _Client(
            host=self._connection.host,
            port=self._connection.port,
            username=self._connection.username,
            password=self._connection.password,
        ) as client:

            result = client.exec(
                cmd=cmd,
                stdin=stdin,
            )

        if check_result and result.return_code != 0:
            raise RuntimeError(result.stderr)

        return result
