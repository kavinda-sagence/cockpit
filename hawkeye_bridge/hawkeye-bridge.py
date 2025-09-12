#!/usr/bin/env python3

import sys, os
import signal
import json
import logging
from typing import Dict, Any, Optional, IO
import threading
import subprocess
import queue
import time
import select


aix_endpoint_lib_path = os.path.abspath("/home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/out_runtime_test_app/aix/bin/deb64-x86_64/release/streamer/aix_endpoint")
sys.path.append(aix_endpoint_lib_path)

try:
    from aix_endpoint import HostInfoStruct, get_host_info, ai_out_mute, ai_warn_mute, ai_err_mute
except ImportError:
    # Define stub types/functions for IntelliSense when module is not available
    class HostInfoStruct:
        def __init__(self):
            self.iope_temperature: float = 0.0
            self.sub_array_0_temperature: float = 0.0
            self.sub_array_1_temperature: float = 0.0
            self.sub_array_2_temperature: float = 0.0
            self.sub_array_3_temperature: float = 0.0
    
    def get_host_info() -> HostInfoStruct:
        return HostInfoStruct()
    
    def ai_out_mute() -> None:
        pass
    
    def ai_warn_mute() -> None:
        pass
    
    def ai_err_mute() -> None:
        pass


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
        self.running = False
        self.shutdown_requested = False
        self.logger = Logger("message-bridge.log")
        
        # Thread-safe queues for communication
        self.incoming_queue: queue.Queue[Dict[str, Any]] = queue.Queue()
        self.outgoing_queue: queue.Queue[Dict[str, Any]] = queue.Queue()

        self.bridge_thread: Optional[threading.Thread] = None

    def start(self):
        """Start the bridge in a separate thread"""
        if self.running:
            self.logger.warning("Bridge is already running")
            return
        
        self.running = True
        self.bridge_thread = threading.Thread(target=self._run_bridge, daemon=True)
        self.bridge_thread.start()
        self.logger.info("Bridge started")
    
    def stop(self):
        """Stop the bridge"""
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

        # Queues to store output
        self.stdout_lines: queue.Queue[str] = queue.Queue()
        self.stderr_lines: queue.Queue[str] = queue.Queue()

        # Get the script path
        run_script_path = os.path.join(host_path, "run.sh")

        self.logger.info(f"Starting {run_script_path}...")

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


class TaskHandler:
    """Handles application tasks in a separate thread"""
    
    def __init__(self, bridge: MessageBridge):
        self.bridge = bridge
        self.running = False
        self.logger = Logger("task-handler.log")
        self.task_thread: Optional[threading.Thread] = None
        self.host_process = None

    def start_host_process(self):
        if self.host_process:
            self.logger.warning("Host process is already running")
            return

        host_path = os.path.abspath('/home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/out_runtime_test_app/aix/bin/deb64-x86_64/release/runtime/ai_host/')
        fw_path = os.path.abspath('/home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/test_data/no_op/')
        num_streams = 1

        # send notification to front-end
        try:
            self.host_process = HostProcess(host_path, fw_path, num_streams)
        except Exception as e:
            self.logger.error(f"Failed to start host process: {e}")
            # send notification to front-end
            self.host_process = None
            return

    def stop_host_process(self):
        if not self.host_process:
            self.logger.warning("Host process is not running")
            return

        del self.host_process
        self.host_process = None

    def start(self):
        """Start the task handler in a separate thread"""
        if self.running:
            self.logger.warning("Task handler is already running")
            return
        
        self.running = True
        self.task_thread = threading.Thread(target=self._run_tasks, daemon=True)
        self.task_thread.start()
        self.logger.info("Task handler started")
    
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
                if self.bridge.is_shutdown_requested():
                    self.logger.info("Shutdown requested by bridge, stopping task handler")
                    break
                
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

        if self.host_process is None:
            self.start_host_process()
        elif not self.host_process.IsAlive():
            self.logger.error("Host process has stopped unexpectedly, restarting...")
            # send notification to front-end
            self.stop_host_process()
            self.start_host_process()
        else:
            self.stop_host_process()

        self.bridge.push_message('ack', {'message_type' : message_type, 'message_content' : message_content})

    def _send_status(self):
        """Send status messages periodically"""
        try:
            host_info_struct: HostInfoStruct = get_host_info()
            temp_status: dict[str, float] = {
                'iope_temperature': host_info_struct.iope_temperature,
                'sub_array_0_temperature': host_info_struct.sub_array_0_temperature,
                'sub_array_1_temperature': host_info_struct.sub_array_1_temperature,
                'sub_array_2_temperature': host_info_struct.sub_array_2_temperature,
                'sub_array_3_temperature': host_info_struct.sub_array_3_temperature
            }
        except Exception as e:
            temp_status = {}
            self.logger.warning(f"Unable to get host info: {e}")

        hw_status = {'temps': temp_status}

        max_lines = 100

        # pop available stdout and stderr lines
        stdout_lines: list[str] = []
        stderr_lines: list[str] = []
        
        while True:
        
            if self.host_process is None:
                break
            line = self.host_process.pop_stdout()
        
            if line is None or len(stdout_lines) >= max_lines:
                break
        
            stdout_lines.append(line)

        
        while True:
            if self.host_process is None:
                break

            line = self.host_process.pop_stderr()
            
            if line is None or len(stderr_lines) >= max_lines:
                break
            
            stderr_lines.append(line)

        if self.host_process is None:
            host_status = {
                'running': False,
                'exit_code': None,
                'stdout': stdout_lines,
                'stderr': stderr_lines
            }
        else:
            host_status = {
                'running': self.host_process.process.poll() is None,
                'exit_code': self.host_process.process.returncode,
                'stdout': stdout_lines,
                'stderr': stderr_lines
            }

        status_message = {'hw' : hw_status, 'host': host_status}

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
        # Stop both threads
        task_handler.stop()
        bridge.stop()
        logger.info("Stopped.")
        sys.exit(0)


if __name__ == '__main__':
    main()
