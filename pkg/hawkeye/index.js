const { Timestamp } = require("@patternfly/react-core");

(function() {
    "use strict";

    const cockpit = require("cockpit");

    class Hawkeye {
        constructor() {
            this.channel = null;
            this.reconnectAttempts = 0;
            this.maxReconnectAttempts = 5;
            this.reconnectDelay = 1000;
            this.isDisconnecting = false;
            this.connect();
        }

        connect() {
            try {

                const hawkeyeBridgePath = "/home/kavinda/Desktop/MySpace/code/cockpit/hawkeye_bridge/";
                const hawkeyeBridgeScript = "hawkeye-bridge.sh";

                this.channel = cockpit.channel({
                    "payload": "stream",
                    "spawn": [hawkeyeBridgePath + hawkeyeBridgeScript],
                    "err": "ignore",  // Ignore stderr to prevent it from reaching frontend
                    "directory": hawkeyeBridgePath,
                    "environ": [],
                    "binary": false
                });

                this.channel.addEventListener("message", (event, data) => {
                    this.handleRawMessage(data);
                });

                this.channel.addEventListener("close", (event, options) => {
                    console.log("Channel closed:", options);
                    this.handleChannelClose(options);
                });

                this.channel.addEventListener("ready", () => {
                    console.log("Channel ready");
                    this.reconnectAttempts = 0;
                });

                // Handle stderr messages (should not occur due to "err": "ignore")
                this.channel.addEventListener("control", (event, options) => {
                    if (options.command === "done" && options.problem) {
                        console.error("Bridge process error:", options.problem);
                    }
                });

            } catch (error) {
                console.error("Failed to create channel:", error);
                this.scheduleReconnect();
            }
        }

        handleRawMessage(data) {
            // Handle multiple JSON messages in one data chunk
            const lines = data.trim().split('\n');
            
            lines.forEach(line => {
                if (line.trim()) {
                    // Skip lines that don't look like JSON (error messages)
                    if (!line.trim().startsWith('{')) {
                        console.warn("Skipping non-JSON line:", line);
                        return;
                    }
                    
                    try {
                        const message = JSON.parse(line);
                        this.handleMessage(message);
                    } catch (e) {
                        console.error("Invalid JSON:", line, "Error:", e.message);
                    }
                }
            });
        }

        handleMessage(message) {
            // Validate message structure
            if (!message || typeof message !== 'object') {
                console.error("Invalid message format:", message);
                return;
            }

            if (!message.type) {
                console.error("Message missing type:", message);
                return;
            }

            console.log("Received message:", message);

            // Handle different message types
            switch (message.type) {
                case 'status':
                    this.handleStatus(message.data);
                    break;
                case 'error':
                    this.handleError(message.data);
                    break;
                case 'ack':
                    this.handleAck(message.data);
                    break;
                default:
                    console.warn("Unknown message type:", message.type);
            }
        }

        handleStatus(message) {
            console.log("Status:", message);
            // Update UI status indicator here
        }

        handleError(message) {
            console.error("Bridge error:", message);
            // Show error notification to user
        }

        handleAck(message) {
            console.log("Acknowledgment:", message);
        }

        handleChannelClose(options) {
            this.channel = null;
            
            if (options && options.problem) {
                console.error("Channel closed with problem:", options.problem);
            }

            // Only attempt to reconnect if we're not intentionally disconnecting
            if (!this.isDisconnecting) {
                this.scheduleReconnect();
            }
        }

        scheduleReconnect() {
            if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                console.error("Max reconnection attempts reached");
                return;
            }

            this.reconnectAttempts++;
            const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1); // Exponential backoff
            
            console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
            
            setTimeout(() => {
                this.connect();
            }, delay);
        }

        sendCommand(type, data) {
            if (!this.channel) {
                console.error("Channel not available");
                return false;
            }

            const message = { type, data };
            const jsonMessage = JSON.stringify(message) + '\n';

            console.log("Sending message:", message);

            try {
                this.channel.send(jsonMessage);
                return true;
            } catch (error) {
                console.error("Failed to send message:", error);
                return false;
            }
        }

        disconnect() {
            this.isDisconnecting = true;
            if (this.channel) {
                this.channel.close();
                this.channel = null;
            }
        }
    }

    // Initialize when cockpit is ready
    cockpit.transport.wait(function() {
        const hawkeye = new Hawkeye();

        // Add click handler if element exists
        const sendButton = document.getElementById("send");
        if (sendButton) {
            sendButton.addEventListener("click", () => {
                hawkeye.sendCommand('ping', {Timestamp: Date.now()});
            });
        }

        // Cleanup on page unload
        window.addEventListener('beforeunload', () => {
            hawkeye.disconnect();
        });

        // Make hawkeye available globally for debugging
        // window.hawkeye = hawkeye;
    });
})();
