/* Clean, minimal implementation with dynamic streamer configuration */
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
                /** @type {((data:any)=>void)|null} */
                this.onStatusUpdate = null;
                /** @type {((data:any)=>void)|null} */
                this.onNotification = null;
                this.connect();
            }

            connect() {
                try {
                    const hawkeyeBridgePath = "/home/kavinda/Desktop/MySpace/code/cockpit/hawkeye_bridge/";
                    const hawkeyeBridgeScript = "hawkeye-bridge.sh";
                    this.channel = cockpit.channel({
                        payload: "stream",
                        spawn: [hawkeyeBridgePath + hawkeyeBridgeScript],
                        err: "ignore",
                        directory: hawkeyeBridgePath,
                        environ: [],
                        binary: false
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

        /** @param {any} data */
        handleRawMessage(data) {
                const lines = String(data).trim().split('\n');
                lines.forEach((line) => {
                    const trimmed = line.trim();
                    if (!trimmed) return;
                    if (!trimmed.startsWith('{')) {
                        console.warn("Skipping non-JSON line:", trimmed);
                        return;
                    }
                    try {
                        const message = JSON.parse(trimmed);
                        this.handleMessage(message);
                    } catch (e) {
                        const err = /** @type {any} */ (e);
                        console.error("Invalid JSON:", trimmed, "Error:", err && err.message);
                    }
                });
            }

        /** @param {{type?:string,[key:string]:any}} message */
        handleMessage(message) {
                if (!message || typeof message !== "object") {
                    console.error("Invalid message format:", message);
                    return;
                }
                if (!message.type) {
                    console.error("Message missing type:", message);
                    return;
                }
                console.log("Received message:", message);
                switch (message.type) {
                case "status":
                    this.handleStatus(message.data);
                    break;
                case "ntf":
                    this.handleNotification(message.data);
                    break;
                case "ack":
                    this.handleAck(message.data);
                    break;
                default:
                    console.warn("Unknown message type:", message.type);
                }
            }

        /** @param {any} data */
        handleStatus(data) {
                console.log("Status:", data);
                if (this.onStatusUpdate) {
                    try { this.onStatusUpdate(data); } catch (e) { console.error("onStatusUpdate handler error", e); }
                }
            }

        /** @param {any} data */
        handleNotification(data) {
                if (!data || typeof data !== "object") {
                    console.log("Notification:", data);
                    if (this.onNotification) { try { this.onNotification(data); } catch (e) { console.error("onNotification handler error", e); } }
                    return;
                }
                if (data.warning) console.warn("Bridge warning:", data.warning);
                else if (data.error) console.error("Bridge error:", data.error);
                else console.log("Notification:", data);
                if (this.onNotification) {
                    try { this.onNotification(data); } catch (e) { console.error("onNotification handler error", e); }
                }
            }

        /** @param {any} data */
        handleAck(data) {
                console.log("Acknowledgment:", data);
            }

        /** @param {any} options */
        handleChannelClose(options) {
                this.channel = null;
                if (options && options.problem) {
                    console.error("Channel closed with problem:", options.problem);
                }
                if (!this.isDisconnecting) this.scheduleReconnect();
            }

            scheduleReconnect() {
                if (this.reconnectAttempts >= this.maxReconnectAttempts) {
                    console.error("Max reconnection attempts reached");
                    return;
                }
                this.reconnectAttempts += 1;
                const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts - 1);
                console.log(`Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts})`);
                setTimeout(() => this.connect(), delay);
            }

        /** @param {string} type @param {any} data */
        sendCommand(type, data) {
                if (!this.channel) {
                    console.error("Channel not available");
                    return false;
                }
                const message = { type, data };
                const jsonMessage = JSON.stringify(message) + '\n';
                try {
                    console.log("Sending message:", message);
                    this.channel.send(jsonMessage);
                    return true;
                } catch (e) {
                    console.error("Failed to send message:", e);
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

        // UI initialization
        cockpit.transport.wait(() => {
            const hawkeye = new Hawkeye();

            // Channel config schemas (extendable)
            /** @type {Record<string,{role:'src'|'dest',fields:{name:string,label:string,type:'number'|'text',min?:number,placeholder?:string,default?:any,required?:boolean}[]}>} */
            const CHANNEL_CONFIG_SCHEMAS = {
                rand_gen: {
                    role: 'src',
                    fields: [
                        { name: 'number_of_frames', label: 'Frames', type: 'number', min: 1, default: 100, required: true }
                    ]
                },
                no_op: {
                    role: 'dest',
                    fields: []
                }
            };

            const MAX_STREAMS = 5;
            /** @type {HTMLElement|null} */ const streamsContainer = document.getElementById("streams");
            /** @type {HTMLButtonElement|null} */ const addStreamBtn = /** @type {HTMLButtonElement|null} */ (document.getElementById("add-stream"));
            /** @type {HTMLButtonElement|null} */ const clearStreamsBtn = /** @type {HTMLButtonElement|null} */ (document.getElementById("clear-streams"));
            /** @type {HTMLButtonElement|null} */ const startBtn = /** @type {HTMLButtonElement|null} */ (document.getElementById("start"));
            /** @type {HTMLButtonElement|null} */ const stopBtn = /** @type {HTMLButtonElement|null} */ (document.getElementById("stop"));
            /** @type {HTMLInputElement|null} */ const testDirInput = /** @type {HTMLInputElement|null} */ (document.getElementById("test-dir"));
            /** @type {HTMLElement|null} */ const messagesEl = document.getElementById("messages");
            /** Status related elements */
            /** @type {HTMLElement|null} */ const hostRunningEl = document.getElementById("host-running");
            /** @type {HTMLElement|null} */ const hostExitCodeEl = document.getElementById("host-exit-code");
            /** @type {HTMLElement|null} */ const hostStdoutEl = document.getElementById("host-stdout");
            /** @type {HTMLElement|null} */ const hostStderrEl = document.getElementById("host-stderr");
            /** @type {HTMLElement|null} */ const streamersContainerEl = document.getElementById("streamers-container");
            /** @type {HTMLElement|null} */ const hwTempsEl = document.getElementById("hw-temps");

            // Accumulated logs persist until a new Start
            const logStore = {
                /** @type {{stdout:string[], stderr:string[], running:boolean|null, exit_code:number|null}} */
                host: { stdout: /** @type {string[]} */([]), stderr: /** @type {string[]} */([]), running: null, exit_code: null },
                /** @type {Record<string, {alive:boolean|null,num_frames:number|string|null,frames_transmitted:number|string|null,frames_received:number|string|null,streamer_status_msgs:string[],streamer_error_msgs:string[],src_channel_status_msgs:string[],src_channel_error_msgs:string[],dest_channel_status_msgs:string[],dest_channel_error_msgs:string[]}>} */
                streamers: {}
            };

            function resetLogs() {
                logStore.host.stdout = [];
                logStore.host.stderr = [];
                logStore.host.running = null;
                logStore.host.exit_code = null;
                logStore.streamers = {};
            }

            /**
             * @param {string} msg
             * @param {boolean} [isError]
             */
            function setMessage(msg, isError = true) {
                if (!messagesEl) return;
                messagesEl.classList.remove("msg-error","msg-ok");
                messagesEl.classList.add(isError ? "msg-error" : "msg-ok");
                messagesEl.textContent = msg || "";
            }

            // Hook notifications into UI message area (simple handling)
            hawkeye.onNotification = (data) => {
                if (!data) { setMessage("(notification: empty)"); return; }
                if (data.error) setMessage(String(data.error), true);
                else if (data.warning) setMessage(String(data.warning), true);
                else setMessage(typeof data === 'string' ? data : JSON.stringify(data), false);
            };

            /** @returns {number} */
            function currentStreamCount() {
                if (!streamsContainer) return 0;
                return streamsContainer.querySelectorAll(".stream-row").length;
            }

            function updateAddDisabled() {
                if (addStreamBtn) addStreamBtn.disabled = currentStreamCount() >= MAX_STREAMS;
            }

            /** @param {number} id */
            function createStreamRow(id) {
                const row = document.createElement("div");
                row.className = "stream-row";
                row.dataset.streamId = String(id);
                row.innerHTML = `
                    <span>#${id}</span>
                    <label>Src
                        <select class="src-type">
                            <option value="rand_gen" selected>rand_gen</option>
                        </select>
                    </label>
                    <div class="src-configs cfg-block"></div>
                    <label>Dest
                        <select class="dest-type">
                            <option value="no_op" selected>no_op</option>
                        </select>
                    </label>
                    <div class="dest-configs cfg-block"></div>
                    <button type="button" class="remove">X</button>
                `;
                /** @type {HTMLButtonElement|null} */ const removeBtn = row.querySelector("button.remove");
                if (removeBtn) {
                    removeBtn.addEventListener("click", () => {
                        row.remove();
                        renumberStreams();
                        updateAddDisabled();
                    });
                }

                /**
                 * @param {'src'|'dest'} role
                 */
                function renderChannelConfigs(role) {
                    const sel = row.querySelector(role === 'src' ? 'select.src-type' : 'select.dest-type');
                    const container = row.querySelector(role === 'src' ? '.src-configs' : '.dest-configs');
                    if (!sel || !container) return;
                    const type = /** @type {HTMLSelectElement} */(sel).value;
                    const schema = CHANNEL_CONFIG_SCHEMAS[type];
                    container.innerHTML = '';
                    if (!schema || schema.role !== role || !schema.fields.length) return;
                    schema.fields.forEach(f => {
                        const wrap = document.createElement('label');
                        wrap.dataset.field = f.name;
                        let attrs = '';
                        if (f.type === 'number') {
                            if (f.min != null) attrs += ` min="${f.min}"`;
                        }
                        const defVal = f.default != null ? f.default : '';
                        wrap.innerHTML = `${f.label} <input type="${f.type}" class="cfg-field" data-name="${f.name}" value="${defVal}"${attrs} />`;
                        container.appendChild(wrap);
                    });
                }

                // initial render
                renderChannelConfigs('src');
                renderChannelConfigs('dest');
                const srcSel = row.querySelector('select.src-type');
                const destSel = row.querySelector('select.dest-type');
                if (srcSel) srcSel.addEventListener('change', () => renderChannelConfigs('src'));
                if (destSel) destSel.addEventListener('change', () => renderChannelConfigs('dest'));
                return row;
            }

            function renumberStreams() {
                if (!streamsContainer) return;
                const rows = streamsContainer.querySelectorAll(".stream-row");
                rows.forEach((el, idx) => {
                    const row = /** @type {HTMLElement} */ (el);
                    row.dataset.streamId = String(idx);
                    const span = row.querySelector("span");
                    if (span) span.textContent = `#${idx}`;
                });
            }

            function addStream() {
                if (!streamsContainer) return;
                if (currentStreamCount() >= MAX_STREAMS) {
                    setMessage(`Maximum ${MAX_STREAMS} streams reached.`);
                    return;
                }
                const row = createStreamRow(currentStreamCount());
                streamsContainer.appendChild(row);
                updateAddDisabled();
            }

            if (addStreamBtn) addStreamBtn.addEventListener("click", () => { setMessage(""); addStream(); });
            if (clearStreamsBtn) clearStreamsBtn.addEventListener("click", () => {
                if (!streamsContainer) return;
                streamsContainer.innerHTML = "";
                updateAddDisabled();
                setMessage("Cleared streams", false);
            });

            // Start with one default stream
            addStream();

            function gatherConfig() {
                const testDir = (testDirInput && testDirInput.value.trim()) || "";
                if (!testDir) {
                    setMessage("Test dir path required");
                    return null;
                }
                if (!streamsContainer) return null;
                /** @type {{id:number,src:{type:string,configs:Record<string,any>},dest:{type:string,configs:Record<string,any>}}[]} */
                const streams = [];
                const rows = streamsContainer.querySelectorAll(".stream-row");
                rows.forEach((el) => {
                    const row = /** @type {HTMLElement} */ (el);
                    const id = parseInt(row.dataset.streamId || "0", 10);
                    /** @type {HTMLSelectElement|null} */ const srcSel = row.querySelector("select.src-type");
                    /** @type {HTMLSelectElement|null} */ const destSel = row.querySelector("select.dest-type");
                    if (!srcSel || !destSel) return;
                    const srcType = srcSel.value;
                    const destType = destSel.value;
                    /** @type {Record<string,any>} */ const srcCfg = {};
                    /** @type {Record<string,any>} */ const destCfg = {};
                    const srcSchema = CHANNEL_CONFIG_SCHEMAS[srcType];
                    const destSchema = CHANNEL_CONFIG_SCHEMAS[destType];
                    if (srcSchema && srcSchema.fields.length) {
                        const container = row.querySelector('.src-configs');
                        if (container) {
                            srcSchema.fields.forEach(f => {
                                const input = container.querySelector(`input[data-name="${f.name}"]`);
                                if (input) {
                                    const valRaw = /** @type {HTMLInputElement} */(input).value;
                                    if (f.type === 'number') {
                                        const num = parseFloat(valRaw);
                                        if (!Number.isNaN(num)) srcCfg[f.name] = num; else srcCfg[f.name] = valRaw;
                                    } else {
                                        srcCfg[f.name] = valRaw;
                                    }
                                }
                            });
                        }
                    }
                    if (destSchema && destSchema.fields.length) {
                        const container = row.querySelector('.dest-configs');
                        if (container) {
                            destSchema.fields.forEach(f => {
                                const input = container.querySelector(`input[data-name="${f.name}"]`);
                                if (input) {
                                    const valRaw = /** @type {HTMLInputElement} */(input).value;
                                    if (f.type === 'number') {
                                        const num = parseFloat(valRaw);
                                        if (!Number.isNaN(num)) destCfg[f.name] = num; else destCfg[f.name] = valRaw;
                                    } else {
                                        destCfg[f.name] = valRaw;
                                    }
                                }
                            });
                        }
                    }
                    // basic validation for required fields
                    if (srcSchema) {
                        const missing = srcSchema.fields.filter(f=>f.required && (srcCfg[f.name]==null || srcCfg[f.name]===""));
                        if (missing.length) return; // skip invalid stream
                    }
                    streams.push({ id, src: { type: srcType, configs: srcCfg }, dest: { type: destType, configs: destCfg } });
                });
                if (!streams.length) {
                    setMessage("At least one valid stream required");
                    return null;
                }
                return { test_dir_path: testDir, streams };
            }

            if (startBtn) startBtn.addEventListener("click", () => {
                setMessage("");
                resetLogs(); // new inference run starting, clear previous logs
                const cfg = gatherConfig();
                if (!cfg) return;
                hawkeye.sendCommand("command", { component: "inf_process", command: "start", configs: cfg });
                setMessage("Start command sent", false);
            });
            if (stopBtn) stopBtn.addEventListener("click", () => {
                setMessage("");
                hawkeye.sendCommand("command", { component: "inf_process", command: "stop" });
                setMessage("Stop command sent", false);
            });

            window.addEventListener("beforeunload", () => hawkeye.disconnect());
            // window.hawkeye = hawkeye; // Uncomment for debugging

            // ---- Status UI rendering ----
            /** @param {any} statusData */
            function updateStatusUI(statusData) {
                if (!statusData || typeof statusData !== "object") return;
                // Hardware temps
                (function renderHwTemps(){
                    if (!hwTempsEl) return;
                    const hw = statusData.hw || {};
                    const temps = hw.temps || {};
                    const keys = Object.keys(temps);
                    const atBottom = (hwTempsEl.scrollTop + hwTempsEl.clientHeight) >= (hwTempsEl.scrollHeight - 4);
                    hwTempsEl.innerHTML = "";
                    if (!keys.length) {
                        const li = document.createElement("li");
                        li.className = "empty-hint";
                        li.textContent = "(no temps)";
                        hwTempsEl.appendChild(li);
                        if (atBottom) hwTempsEl.scrollTop = hwTempsEl.scrollHeight;
                        return;
                    }
                    keys.sort();
                    keys.forEach(k => {
                        const li = document.createElement("li");
                        li.textContent = `${k}: ${temps[k]}`;
                        hwTempsEl.appendChild(li);
                    });
                    if (atBottom) hwTempsEl.scrollTop = hwTempsEl.scrollHeight;
                })();
                const infPro = statusData.inf_pro || {};
                const hostPresent = Object.prototype.hasOwnProperty.call(infPro, "host");
                const host = hostPresent ? (infPro.host || {}) : {};
                // Merge host info & append new stdout/stderr lines
                if (!hostPresent) {
                    // Inference process section disappeared => treat as stopped
                    logStore.host.running = false;
                } else {
                    logStore.host.running = host.running == null ? logStore.host.running : host.running;
                }
                logStore.host.exit_code = host.exit_code == null ? logStore.host.exit_code : host.exit_code;
                if (Array.isArray(host.stdout)) {
                    host.stdout.forEach((/** @type {any} */ l) => { const line = String(l); if (!logStore.host.stdout.includes(line)) logStore.host.stdout.push(line); });
                }
                if (Array.isArray(host.stderr)) {
                    host.stderr.forEach((/** @type {any} */ l) => { const line = String(l); if (!logStore.host.stderr.includes(line)) logStore.host.stderr.push(line); });
                }
                if (hostRunningEl) hostRunningEl.textContent = logStore.host.running == null ? "-" : String(!!logStore.host.running);
                if (hostExitCodeEl) hostExitCodeEl.textContent = logStore.host.exit_code == null ? "-" : String(logStore.host.exit_code);
                // Helper to populate list
                /**
                 * @param {HTMLElement|null} container
                 * @param {any} arr
                 * @param {boolean} isErr
                 */
                function fillList(container, arr, isErr) {
                    if (!container) return;
                    const atBottom = (container.scrollTop + container.clientHeight) >= (container.scrollHeight - 4);
                    container.innerHTML = "";
                    if (!Array.isArray(arr) || !arr.length) {
                        const li = document.createElement("li");
                        li.className = "empty-hint";
                        li.textContent = "(empty)";
                        container.appendChild(li);
                        if (atBottom) container.scrollTop = container.scrollHeight;
                        return;
                    }
                    arr.forEach(line => {
                        const li = document.createElement("li");
                        if (isErr) li.classList.add("error");
                        li.textContent = String(line);
                        container.appendChild(li);
                    });
                    if (atBottom) container.scrollTop = container.scrollHeight;
                }
                fillList(hostStdoutEl, logStore.host.stdout, false);
                fillList(hostStderrEl, logStore.host.stderr, true);

                // Streamers
                const streamers = (infPro.streamers && typeof infPro.streamers === "object") ? infPro.streamers : {};
                if (!hostPresent) {
                    // Clear streamers when inference process is gone
                    logStore.streamers = {};
                }
                // Merge streamer data
                Object.keys(streamers).forEach(k => {
                    const incoming = streamers[k] || {};
                    if (!logStore.streamers[k]) {
                        logStore.streamers[k] = {
                            alive: incoming.alive,
                            num_frames: incoming.num_frames,
                            frames_transmitted: incoming.frames_transmitted,
                            frames_received: incoming.frames_received,
                            streamer_status_msgs: [],
                            streamer_error_msgs: [],
                            src_channel_status_msgs: [],
                            src_channel_error_msgs: [],
                            dest_channel_status_msgs: [],
                            dest_channel_error_msgs: []
                        };
                    }
                    const stored = logStore.streamers[k];
                    // Update scalar fields with latest values if provided
                    if (incoming.alive != null) stored.alive = incoming.alive;
                    if (incoming.num_frames != null) stored.num_frames = incoming.num_frames;
                    if (incoming.frames_transmitted != null) stored.frames_transmitted = incoming.frames_transmitted;
                    if (incoming.frames_received != null) stored.frames_received = incoming.frames_received;
                    // Helper to merge arrays without duplicates, preserving order
                    /**
                     * @param {keyof typeof stored} field
                     * @param {any} incomingArr
                     */
                    function mergeArr(field, incomingArr) {
                        const target = stored[field];
                        if (!Array.isArray(incomingArr) || !Array.isArray(target)) return;
                        incomingArr.forEach((item) => {
                            const line = String(item);
                            if (!target.includes(line)) target.push(line);
                        });
                    }
                    mergeArr("streamer_status_msgs", incoming.streamer_status_msgs);
                    mergeArr("streamer_error_msgs", incoming.streamer_error_msgs);
                    mergeArr("src_channel_status_msgs", incoming.src_channel_status_msgs);
                    mergeArr("src_channel_error_msgs", incoming.src_channel_error_msgs);
                    mergeArr("dest_channel_status_msgs", incoming.dest_channel_status_msgs);
                    mergeArr("dest_channel_error_msgs", incoming.dest_channel_error_msgs);
                });
                if (streamersContainerEl) {
                    streamersContainerEl.innerHTML = "";
                    const keys = Object.keys(logStore.streamers).sort((a,b)=>parseInt(a,10)-parseInt(b,10));
                    if (!keys.length) {
                        const div = document.createElement("div");
                        div.className = "empty-hint";
                        div.textContent = "No streamer data";
                        streamersContainerEl.appendChild(div);
                    } else {
                        keys.forEach(k => {
                            const sObj = logStore.streamers[k] || {};
                            const card = document.createElement("div");
                            card.className = "streamer-card";
                            const alive = sObj.alive === true;
                            const framesTx = sObj.frames_transmitted ?? "-";
                            const framesRx = sObj.frames_received ?? "-";
                            const numFrames = sObj.num_frames ?? "-";
                            card.innerHTML = `
                                <div class="streamer-header">
                                    <div>Streamer #${k}</div>
                                    <div class="badges">
                                        <span class="badge alive-${alive}">${alive ? "ALIVE" : "DONE"}</span>
                                        <span class="badge">Frames ${framesTx}/${numFrames} TX</span>
                                        <span class="badge">RX ${framesRx}</span>
                                    </div>
                                </div>
                                <div class="pair-cols">
                                    <div class="col">
                                        <div class="msg-group-title">Streamer Status</div>
                                        <ul class="msg-list streamer-status"></ul>
                                        <div class="msg-group-title">Streamer Errors</div>
                                        <ul class="msg-list streamer-errors"></ul>
                                    </div>
                                    <div class="col">
                                        <div class="msg-group-title">Src Channel Status</div>
                                        <ul class="msg-list src-status"></ul>
                                        <div class="msg-group-title">Src Channel Errors</div>
                                        <ul class="msg-list src-errors"></ul>
                                    </div>
                                    <div class="col">
                                        <div class="msg-group-title">Dest Channel Status</div>
                                        <ul class="msg-list dest-status"></ul>
                                        <div class="msg-group-title">Dest Channel Errors</div>
                                        <ul class="msg-list dest-errors"></ul>
                                    </div>
                                </div>
                            `;
                            streamersContainerEl.appendChild(card);
                            // Fill lists
                            fillList(card.querySelector(".streamer-status"), sObj.streamer_status_msgs, false);
                            fillList(card.querySelector(".streamer-errors"), sObj.streamer_error_msgs, true);
                            fillList(card.querySelector(".src-status"), sObj.src_channel_status_msgs, false);
                            fillList(card.querySelector(".src-errors"), sObj.src_channel_error_msgs, true);
                            fillList(card.querySelector(".dest-status"), sObj.dest_channel_status_msgs, false);
                            fillList(card.querySelector(".dest-errors"), sObj.dest_channel_error_msgs, true);
                        });
                    }
                }
            }

            hawkeye.onStatusUpdate = updateStatusUI;
            // For quick manual UI test without backend, you can uncomment below:
            // setTimeout(() => {
            //     updateStatusUI({
            //         inf_pro: {
            //             host: { running: true, exit_code: null, stdout: ["Framework init"], stderr: [] },
            //             streamers: {
            //                 0: { alive: true, num_frames: 50, frames_transmitted: 10, frames_received: 5, streamer_status_msgs: ["Started"], streamer_error_msgs: [], src_channel_status_msgs: ["Frame 1 captured"], src_channel_error_msgs: [], dest_channel_status_msgs: ["Frame 1 received"], dest_channel_error_msgs: [] }
            //             }
            //         }
            //     });
            // }, 500);
        });
})();

// Example JSON messages from the bridge for testing:
// Status message - when inference process is running
// Example 1
// {
//     "type": "status",
//     "data": {
//         "hw": {
//             "temps": {
//                 "iope_temperature": 0.12300000339746475,
//                 "sub_array_0_temperature": 0.12300000339746475,
//                 "sub_array_1_temperature": 1.1230000257492065,
//                 "sub_array_2_temperature": 2.122999906539917,
//                 "sub_array_3_temperature": 3.122999906539917
//             }
//         },
//         "inf_pro": {
//             "host": {
//                 "stdout": [
//                     "User name: kavinda",
//                     "User home dir: /home/kavinda",
//                     "Framework path: /home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/test_data/no_op",
//                 ],
//                 "stderr": [],
//                 "running": true,
//                 "exit_code": null
//             },
//             "streamers": {
//                 "0": {
//                     "alive": true,
//                     "num_frames": 123,
//                     "frames_transmitted": 1,
//                     "frames_received": 0,
//                     "streamer_status_msgs": [
//                         "Frame streaming started."
//                     ],
//                     "streamer_error_msgs": [],
//                     "src_channel_status_msgs": [
//                         "Frame 1 captured"
//                     ],
//                     "src_channel_error_msgs": [],
//                     "dest_channel_status_msgs": [],
//                     "dest_channel_error_msgs": []
//                 },
//                 "1": {
//                     "alive": true,
//                     "num_frames": 456,
//                     "frames_transmitted": 0,
//                     "frames_received": 0,
//                     "streamer_status_msgs": [
//                         "Frame streaming started."
//                     ],
//                     "streamer_error_msgs": [],
//                     "src_channel_status_msgs": [],
//                     "src_channel_error_msgs": [],
//                     "dest_channel_status_msgs": [],
//                     "dest_channel_error_msgs": []
//                 }
//             }
//         }
//     }
// }
// Example 2
// {
//     "type": "status",
//     "data": {
//         "hw": {
//             "temps": {
//                 "iope_temperature": 0.12300000339746475,
//                 "sub_array_0_temperature": 0.12300000339746475,
//                 "sub_array_1_temperature": 1.1230000257492065,
//                 "sub_array_2_temperature": 2.122999906539917,
//                 "sub_array_3_temperature": 3.122999906539917
//             }
//         },
//         "inf_pro": {
//             "host": {
//                 "stdout": [],
//                 "stderr": [],
//                 "running": true,
//                 "exit_code": null
//             },
//             "streamers": {
//                 "0": {
//                     "alive": true,
//                     "num_frames": 123,
//                     "frames_transmitted": 10,
//                     "frames_received": 5,
//                     "streamer_status_msgs": [],
//                     "streamer_error_msgs": [],
//                     "src_channel_status_msgs": [
//                         "Frame 2 captured",
//                         "Frame 3 captured",
//                         "Frame 4 captured",
//                         "Frame 5 captured",
//                         "Frame 6 captured",
//                         "Frame 7 captured",
//                         "Frame 8 captured"
//                     ],
//                     "src_channel_error_msgs": [],
//                     "dest_channel_status_msgs": [
//                         "Frame 1 received",
//                         "Frame 2 received",
//                         "Frame 3 received",
//                         "Frame 4 received"
//                     ],
//                     "dest_channel_error_msgs": []
//                 },
//                 "1": {
//                     "alive": true,
//                     "num_frames": 456,
//                     "frames_transmitted": 2,
//                     "frames_received": 0,
//                     "streamer_status_msgs": [],
//                     "streamer_error_msgs": [],
//                     "src_channel_status_msgs": [
//                         "Frame 1 captured"
//                     ],
//                     "src_channel_error_msgs": [],
//                     "dest_channel_status_msgs": [],
//                     "dest_channel_error_msgs": []
//                 }
//             }
//         }
//     }
// }
// Status message - when streamers done
// {
//     "type": "status",
//     "data": {
//         "hw": {
//             "temps": {
//                 "iope_temperature": 0.12300000339746475,
//                 "sub_array_0_temperature": 0.12300000339746475,
//                 "sub_array_1_temperature": 1.1230000257492065,
//                 "sub_array_2_temperature": 2.122999906539917,
//                 "sub_array_3_temperature": 3.122999906539917
//             }
//         },
//         "inf_pro": {
//             "host": {
//                 "stdout": [],
//                 "stderr": [],
//                 "running": true,
//                 "exit_code": null
//             },
//             "streamers": {
//                 "0": {
//                     "alive": false,
//                     "num_frames": 123,
//                     "frames_transmitted": 123,
//                     "frames_received": 123,
//                     "streamer_status_msgs": [],
//                     "streamer_error_msgs": [],
//                     "src_channel_status_msgs": [],
//                     "src_channel_error_msgs": [],
//                     "dest_channel_status_msgs": [],
//                     "dest_channel_error_msgs": []
//                 },
//                 "1": {
//                     "alive": false,
//                     "num_frames": 456,
//                     "frames_transmitted": 456,
//                     "frames_received": 456,
//                     "streamer_status_msgs": [],
//                     "streamer_error_msgs": [],
//                     "src_channel_status_msgs": [],
//                     "src_channel_error_msgs": [],
//                     "dest_channel_status_msgs": [],
//                     "dest_channel_error_msgs": []
//                 }
//             }
//         }
//     }
// }
// Status message - when inference process stopped
// {
//     "type": "status",
//     "data": {
//         "hw": {},
//         "inf_pro": {}
//     }
// }
// When command send and once backend process, it acknowledges
// {
//     "type": "ack",
//     "data": null
// }
// Notification messages
// {
//     "type": "ntf",
//     "data": {
//         "warning": "Inference process is not running"
//     }
// }
// {
//     "type": "ntf",
//     "data": {
//         "error": "Failed to start inference process: Failed to start host process: Process failed to start. Exit code: 127, stderr: bash: /home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/out_runtime_test_app/aix/bin/deb64-x86_64/release/runtime/ai_host1/run.sh: No such file or directory"
//     }
// }