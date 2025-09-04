#!/usr/bin/env python3
import sys
import json
import time
import threading
import random

# Your custom hardware interface
class TempSensor:
    def __init__(self):
        self.config = {"polling_interval": 5}
        
    def read_temperature(self):
        # Replace with your actual hardware reading logic
        # For now, using random values for demonstration
        cpu_temp = round(random.uniform(40.0, 60.0), 1)
        ambient_temp = round(random.uniform(20.0, 30.0), 1)
        return {"cpu_temp": cpu_temp, "ambient_temp": ambient_temp}
    
    def set_config(self, config):
        # Handle configuration from Cockpit
        self.config.update(config)
        return True

class CockpitBridge:
    def __init__(self):
        self.sensor = TempSensor()
        self.running = True
        
    def send_message(self, message):
        """Send message to Cockpit via stdout"""
        try:
            json.dump(message, sys.stdout)
            sys.stdout.write('\n')
            sys.stdout.flush()
        except Exception as e:
            self.log_error(f"Error sending message: {e}")
            
    def log_error(self, message):
        """Log error messages to stderr"""
        print(f"Error: {message}", file=sys.stderr)
        
    def read_messages(self):
        """Read messages from Cockpit via stdin"""
        try:
            for line in sys.stdin:
                if not self.running:
                    break
                try:
                    line = line.strip()
                    if line:
                        message = json.loads(line)
                        self.handle_cockpit_message(message)
                except json.JSONDecodeError as e:
                    self.log_error(f"JSON decode error: {e}")
                    continue
        except Exception as e:
            self.log_error(f"Error reading messages: {e}")
                
    def handle_cockpit_message(self, message):
        """Handle incoming messages from Cockpit"""
        try:
            if message.get('command') == 'get_temp':
                temp_data = self.sensor.read_temperature()
                self.send_message({
                    'type': 'temperature',
                    'data': temp_data,
                    'timestamp': time.time()
                })
            elif message.get('command') == 'set_config':
                config = message.get('config', {})
                success = self.sensor.set_config(config)
                self.send_message({
                    'type': 'ack', 
                    'message': f'Config updated: {config}',
                    'success': success
                })
            elif message.get('command') == 'stop':
                self.running = False
                self.send_message({'type': 'ack', 'message': 'Stopping'})
            else:
                self.send_message({
                    'type': 'error',
                    'message': f'Unknown command: {message.get("command")}'
                })
        except Exception as e:
            self.send_message({
                'type': 'error',
                'message': f'Error handling command: {e}'
            })
            
    def start_temp_monitoring(self):
        """Send periodic temperature updates"""
        while self.running:
            try:
                temp_data = self.sensor.read_temperature()
                self.send_message({
                    'type': 'temperature',
                    'data': temp_data,
                    'timestamp': time.time()
                })
                time.sleep(self.sensor.config.get('polling_interval', 5))
            except Exception as e:
                self.log_error(f"Error in temperature monitoring: {e}")
                time.sleep(5)
                
    def run(self):
        try:
            # Send initial status
            self.send_message({
                'type': 'status',
                'message': 'Temperature bridge started',
                'config': self.sensor.config
            })
            
            # Start temperature monitoring in background
            temp_thread = threading.Thread(target=self.start_temp_monitoring)
            temp_thread.daemon = True
            temp_thread.start()
            
            # Listen for Cockpit messages
            self.read_messages()
        except Exception as e:
            self.log_error(f"Error in main loop: {e}")
        finally:
            self.running = False

if __name__ == "__main__":
    bridge = CockpitBridge()
    bridge.run()
