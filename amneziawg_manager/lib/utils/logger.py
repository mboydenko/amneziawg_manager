from typing import Any
import functools

from loguru import logger

def _deb(log: str):
    logger.debug(log)

def _info(log: str):
    logger.info(log)

def _err(log: str):
    logger.error(log)

def _trace(log: str):
    logger.trace(log)

def _warning(log: str):
    logger.warning(log)

def _critical(log: str):
    logger.critical(log)
    

def _log(log: str, level: str):
    if level == 'debug':
        _deb(log)

    elif level == 'info':
        _info(log)

    elif level == 'error':
        _err(log)

    elif level == 'warning':
        _warning(log)

    elif level == 'trace':
        _trace(log)

    elif level == 'critical':
        _critical(log)
    else:
        raise RuntimeError(f'Unknown log level: {level}')

def _func_dec(log: str | None = None, level: str = 'debug',  # type: ignore
              log_params: bool = True, log_result: bool = True):
    
    def _dec(func):

        @functools.wraps(func)
        def _wrapper(*args, **kwargs):

            if not callable(func):
                raise RuntimeError('Incorrect using of the decorator')

            if log:
                _log(log, level=level)

            _log(f'"{func}"', level=level)

            if log_params:
                _log(f'"{func}" parameters:\nArgs: {args}\nKwargs: {kwargs}', level=level)

            result = func(*args, **kwargs)

            if log_result:
                _log(f'"{func}" result:\n{result}', level=level)

            return result # type: ignore
        return _wrapper # type: ignore
    
    return _dec # type: ignore


class _logger:

    def __init__(self, log: str, level: str = 'debug') -> None:
        self._log = log
        self._level = level

    def __enter__(self):
        self.__call__()
        
    def __exit__(self, *args, **kwargs): # type: ignore
        pass
            
    def __call__(self, *args: Any, **kwds: Any) -> Any:
        _log(self._log, level=self._level)

class Logger:

    def __init__(self, title: str | None = None) -> None:
        self._title = title
        self._log_func = _func_dec

    def log(self, log: str, level: str):
        if self._title:
            log = f"{self._title}: {log}"
        return _logger(log, level)

    def info(self, log: str):
        return self.log(log, 'info')
    
    def warning(self, log: str):
        return self.log(log, 'warning')
    
    def error(self, log: str):
        return self.log(log, 'error')
    
    def trace(self, log: str):
        return self.log(log, 'trace')
    
    def debug(self, log: str):
        return self.log(log, 'debug')

    @property
    def log_function(self):
        return self._log_func
