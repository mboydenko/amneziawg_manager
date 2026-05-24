import subprocess

from amneziawg_manager.lib.utils.cmd_executer.protocols.cmd_executor import CmdExecutor
from amneziawg_manager.lib.utils.cmd_executer.models.cmd_result import CmdResult 

class DockerCmdExecutor(CmdExecutor):

    def __init__(self, container_name: str):
        self.container_name = container_name

    def exec_cmd(self, cmd: str, check_result: bool = True) -> CmdResult:
        docker_cmd = f'docker exec {self.container_name} {cmd}'
        subprocess_result = subprocess.run(docker_cmd, shell=True, capture_output=True, text=True)
        res = CmdResult(
            stdout=subprocess_result.stdout,
            stderr=subprocess_result.stderr,
            return_code=subprocess_result.returncode
        )
        if check_result:
            if res.return_code != 0:
                raise RuntimeError(res.stderr)
        return res
