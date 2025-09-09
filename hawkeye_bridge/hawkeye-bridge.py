#!/usr/bin/env python3

import sys
import json
import os
import logging
import signal
from typing import Dict, Any, Optional
from threading import Thread
import queue
import time
import select


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
        
        self.bridge_thread: Optional[Thread] = None
    
    def start(self):
        """Start the bridge in a separate thread"""
        if self.running:
            self.logger.warning("Bridge is already running")
            return
        
        self.running = True
        self.bridge_thread = Thread(target=self._run_bridge, daemon=True)
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


class TaskHandler:
    """Handles application tasks in a separate thread"""
    
    def __init__(self, bridge: MessageBridge):
        self.bridge = bridge
        self.running = False
        self.logger = Logger("task-handler.log")
        self.task_thread: Optional[Thread] = None
    
    def start(self):
        """Start the task handler in a separate thread"""
        if self.running:
            self.logger.warning("Task handler is already running")
            return
        
        self.running = True
        self.task_thread = Thread(target=self._run_tasks, daemon=True)
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
                
                self._send_status()
                
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

        self.bridge.push_message('ack', {'message_type' : message_type, 'message_content' : message_content})

    def _send_status(self):
        """Send status every 10 seconds"""
        status_interval = 10
        if hasattr(self, '_last_status'):
            if time.time() - self._last_status > status_interval:
                self.bridge.push_message('status', 'Task handler alive')
                self._last_status = time.time()
        else:
            self._last_status = time.time()


def main():
    """Simple main function"""
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
