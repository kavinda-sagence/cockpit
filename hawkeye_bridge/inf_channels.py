import os
from abc import ABC, abstractmethod
from typing import Any
import queue
import numpy as np
import cv2
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


class CameraChannel(SrcChannel):
    def __init__(self, stream_id: int, configs: dict[str, Any]) -> None:
        super().__init__(stream_id, configs)
        
        self.q_val: float = 0.5
        self.input_image_shape: tuple[tuple[int, int, int], ...] = configs['input_image_shape']
        self.address: str = configs['address']
        
        self.cap = cv2.VideoCapture(self.address)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open camera stream: {self.address}")
        
        self.put_status_message(f"Camera stream opened: {self.address}")

    def __del__(self) -> None:
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()
        
        self.put_status_message("Camera stream released")

    def capture(self) -> tuple[bool, list[np.ndarray[np.int8, Any]]]:
        
        input_lst: list[np.ndarray[np.int8, Any]] = list()

        if(self.frames_transmitted >= self.number_of_frames):
            return False, input_lst

        stat, image = self.cap.read()
        self.image_queue.put(image)

        resized_image = cv2.resize(image, (self.input_image_shape[0][1], self.input_image_shape[0][0]))
        qt_image = cv2.convertScaleAbs(resized_image, alpha=self.q_val).astype(np.int8)

        self.frames_transmitted += 1
        self.put_status_message(f"Frame {self.frames_transmitted} captured")

        return stat, [qt_image]


class VideoReaderChannel(SrcChannel):
    def __init__(self, stream_id: int, configs: dict[str, Any]) -> None:
        super().__init__(stream_id, configs)
        
        self.q_val: float = 0.5
        self.input_image_shape: tuple[tuple[int, int, int], ...] = configs['input_image_shape']
        self.video_path: str = configs['video_path']
        
        if not os.path.exists(self.video_path):
            raise FileNotFoundError(f"Video file not found: {self.video_path}")
        
        self.cap = cv2.VideoCapture(self.video_path)
        if not self.cap.isOpened():
            raise RuntimeError(f"Failed to open video file: {self.video_path}")
        
        self.put_status_message(f"Video file opened: {self.video_path}")

    def __del__(self) -> None:
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()
        
        self.put_status_message("Video file released")

    def capture(self) -> tuple[bool, list[np.ndarray[np.int8, Any]]]:
        
        input_lst: list[np.ndarray[np.int8, Any]] = list()

        if self.frames_transmitted >= self.number_of_frames:
            return False, input_lst

        stat, image = self.cap.read()
        self.image_queue.put(image)

        resized_image = cv2.resize(image, (self.input_image_shape[0][1], self.input_image_shape[0][0]))
        qt_image = cv2.convertScaleAbs(resized_image, alpha=self.q_val).astype(np.int8)

        self.frames_transmitted += 1
        self.put_status_message(f"Frame {self.frames_transmitted} captured")

        return stat, [qt_image]


class NoOpChannel(DestChannel):
    def __init__(self, stream_id: int, configs: dict[str, Any], src_channel: SrcChannel) -> None:
        super().__init__(stream_id, configs, src_channel)

    def show(self, inference: list[np.ndarray[np.float32, Any]]) -> None:
        _ = self.image_queue.get()

        self.frames_received += 1
        self.put_status_message(f"Frame {self.frames_received} received")


class ImageWriterChannel(DestChannel):
    def __init__(self, stream_id: int, configs: dict[str, Any], src_channel: SrcChannel) -> None:
        super().__init__(stream_id, configs, src_channel)

        self.output_path: str = configs['output_path']
        if not self.output_path.endswith('/'):
            self.output_path += '/'
        
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
            self.put_status_message(f"Output directory created: {self.output_path}")
        else:
            self.put_status_message(f"Output directory exists: {self.output_path}")

    def show(self, inference: list[np.ndarray[np.float32, Any]]) -> None:
        _ = self.image_queue.get()

        for i, arr in enumerate(inference):
            output_file = f"{self.output_path}frame_{self.frames_received}_{i}.png"
            cv2.imwrite(output_file, arr)

        self.frames_received += 1
        self.put_status_message(f"Frame {self.frames_received} written to {self.output_path}")


class TxtWriterChannel(DestChannel):
    def __init__(self, stream_id: int, configs: dict[str, Any], src_channel: SrcChannel) -> None:
        super().__init__(stream_id, configs, src_channel)

        self.output_path: str = configs['output_path']
        if not self.output_path.endswith('/'):
            self.output_path += '/'
        
        if not os.path.exists(self.output_path):
            os.makedirs(self.output_path)
            self.put_status_message(f"Output directory created: {self.output_path}")
        else:
            self.put_status_message(f"Output directory exists: {self.output_path}")

    def show(self, inference: list[np.ndarray[np.float32, Any]]) -> None:
        _ = self.image_queue.get()

        for i, arr in enumerate(inference):
            output_file = f"{self.output_path}frame_{self.frames_received}_{i}.txt"
            with open(output_file, 'w') as f:
                arr_2d = arr.reshape(arr.shape[0], -1)
                for row in arr_2d:
                    f.write(' '.join(map(str, row)))
                    f.write('\n')

        self.frames_received += 1
        self.put_status_message(f"Frame {self.frames_received} written to {self.output_path}")
