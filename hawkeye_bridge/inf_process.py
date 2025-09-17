import os
import signal
import time
from typing import Dict, Any, Optional, IO
from abc import ABC, abstractmethod
import queue
import json
import threading
import subprocess
import numpy as np
from hawkeye_logger import Logger
from aix_endpoint import AixEndpoint


class HostProcess:
    def __init__(self, host_path: str, fw_path: str, num_streams: int):

        self.logger = Logger("host-process.log")
        self.logger.info(f"Starting Host process...")

        # Queues to store output
        self.stdout_lines: queue.Queue[str] = queue.Queue()
        self.stderr_lines: queue.Queue[str] = queue.Queue()

        # Get the script path
        run_script_path = os.path.join(host_path, "run.sh")

        # Start the process
        self.process = subprocess.Popen(
            ["bash", run_script_path, fw_path, str(num_streams)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line buffered
            universal_newlines=True,
            preexec_fn=os.setsid  # Create a new process group
        )

        # Give the process a moment to start and check if it failed immediately
        time.sleep(5)
        if self.process.poll() is not None:
            # Process has already ended, likely due to an error
            try:
                _, stderr = self.process.communicate(timeout=1)
                error_msg = f"Process failed to start. Exit code: {self.process.returncode}"
                if stderr:
                    error_msg += f", stderr: {stderr.strip()}"
                raise RuntimeError(error_msg)
            except subprocess.TimeoutExpired:
                raise RuntimeError("Process failed to start (timeout during error check)")
                
        # Create threads to read stdout and stderr
        self.stdout_thread = threading.Thread(
            target=self._read_output_stream, 
            args=(self.process.stdout, self.stdout_lines), 
            daemon=True
        )
        self.stderr_thread = threading.Thread(
            target=self._read_output_stream, 
            args=(self.process.stderr, self.stderr_lines), 
            daemon=True
        )
        
        # Start the reader threads
        self.stdout_thread.start()
        self.stderr_thread.start()

        self.logger.info(f"Host process started.")

    
    def __del__(self):
        # Check if process is still running
        if self.process.poll() is None:
            self.logger.info("Terminating process...")
            
            # Send SIGINT (Ctrl+C) to the process group
            os.killpg(os.getpgid(self.process.pid), signal.SIGINT)
            
            # Wait a bit for graceful shutdown
            try:
                self.process.wait(timeout=5)
                self.logger.info("Process terminated gracefully.")
            except subprocess.TimeoutExpired:
                self.logger.warning("Process didn't terminate gracefully, forcing kill...")
                os.killpg(os.getpgid(self.process.pid), signal.SIGKILL)
                self.process.wait()
                self.logger.warning("Process killed.")
        else:
            self.logger.warning("Process already stopped.")
        
        if hasattr(self, 'stdout_thread'):
            self.stdout_thread.join(timeout=2)
        if hasattr(self, 'stderr_thread'):
            self.stderr_thread.join(timeout=2)

        if 0 != self.process.returncode:
            self.logger.warning(f"Process stopped with errors. Exit code: {self.process.returncode}")

        # Convert queue to list to get size and iterate
        stdout_list: list[str] = []
        while not self.stdout_lines.empty():
            try:
                stdout_list.append(self.stdout_lines.get_nowait())
            except queue.Empty:
                break

        stderr_list: list[str] = []
        while not self.stderr_lines.empty():
            try:
                stderr_list.append(self.stderr_lines.get_nowait())
            except queue.Empty:
                break

        self.logger.info(f"Remaining stdout lines: {len(stdout_list)}")
        for stdout_line in stdout_list:
            self.logger.info(stdout_line)
        self.logger.info(f"Remaining stderr lines: {len(stderr_list)}")
        for stderr_line in stderr_list:
            self.logger.info(stderr_line)

    def IsAlive(self) -> bool:
        """Check if the process is still running"""
        return self.process.poll() is None

    def pop_stdout(self) -> Optional[str]:
        """Pop a line from stdout if available"""
        try:
            line = self.stdout_lines.get_nowait()
            self.logger.info(f'Popped stdout: {line}')
            return line
        except queue.Empty:
            return None
    
    def pop_stderr(self) -> Optional[str]:
        """Pop a line from stderr if available"""
        try:
            line = self.stderr_lines.get_nowait()
            self.logger.info(f'Popped stderr: {line}')
            return line
        except queue.Empty:
            return None

    @staticmethod
    def _read_output_stream(stream: IO[str], output_list: queue.Queue[str]) -> None:
        """Read from a stream and print in real-time."""
        try:
            for line in iter(stream.readline, ''):
                if line:
                    output_list.put(line.rstrip())
        except:
            pass


class AixChannel(ABC):
    def __init__(self, file_name: str, input_image_shape: tuple[tuple[int, int, int], ...], number_of_frames: int) -> None:
        self.file_name = file_name
        self.input_image_shape = input_image_shape
        self.number_of_frames = number_of_frames
        self.frames_transmitted = 0
        self.frames_received = 0

    @abstractmethod
    def capture(self) -> tuple[bool, list[np.ndarray[np.int8, Any]]]:
        pass

    @abstractmethod
    def show(self, inference: list[np.ndarray[np.float32, Any]]) -> None:
        pass


class AixChannelDummy(AixChannel):
    def __init__(self, file_name: str, input_image_shape: tuple[tuple[int, int, int], ...], number_of_frames: int) -> None:
        super().__init__(file_name, input_image_shape, number_of_frames)
        self.image_queue: queue.Queue[Any] = queue.Queue()
    
    def capture(self) -> tuple[bool, list[np.ndarray[np.int8, Any]]]:
        input_lst: list[np.ndarray[np.int8, Any]] = list()
        if(self.frames_transmitted >= self.number_of_frames):
            return False, input_lst
        for shape in self.input_image_shape:
            input_lst.append(((np.random.random(size=shape) * 255) - 128).astype(dtype=np.int8, order='C'))
        self.image_queue.put(input_lst)
        self.frames_transmitted += 1
        return True, input_lst
    
    def show(self, inference: list[np.ndarray[np.float32, Any]]) -> None:
        _ = self.image_queue.get()
        self.frames_received += 1


class Streamer():
    def __init__(self, input_image_shape: tuple[tuple[int, int, int], ...], stream_id: int, channel: AixChannel):

        self.logger = Logger(f"streamer_{stream_id}.log")
        self.logger.info(f"Initializing streamer {stream_id}...")

        self.input_image_shape = input_image_shape
        self.stream_id = stream_id
        self.channel = channel

        self.frames_transmitted = 0
        self.frames_received = 0
        self.num_frames = channel.number_of_frames

        self.status_messages: queue.Queue[str] = queue.Queue()
        self.error_messages: queue.Queue[str] = queue.Queue()

        self.endpoint = AixEndpoint(self.stream_id, self.input_image_shape)

        self.running = True
        self.thread = threading.Thread(target=self._stream, daemon=True)
        self.thread.start()

        self.logger.info(f"Streamer {self.stream_id} initialized successfully.")

    def is_alive(self) -> bool:
        return self.thread.is_alive()

    def __del__(self):
        self.logger.info(f"Destroying streamer {self.stream_id}...")

        self.running = False
        self.thread.join(timeout=2)

        self.logger.info(f"Streamer {self.stream_id} destroyed.")

    def pop_status_message(self) -> Optional[str]:
        try:
            return self.status_messages.get_nowait()
        except queue.Empty:
            return None
    
    def pop_error_message(self) -> Optional[str]:
        try:
            return self.error_messages.get_nowait()
        except queue.Empty:
            return None

    def _stream(self):
        try:
            self.status_messages.put(f"Frame streaming started.")

            while True:

                if not self.endpoint.compute():
                    raise RuntimeError("Endpoint compute failed")

                if self.running == False: break

                if self.endpoint.ready_to_set():
                    stat, image = self.channel.capture()
                    if stat:
                        self.endpoint.set(image)
                        self.frames_transmitted += 1
                        # self.status_messages.put(f"Transmitted frame {frames_transmitted}")
                    elif(self.frames_received == self.frames_transmitted):
                        # If the video stream finished, -
                        # wait for the results of the final transmitted frame to be received.
                        break

                if self.endpoint.ready_to_get():
                    inference = self.endpoint.get()
                    self.channel.show(inference)
                    self.frames_received += 1
                    # self.status_messages.put(f"Received frame {frames_received}")

            self.status_messages.put(f"Frame streaming stopped.")
        except Exception as e:
            self.error_messages.put(str(e))
            self.logger.error(str(e))


class InfProcess:
    def __init__(self, host_path: str, fw_path: str, num_streams: int, configs: Dict[str, Any]):
        """Initialize and start the host process and streamers"""
        
        self.logger = Logger("inf-process.log")
        self.logger.info("Starting InfProcess...")
        
        try:
            self.host_process = HostProcess(host_path, fw_path, num_streams)
        except Exception as e:
            raise RuntimeError(f"Failed to start host process: {e}")

        try:
            number_of_frames = configs.get('num_frames', 0)
            input_image_shape = self._get_input_image_shape(fw_path)
            self.channel = AixChannelDummy("", input_image_shape, number_of_frames)
            self.streamers = [Streamer(input_image_shape, i, self.channel) for i in range(num_streams)]
        except Exception as e:
            del self.host_process
            raise RuntimeError(f"Failed to initialize streamers: {e}")

        self.logger.info("InfProcess started successfully.")


    def __del__(self):
        self.logger.info("Destroying InfProcess...")
        self.logger.info("InfProcess destroyed.")

    def IsHostAlive(self) -> bool:
        """Check if the host process is still running"""
        return self.host_process.IsAlive()

    def get_logs(self) -> Dict[str, Any]:
        """Get available logs from host process and streamers"""
        max_num_lines = 100        
    
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
    
        while True:
            line = self.host_process.pop_stdout()
            if line is None or len(stdout_lines) >= max_num_lines: break
            stdout_lines.append(line)
        
        while True:
            line = self.host_process.pop_stderr()
            if line is None or len(stderr_lines) >= max_num_lines: break
            stderr_lines.append(line)
        
        host_status = {
                'stdout': stdout_lines, 'stderr': stderr_lines, 'running': self.host_process.process.poll() is None,
                'exit_code': self.host_process.process.returncode
        }

        streamer_status = {}

        for streamer in self.streamers:
            
            status_msgs: list[str] = []
            error_msgs: list[str] = []
            
            while True:
                msg = streamer.pop_status_message()
                if msg is None or len(status_msgs) >= max_num_lines: break
                status_msgs.append(msg)
            
            while True:
                msg = streamer.pop_error_message()
                if msg is None or len(error_msgs) >= max_num_lines: break
                error_msgs.append(msg)

            streamer_status[str(streamer.stream_id)] = {
                'alive': streamer.is_alive(),
                'num_frames': streamer.num_frames,
                'frames_transmitted': streamer.frames_transmitted,
                'frames_received': streamer.frames_received,
                'status': status_msgs,
                'errors': error_msgs
            }

        return {
            'host': host_status,
            'streamers': streamer_status
        }

    def _get_input_image_shape(self, test_dir_path: str) -> tuple[tuple[int, int, int], ...]:

        test_config_file_path = os.path.join(test_dir_path, 'ai_fw', 'test_config.json')

        # Open and read the JSON file
        with open(test_config_file_path, 'r') as file:
            data = json.load(file)

        dest_ids: set[int] = set()

        for output_layer_inf in data['outputs']:
            dest_ids.add(output_layer_inf['dest_id'][0])

        input_image_shape: list[tuple[int, int, int]] = list()

        for input_layer_inf in data['inputs']:

            if "inp_id" in input_layer_inf:
                inp_id: int = input_layer_inf["inp_id"][0]
                if(inp_id in dest_ids): continue

            input_image_shape.append((
                input_layer_inf['num_in_rows'], 
                input_layer_inf['num_in_cols'], 
                input_layer_inf['num_in_filters']
            ))

        return tuple(input_image_shape)

