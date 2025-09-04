#!/usr/bin/env python3

import sys
import json
import asyncio
from typing import Dict, Any


class HawkeyeBridge:
    def __init__(self):
        self.message_types = {'ack', 'status', 'error', 'data'}
        self.running = True

    async def send_message(self, msg_type: str, message: Any) -> None:
        """Send message asynchronously"""
        if msg_type not in self.message_types:
            await self.log_error(f"Invalid message type: {msg_type}")
            return

        try:
            data = json.dumps({'type': msg_type, 'message': message}) + '\n'
            sys.stdout.write(data)
            sys.stdout.flush()
        except Exception as e:
            await self.log_error(f"Error sending message: {e}")

    async def log_error(self, message: str) -> None:
        """Log error asynchronously"""
        print(f"Error: {message}", file=sys.stderr, flush=True)

    async def handle_message(self, message: Dict[str, Any]) -> None:
        """Handle messages asynchronously"""
        await self.send_message('ack', message)

    async def run(self) -> None:
        """Main async event loop"""
        await self.send_message('status', 'Hawkeye Bridge started')
        
        try:
            async for line in self.read_stdin():
                if not self.running:
                    break
                try:
                    message = json.loads(line.strip())
                    await self.handle_message(message)
                except json.JSONDecodeError as e:
                    await self.log_error(f"JSON decode error: {e}")
        finally:
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
    asyncio.run(bridge.run())
