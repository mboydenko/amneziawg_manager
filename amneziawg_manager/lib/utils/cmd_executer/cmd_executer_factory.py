from amneziawg_manager.lib.utils.cmd_executer.impl.local_cmd_executor import LocalCmdExecutor
from amneziawg_manager.lib.utils.cmd_executer.impl.ssh_cmd_executor import SshCmdExecutor
from amneziawg_manager.lib.utils.cmd_executer.protocols.cmd_executor import CmdExecutor
from amneziawg_manager.lib.utils.cmd_executer.models import SshConnection


class CmdExecutorFactory:

    def create_cmd_execptor(self, docker_container: str | None = None, ssh_connection: SshConnection | None = None) -> CmdExecutor:
        if ssh_connection:
            return SshCmdExecutor(ssh_connection=ssh_connection, docker_container=docker_container)
        else:
            return LocalCmdExecutor(docker_container=docker_container)
