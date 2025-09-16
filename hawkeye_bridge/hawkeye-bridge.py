#!/usr/bin/env python3

import sys, os
import signal
from typing import Dict, Any, Optional, IO
from abc import ABC, abstractmethod
import json
import logging
import threading
import subprocess
import queue
import time
import select
import numpy as np
from aix_endpoint import AixEndpoint, HostInfoStruct, get_host_info, ai_out_mute, ai_warn_mute, ai_err_mute


class Logger:
    def __init__(self, log_file_name: str, recreate_file: bool = True):
        """Initialize logger with file in same directory as the script"""
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_file_path = os.path.join(script_dir, log_file_name)
        
        if recreate_file and os.path.exists(self.log_file_path):
            os.remove(self.log_file_path)
        
        # Create a unique logger name based on the log file name
        logger_name = f"logger_{log_file_name.replace('.', '_').replace('-', '_')}"
        self.logger = logging.getLogger(logger_name)
        
        # Remove any existing handlers to avoid duplicates
        self.logger.handlers.clear()
        
        # Set the logger level
        self.logger.setLevel(logging.INFO)
        
        # Create file handler for this specific logger
        file_handler = logging.FileHandler(self.log_file_path)
        file_handler.setLevel(logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        
        # Add handler to logger
        self.logger.addHandler(file_handler)
        
        # Prevent propagation to root logger to avoid duplicate logs
        self.logger.propagate = False
    
    def info(self, message: str) -> None:
        self.logger.info(message)
    
    def error(self, message: str) -> None:
        self.logger.error(message)
    
    def warning(self, message: str) -> None:
        self.logger.warning(message)


class MessageBridge:
    """Bridge that handles stdin/stdout in a separate thread"""
    
    def __init__(self):
        self.logger = Logger("message-bridge.log")

        self.running = False
        self.shutdown_requested = False
        
        # Thread-safe queues for communication
        self.incoming_queue: queue.Queue[Dict[str, Any]] = queue.Queue()
        self.outgoing_queue: queue.Queue[Dict[str, Any]] = queue.Queue()

        self.bridge_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the bridge in a separate thread"""
        self.logger.info("Starting bridge...")

        if self.running:
            self.logger.warning("Bridge is already running")
            return
        
        self.running = True
        self.bridge_thread = threading.Thread(target=self._run_bridge, daemon=True)
        self.bridge_thread.start()
        self.logger.info("Bridge started")
    
    def stop(self):
        """Stop the bridge"""
        self.logger.info("Stopping bridge...")
        self.running = False
        if self.bridge_thread:
            self.bridge_thread.join(timeout=2)
        self.logger.info("Bridge stopped")
    
    def push_message(self, type: str, data: Any):
        """Push message to send (thread-safe)"""
        msg = {'type': type, 'data': data}
        self.outgoing_queue.put(msg)
    
    def pop_message(self, timeout: float = 0.1) -> Optional[Dict[str, Any]]:
        """Pop received message (thread-safe)"""
        try:
            return self.incoming_queue.get(timeout=timeout)
        except queue.Empty:
            return None
    
    def is_shutdown_requested(self) -> bool:
        """Check if shutdown has been requested"""
        return self.shutdown_requested
    
    def _run_bridge(self):
        """Main bridge loop - runs in separate thread"""
        self.logger.info("Bridge thread started")
        
        try:
            while self.running:
                # Handle outgoing messages
                try:
                    msg = self.outgoing_queue.get(timeout=0.1)
                    data = json.dumps(msg) + '\n'
                    sys.stdout.write(data)
                    sys.stdout.flush()
                    self.logger.info(f"Sent: {msg}")
                except queue.Empty:
                    pass
                except Exception as e:
                    self.logger.error(f"Error sending message: {e}")
                
                # Handle incoming messages (non-blocking check)
                try:
                    # Use select to check if stdin has data available (Unix/Linux)
                    if select.select([sys.stdin], [], [], 0.01)[0]:
                        line = sys.stdin.readline()
                        if not line:  # Empty string means stdin was closed
                            self.logger.info("stdin closed, requesting shutdown")
                            self.shutdown_requested = True
                            break
                        if line.strip():
                            message = json.loads(line.strip())
                            self.incoming_queue.put(message)
                            self.logger.info(f"Received: {message}")
                except json.JSONDecodeError as e:
                    self.logger.error(f"JSON decode error: {e}")
                except Exception as e:
                    self.logger.error(f"Error reading stdin: {e}")
                    # If we can't read from stdin, assume it's closed
                    self.logger.info("stdin error, requesting shutdown")
                    self.shutdown_requested = True
                    break
                
                # Small delay to prevent busy waiting
                time.sleep(0.01)
                
        except Exception as e:
            self.logger.error(f"Bridge thread error: {e}")
        finally:
            self.logger.info("Bridge thread ended")


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
        else:
            self.logger.info("Process stopped successfully.")
        
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


def get_input_image_shape(test_dir_path: str) -> tuple[tuple[int, int, int], ...]:

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


class AixChannel(ABC):
    def __init__(self, file_name: str, input_image_shape: tuple[tuple[int, int, int], ...], number_of_frames: int) -> None:
        self.file_name = file_name
        self.input_image_shape = input_image_shape
        self.number_of_frames = number_of_frames
        self.frames_transmitted = 0
        self.frames_received = 0

    @abstractmethod
    def capture(self, q_val: float) -> tuple[bool, list[np.ndarray[np.int8, Any]]]:
        pass

    @abstractmethod
    def show(self, inference: list[np.ndarray[np.float32, Any]]) -> None:
        pass


class AixChannelDummy(AixChannel):
    def __init__(self, file_name: str, input_image_shape: tuple[tuple[int, int, int], ...], number_of_frames: int) -> None:
        super().__init__(file_name, input_image_shape, number_of_frames)
        self.image_queue: queue.Queue[Any] = queue.Queue()
    
    def capture(self, q_val: float) -> tuple[bool, list[np.ndarray[np.int8, Any]]]:
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
    def __init__(self, fw_path: str, stream_id: int, channel: AixChannel):

        self.logger = Logger(f"streamer_{stream_id}.log")
        self.logger.info(f"Initializing streamer {stream_id}...")

        self.input_image_shape = get_input_image_shape(fw_path)
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

        q_val = 0.5

        self.status_messages.put(f"Frame streaming started.")

        while self.endpoint.compute():

            if self.running == False: break

            if self.endpoint.ready_to_set():
                stat, image = self.channel.capture(q_val)
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


class InfProcess:
    def __init__(self, host_path: str, fw_path: str, num_streams: int):
        """Initialize and start the host process and streamers"""
        
        self.logger = Logger("inf-process.log")
        self.logger.info("Starting InfProcess...")
        
        try:
            self.host_process = HostProcess(host_path, fw_path, num_streams)
        except Exception as e:
            raise RuntimeError(f"Failed to start host process: {e}")

        try:
            number_of_frames=100000000
            input_image_shape = get_input_image_shape(fw_path)
            self.channel = AixChannelDummy("", input_image_shape, number_of_frames)
            self.streamers = [Streamer(fw_path, i, self.channel) for i in range(num_streams)]
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


class TaskHandler:
    """Handles application tasks in a separate thread"""
    
    def __init__(self, bridge: MessageBridge):
        self.logger = Logger("task-handler.log")
        
        self.bridge = bridge
        self.running = False
        self.task_thread: Optional[threading.Thread] = None
        self.inf_process = None

    def start_inference(self):
        if self.inf_process:
            self.logger.warning("Inference process is already running")
            return

        host_path = os.path.abspath('/home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/out_runtime_test_app/aix/bin/deb64-x86_64/release/runtime/ai_host/')
        fw_path = os.path.abspath('/home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/test_data/no_op/')
        num_streams = 1

        # send notification to front-end
        try:
            self.inf_process = InfProcess(host_path, fw_path, num_streams)
        except Exception as e:
            self.logger.error(f"Failed to start inference process: {e}")
            # send notification to front-end
            self.inf_process = None
            return

    def stop_inference(self):
        if not self.inf_process:
            self.logger.warning("Inference process is not running")
            return

        del self.inf_process
        self.inf_process = None

    def start(self):
        """Start the task handler in a separate thread"""
        if self.running:
            self.logger.warning("Task handler is already running")
            return
        
        self.logger.info("Task handler started")
        
        self.running = True
        self.task_thread = threading.Thread(target=self._run_tasks, daemon=True)
        self.task_thread.start()
    
    def stop(self):
        """Stop the task handler"""
        self.running = False
        if self.task_thread:
            self.task_thread.join(timeout=2)
        self.logger.info("Task handler stopped")
    
    def _run_tasks(self):
        """Main task loop - runs in separate thread"""
        self.logger.info("Task handler thread started")
        
        try:
            while self.running:
                # Check if bridge requested shutdown
                if self.bridge.is_shutdown_requested(): break
                
                # Process incoming messages
                message = self.bridge.pop_message(timeout=0.1)
                if message:
                    self._handle_message(message)
                
                # Send status every 3 seconds
                status_interval = 3
                if hasattr(self, '_last_status'):
                    if time.time() - self._last_status > status_interval:
                        self._send_status()
                        self._last_status = time.time()
                else:
                    self._last_status = time.time()
                
                # Small delay
                time.sleep(0.01)
                
        except Exception as e:
            self.logger.error(f"Task handler error: {e}")
        finally:
            self.logger.info("Task handler thread ended")
    
    def _handle_message(self, message: Dict[str, Any]):
        """Handle incoming messages"""
        message_type = message.get('type', 'unknown')
        message_content = message.get('data', '')

        self.logger.info(f"Handling message: {message}")

        if self.inf_process is None:
            self.logger.info("Starting inference process...")
            self.start_inference()
            self.logger.info("Inference process started.")
        elif not self.inf_process.IsHostAlive():
            self.logger.error("Host process has stopped unexpectedly, restarting...")
            # send notification to front-end
            self.stop_inference()
            self.start_inference()
            self.logger.info("Inference process restarted.")
        else:
            self.logger.info("Stopping inference process...")
            self.stop_inference()
            self.logger.info("Inference process stopped.")

        self.bridge.push_message('ack', {'message_type' : message_type, 'message_content' : message_content})

    def _get_temps(self) -> Optional[Dict[str, float]]:
        """Get temperature readings from host"""
        try:
            host_info_struct: HostInfoStruct = get_host_info()
            temp_status: dict[str, float] = {
                'iope_temperature': host_info_struct.iope_temperature,
                'sub_array_0_temperature': host_info_struct.sub_array_0_temperature,
                'sub_array_1_temperature': host_info_struct.sub_array_1_temperature,
                'sub_array_2_temperature': host_info_struct.sub_array_2_temperature,
                'sub_array_3_temperature': host_info_struct.sub_array_3_temperature
            }
            return temp_status
        except Exception as e:
            self.logger.warning(f"Unable to get host info: {e}")
            return None

    def _send_status(self):
        """Send status messages periodically"""

        temp_status = self._get_temps()
        if temp_status is not None:
            hw_status = {'temps': temp_status}
        else:
            hw_status = {}

        if self.inf_process is None:
            inf_process_status = {}
        else:
            inf_process_status = self.inf_process.get_logs()

        status_message = {'hw' : hw_status, 'inf_pro': inf_process_status}

        self.bridge.push_message('status', status_message)


def main():
    ai_out_mute()
    ai_warn_mute() 
    ai_err_mute()

    # Create bridge and task handler
    logger = Logger("main.log")
    bridge = MessageBridge()
    task_handler = TaskHandler(bridge)
    
    # Signal handler for graceful shutdown
    def signal_handler(signum: int, frame: Any) -> None:
        logger.info(f"Received signal {signum}, shutting down...")
        bridge.shutdown_requested = True
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        logger.info("Starting bridge and task handler...")

        # Start both threads
        bridge.start()
        task_handler.start()

        logger.info("Bridge and task handler started.")

        # Keep main thread alive and check for shutdown requests
        while not bridge.is_shutdown_requested():
            time.sleep(0.1)
            
        logger.info("Shutdown requested, stopping...")
            
    except KeyboardInterrupt:
        logger.info("\nKeyboardInterrupt received, stopping...")
    finally:
        logger.info("Stopping bridge and task handler...")
        # Stop both threads
        task_handler.stop()
        bridge.stop()
        logger.info("Bridge and task handler stopped.")
        sys.exit(0)


if __name__ == '__main__':
    main()
