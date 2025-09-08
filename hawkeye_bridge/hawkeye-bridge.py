#!/usr/bin/env python3

import sys
import json
import asyncio
import os
import logging
from datetime import datetime
from typing import Dict, Any


class Logger:
    def __init__(self, log_file_name: str = "hawkeye-bridge.log", recreate_file: bool = False):
        """Initialize logger with file in same directory as the script
        
        Args:
            log_file_name: Name of the log file
            recreate_file: If True, removes existing log file before creating new one
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        self.log_file_path = os.path.join(script_dir, log_file_name)
        
        # Remove existing log file if recreate_file is True
        if recreate_file and os.path.exists(self.log_file_path):
            os.remove(self.log_file_path)
        
        # Configure logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(self.log_file_path)
            ]
        )
        self.logger = logging.getLogger(__name__)
    
    def info(self, message: str) -> None:
        """Log info message"""
        self.logger.info(message)
    
    def error(self, message: str) -> None:
        """Log error message"""
        self.logger.error(message)
    
    def warning(self, message: str) -> None:
        """Log warning message"""
        self.logger.warning(message)
    
    def debug(self, message: str) -> None:
        """Log debug message"""
        self.logger.debug(message)
    
    def critical(self, message: str) -> None:
        """Log critical message"""
        self.logger.critical(message)
    
    def log_with_timestamp(self, level: str, message: str) -> None:
        """Log message with custom timestamp"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"
        
        if level.lower() == 'info':
            self.info(formatted_message)
        elif level.lower() == 'error':
            self.error(formatted_message)
        elif level.lower() == 'warning':
            self.warning(formatted_message)
        elif level.lower() == 'debug':
            self.debug(formatted_message)
        elif level.lower() == 'critical':
            self.critical(formatted_message)
        else:
            self.info(formatted_message)


class HawkeyeBridge:
    def __init__(self):
        """Initialize HawkeyeBridge
        
        Args:
            recreate_log: If True, recreates the log file on startup
        """
        self.message_types = {'ack', 'status', 'error', 'data'}
        self.running = True
        self.logger = Logger(recreate_file=True)  # Initialize logger

    async def send_message(self, msg_type: str, message: Any) -> None:
        """Send message asynchronously"""
        if msg_type not in self.message_types:
            await self.log_error(f"Invalid message type: {msg_type}")
            return

        try:
            data = json.dumps({'type': msg_type, 'message': message}) + '\n'
            sys.stdout.write(data)
            sys.stdout.flush()
            self.logger.info(f"Sent message - Type: {msg_type}, Message: {message}")
        except Exception as e:
            await self.log_error(f"Error sending message: {e}")

    async def log_error(self, message: str) -> None:
        """Log error asynchronously"""
        self.logger.error(message)
        print(f"Error: {message}", file=sys.stderr, flush=True)

    async def handle_message(self, message: Dict[str, Any]) -> None:
        """Handle messages asynchronously"""
        self.logger.info(f"Received message: {message}")
        await self.send_message('ack', message)

    async def run(self) -> None:
        """Main async event loop"""
        self.logger.info("Starting Hawkeye Bridge")
        await self.send_message('status', 'Hawkeye Bridge started')
        
        try:
            async for line in self.read_stdin():
                if not self.running:
                    self.logger.info("Bridge stopping - running flag set to False")
                    break
                try:
                    message = json.loads(line.strip())
                    await self.handle_message(message)
                except json.JSONDecodeError as e:
                    await self.log_error(f"JSON decode error: {e}")
        except Exception as e:
            self.logger.critical(f"Critical error in main loop: {e}")
        finally:
            self.logger.info("Hawkeye Bridge stopping")
            await self.send_message('status', 'Hawkeye Bridge stopped')

    async def read_stdin(self):
        """Async generator for reading stdin"""
        loop = asyncio.get_event_loop()
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: protocol, sys.stdin)
        
        async for line in reader:
            yield line.decode('utf-8')


if __name__ == '__main__':
    bridge = HawkeyeBridge()
    bridge.logger.info("Hawkeye Bridge application started")
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        bridge.logger.info("Bridge interrupted by user")
    except Exception as e:
        bridge.logger.critical(f"Unhandled exception: {e}")
    finally:
        bridge.logger.info("Hawkeye Bridge application ended")
