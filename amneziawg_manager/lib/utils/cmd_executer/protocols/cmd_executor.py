from typing import Protocol


from amneziawg_manager.lib.utils.cmd_executer.models import CmdResult


class CmdExecutor(Protocol):

    def exec_cmd(
        self,
        cmd: str,
        stdin: str | None = None,
        check_result: bool = True,
    ) -> CmdResult:
        ...