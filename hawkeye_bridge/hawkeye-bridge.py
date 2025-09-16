#!/usr/bin/env python3

import sys, os
import signal
from typing import Dict, Any, Optional
import json
import threading
import queue
import time
import select
from hawkeye_logger import Logger
from inf_process import InfProcess
from aix_endpoint import HostInfoStruct, get_host_info, ai_out_mute, ai_warn_mute, ai_err_mute


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
