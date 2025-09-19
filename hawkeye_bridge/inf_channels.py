from abc import ABC, abstractmethod
from typing import Any
import queue
import numpy as np
from hawkeye_logger import Logger
from message_handler import MessageQueueHandler


class SrcChannel(MessageQueueHandler, ABC):
    def __init__(self, stream_id:int, configs: dict[str, Any]) -> None:

        self.logger = Logger(f"streamer-{stream_id}-src.log")

        super().__init__(self.logger)

        self.configs = configs
        self.frames_transmitted = 0
        self.number_of_frames = configs.get('number_of_frames', -1)
        self.image_queue: queue.Queue[Any] = queue.Queue()

        self.logger.info(f"Source channel initialized.")

    def __del__(self) -> None:
        self.logger.info("Source channel is being deleted")

    @abstractmethod
    def capture(self) -> tuple[bool, list[np.ndarray[np.int8, Any]]]:
        pass


class DestChannel(MessageQueueHandler, ABC):
    def __init__(self, stream_id:int, configs: dict[str, Any], src_channel: SrcChannel) -> None:
        self.logger = Logger(f"streamer-{stream_id}-dest.log")

        super().__init__(self.logger)

        self.configs = configs
        self.frames_received = 0
        self.image_queue = src_channel.image_queue

        self.logger.info(f"Destination channel initialized.")
    
    def __del__(self) -> None:
        self.logger.info("Destination channel is being deleted")

    @abstractmethod
    def show(self, inference: list[np.ndarray[np.float32, Any]]) -> None:
        pass


class RandGenChannel(SrcChannel):
    def __init__(self, stream_id: int, configs: dict[str, Any]) -> None:
        super().__init__(stream_id, configs)

        if self.number_of_frames < 0:
            raise ValueError("Number of frames must be a positive integer")

        self.input_image_shape: tuple[tuple[int, int, int], ...] = configs['input_image_shape']

    def capture(self) -> tuple[bool, list[np.ndarray[np.int8, Any]]]:
        input_lst: list[np.ndarray[np.int8, Any]] = list()
        
        if(self.frames_transmitted >= self.number_of_frames):
            return False, input_lst
        
        for shape in self.input_image_shape:
            input_lst.append(((np.random.random(size=shape) * 255) - 128).astype(dtype=np.int8, order='C'))
        
        self.image_queue.put(input_lst)
        
        self.frames_transmitted += 1
        self.put_status_message(f"Frame {self.frames_transmitted} captured")

        return True, input_lst


class NoOpChannel(DestChannel):
    def __init__(self, stream_id: int, configs: dict[str, Any], src_channel: SrcChannel) -> None:
        super().__init__(stream_id, configs, src_channel)

    def show(self, inference: list[np.ndarray[np.float32, Any]]) -> None:
        _ = self.image_queue.get()

        self.frames_received += 1
        self.put_status_message(f"Frame {self.frames_received} received")
