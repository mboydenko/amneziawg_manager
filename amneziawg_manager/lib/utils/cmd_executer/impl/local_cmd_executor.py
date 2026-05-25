import subprocess

from amneziawg_manager.lib.utils.cmd_executer.protocols.cmd_executor import CmdExecutor
from amneziawg_manager.lib.utils.cmd_executer.models import CmdResult 

from amneziawg_manager.lib.utils.logger import Logger

_logger = Logger('LocalCmdExecutor')

class LocalCmdExecutor(CmdExecutor):

    def __init__(self, docker_container: str | None = None) -> None:
        self._docker_container =docker_container

    @_logger.log_function()
    def exec_cmd(self, cmd: str, check_result: bool = True) -> CmdResult:
        if self._docker_container:
            cmd = f'docker exec {self._docker_container} {cmd}'

        subprocess_result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        res = CmdResult(
            stdout=subprocess_result.stdout,
            stderr=subprocess_result.stderr,
            return_code=subprocess_result.returncode
        )
        if check_result:
            if res.return_code != 0:
                raise RuntimeError(res.stderr)
        return res
