(function() {
    "use strict";

    const cockpit = require("cockpit");
    
    class TempMonitor {
        constructor() {
            this.channel = null;
            this.connect();
        }
        
        connect() {
            // Create a stream channel to your Python script
            this.channel = cockpit.channel({
                "payload": "stream",
                "spawn": ["/home/kavinda/Desktop/MySpace/code/cockpit/pkg/example/temp-sensor-bridge.py"],
                "environ": ["TERM=xterm-256color"]
            });
            
            this.channel.addEventListener("message", (event, data) => {
                try {
                    const message = JSON.parse(data);
                    this.handleMessage(message);
                } catch (e) {
                    console.error("Invalid JSON:", data);
                }
            });
            
            this.channel.addEventListener("close", () => {
                console.log("Channel closed");
                // Optionally reconnect
                setTimeout(() => this.connect(), 5000);
            });
        }
        
        handleMessage(message) {
            console.log("Received message:", message);
            if (message.type === 'temperature') {
                this.updateTemperatureDisplay(message.data);
            } else if (message.type === 'ack') {
                console.log("Received acknowledgment:", message.message);
                this.showStatus(message.message, 'success');
            } else if (message.type === 'error') {
                console.error("Received error:", message.message);
                this.showStatus(message.message, 'error');
            } else if (message.type === 'status') {
                console.log("Status:", message.message);
                this.showStatus(message.message, 'info');
            }
        }
        
        updateTemperatureDisplay(tempData) {
            // Update your UI with temperature data
            const cpuTempElement = document.getElementById('cpu-temp');
            const ambientTempElement = document.getElementById('ambient-temp');
            
            if (cpuTempElement && tempData.cpu_temp !== undefined) {
                cpuTempElement.textContent = tempData.cpu_temp + '°C';
            }
            if (ambientTempElement && tempData.ambient_temp !== undefined) {
                ambientTempElement.textContent = tempData.ambient_temp + '°C';
            }
        }
        
        showStatus(message, type) {
            console.log(`${type.toUpperCase()}: ${message}`);
            
            const statusArea = document.getElementById('status-area');
            if (statusArea) {
                statusArea.innerHTML = `<div class="status-message status-${type}">${message}</div>`;
                
                // Auto-hide after 5 seconds for success/info messages
                if (type === 'success' || type === 'info') {
                    setTimeout(() => {
                        statusArea.innerHTML = '';
                    }, 5000);
                }
            }
        }
        
        sendCommand(command, data = {}) {
            const message = { command, ...data };
            if (this.channel) {
                this.channel.send(JSON.stringify(message) + '\n');
            } else {
                console.error("Channel not available");
            }
        }
        
        requestTemperature() {
            this.sendCommand('get_temp');
        }
        
        updateConfig(config) {
            this.sendCommand('set_config', { config });
        }
    }
    
    // Initialize when page loads
    document.addEventListener("DOMContentLoaded", () => {
        const monitor = new TempMonitor();
        
        // Example: Request temperature every 10 seconds
        setInterval(() => monitor.requestTemperature(), 10000);
        
        // Example: Button to update configuration
        document.getElementById('update-config')?.addEventListener('click', () => {
            monitor.updateConfig({ polling_interval: 3 });
        });
        
        // Button to manually request temperature
        document.getElementById('request-temp')?.addEventListener('click', () => {
            monitor.requestTemperature();
        });
    });
})();