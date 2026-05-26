import subprocess

from amneziawg_manager.lib.utils.cmd_executer.models import CmdResult
from amneziawg_manager.lib.utils.cmd_executer.protocols.cmd_executor import CmdExecutor
from amneziawg_manager.lib.utils.logger import Logger


_logger = Logger("LocalCmdExecutor")


class LocalCmdExecutor(CmdExecutor):

    def __init__(
        self,
        docker_container: str | None = None,
    ) -> None:
        self._docker_container = docker_container

    @_logger.log_function()
    def exec_cmd(
        self,
        cmd: str,
        stdin: str | None = None,
        check_result: bool = True,
    ) -> CmdResult:

        if self._docker_container:
            final_cmd = [
                "docker",
                "exec",
                "-i",
                self._docker_container,
                "sh",
                "-c",
                cmd,
            ]
        else:
            final_cmd = [
                "sh",
                "-c",
                cmd,
            ]

        _logger.debug(f"Exec cmd: {final_cmd}")

        subprocess_result = subprocess.run(
            final_cmd,
            input=stdin,
            text=True,
            capture_output=True,
        )

        result = CmdResult(
            stdout=subprocess_result.stdout,
            stderr=subprocess_result.stderr,
            return_code=subprocess_result.returncode,
        )

        if check_result and result.return_code != 0:
            raise RuntimeError(result.stderr)

        return result
