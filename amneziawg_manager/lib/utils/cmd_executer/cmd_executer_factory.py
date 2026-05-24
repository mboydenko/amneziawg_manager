from amneziawg_manager.lib.utils.cmd_executer.impl.docker_cmd_executor import DockerCmdExecutor
from amneziawg_manager.lib.utils.cmd_executer.impl.local_cmd_executor import LocalCmdExecutor
from amneziawg_manager.lib.utils.cmd_executer.protocols.cmd_executor import CmdExecutor

class CmdExecutorFactory:

    def create_cmd_execptor(self, container_name: str | None = None) -> CmdExecutor:
        if container_name:
            return DockerCmdExecutor(container_name)
        else:
            return LocalCmdExecutor()
