from abc import ABC, abstractmethod

from amneziawg_manager.lib.utils.cmd_executer.models.cmd_result import CmdResult

class CmdExecutor(ABC):

    @abstractmethod
    def exec_cmd(self, cmd: str, check_result: bool = True) -> CmdResult:
        ...
