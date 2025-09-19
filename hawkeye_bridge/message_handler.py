from abc import ABC
from typing import Optional
import queue
from hawkeye_logger import Logger

class MessageQueueHandler(ABC):
    def __init__(self, logger: Logger) -> None:
        super().__init__()
        
        self.logger = logger
        self._status_messages: queue.Queue[str] = queue.Queue()
        self._error_messages: queue.Queue[str] = queue.Queue()
    
    def put_status_message(self, message: str) -> None:
        """Put a line into status messages"""
        self.logger.info(message)
        self._status_messages.put(message)
    
    def put_error_message(self, message: str) -> None:
        """Put a line into error messages"""
        self.logger.error(message)
        self._error_messages.put(message)

    def pop_status_message(self) -> Optional[str]:
        """Pop a line from status messages if available"""
        try:
            return self._status_messages.get_nowait()
        except queue.Empty:
            return None
    
    def pop_error_message(self) -> Optional[str]:
        """Pop a line from error messages if available"""
        try:
            return self._error_messages.get_nowait()
        except queue.Empty:
            return None

    def get_messages(self, max_num_lines: int) -> tuple[list[str], list[str]]:
        """Get available status and error messages up to max_num_lines each"""

        status_msgs: list[str] = []
        error_msgs: list[str] = []

        while True:
            msg = self.pop_status_message()
            if msg is None or len(status_msgs) >= max_num_lines: break
            status_msgs.append(msg)

        while True:
            msg = self.pop_error_message()
            if msg is None or len(error_msgs) >= max_num_lines: break
            error_msgs.append(msg)

        return status_msgs, error_msgs
