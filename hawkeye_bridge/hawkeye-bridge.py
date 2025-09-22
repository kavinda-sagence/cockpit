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
        """Start the message bridge in a separate thread"""
        self.logger.info("Starting message bridge...")

        if self.running:
            self.logger.warning("Bridge is already running")
            return
        
        self.running = True
        self.bridge_thread = threading.Thread(target=self._run_bridge, daemon=True)
        self.bridge_thread.start()
        self.logger.info("Bridge started")
    
    def stop(self):
        """Stop the message bridge"""
        self.logger.info("Stopping message bridge...")
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
        """Main message bridge loop - runs in separate thread"""
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
    
    def __init__(self, message_bridge: MessageBridge):
        self.logger = Logger("task-handler.log")
        
        self.message_bridge = message_bridge
        self.running = False
        self.task_thread: Optional[threading.Thread] = None
        self.inf_process = None

    def start_inference(self, configs: Dict[str, Any]):
        self.logger.info("Starting inference process...")

        if self.inf_process:
            warn_msg = "Inference process is already running"
            self.logger.warning(warn_msg)
            self.message_bridge.push_message('ntf', {'warning': warn_msg})
            return

        host_path = os.path.abspath('/home/analog/kavinda/sg_sw/sw_be/out_sw_be/aix/bin/deb64-x86_64/release/runtime/ai_host/')

        self.logger.info("Inference process started.")

        try:
            self.inf_process = InfProcess(host_path, configs)
        except Exception as e:
            err_msg = f"Failed to start inference process: {e}"
            self.logger.error(err_msg)
            self.message_bridge.push_message('ntf', {'error': err_msg})
            self.inf_process = None
            return

    def stop_inference(self):
        self.logger.info("Stopping inference process...")

        if not self.inf_process:
            warn_msg = "Inference process is not running"
            self.logger.warning(warn_msg)
            self.message_bridge.push_message('ntf', {'warning': warn_msg})
            return

        del self.inf_process
        self.inf_process = None
        
        self.logger.info("Inference process stopped.")

    def start(self):
        """Start the task handler in a separate thread"""
        self.logger.info("Starting task handler...")
        
        if self.running:
            self.logger.warning("Task handler is already running")
            return

        self.logger.info("Task handler started")

        self.running = True
        self.task_thread = threading.Thread(target=self._run_tasks, daemon=True)
        self.task_thread.start()
    
    def stop(self):
        """Stop the task handler"""
        self.logger.info("Stopping task handler...")

        self.running = False
        if self.task_thread:
            self.task_thread.join(timeout=2)

        self.logger.info("Task handler stopped")
    
    def _run_tasks(self):
        """Main task loop - runs in separate thread"""
        self.logger.info("Task handler thread started")
        
        try:
            while self.running:
                # Check if message bridge requested shutdown
                if self.message_bridge.is_shutdown_requested(): break
                
                # Process incoming messages
                message = self.message_bridge.pop_message(timeout=0.1)
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

        if 'command' == message_type:
            
            command = message_content.get('command', '')
            component = message_content.get('component', '')
            configs = message_content.get('configs', {})
            
            if 'inf_process' == component:
                if command == 'start':
                    self.start_inference(configs)
                elif command == 'stop':
                    self.stop_inference()
                else:
                    self.logger.warning(f"Unknown command: {command}")
            else:
                self.logger.warning(f"Unknown component: {component}")
                return
        
        else:
            self.logger.warning(f"Unknown message type: {message_type}")

        self.message_bridge.push_message('ack', None)

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

        hw_status = {}
        inf_process_status = {}

        temp_status = self._get_temps()
        if temp_status is not None:
            hw_status = {'temps': temp_status}

        if self.inf_process is not None:
            inf_process_status = self.inf_process.get_logs()

        status_message = {'hw' : hw_status, 'inf_pro': inf_process_status}
        self.message_bridge.push_message('status', status_message)


def main():
    ai_out_mute()
    ai_warn_mute() 
    ai_err_mute()

    # Create message bridge and task handler
    logger = Logger("main.log")
    message_bridge = MessageBridge()
    task_handler = TaskHandler(message_bridge)
    
    # Signal handler for graceful shutdown
    def signal_handler(signum: int, frame: Any) -> None:
        logger.info(f"Received signal {signum}, shutting down...")
        message_bridge.shutdown_requested = True
    
    # Register signal handlers
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    try:
        logger.info("Starting message bridge and task handler...")

        # Start both threads
        message_bridge.start()
        task_handler.start()

        logger.info("Message bridge and task handler started.")

        # Keep main thread alive and check for shutdown requests
        while not message_bridge.is_shutdown_requested():
            time.sleep(0.1)
            
        logger.info("Shutdown requested, stopping...")
            
    except KeyboardInterrupt:
        logger.info("\nKeyboardInterrupt received, stopping...")
    finally:
        logger.info("Stopping message bridge and task handler...")
        # Stop both threads
        task_handler.stop()
        message_bridge.stop()
        logger.info("Message bridge and task handler stopped.")
        sys.exit(0)


if __name__ == '__main__':
    main()
