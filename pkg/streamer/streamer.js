const command = document.getElementById("command");
const output = document.getElementById("output");
const result = document.getElementById("result");
const startButton = document.getElementById("start");
const stopButton = document.getElementById("stop");
const clearButton = document.getElementById("clear");
const streamId = document.getElementById("stream_id");
const fwPath = document.getElementById('fw_path');
const numFrames = document.getElementById('num_frames');

const default_command = "/home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/out_runtime_test_app/aix/bin/deb64-x86_64/release/streamer/streamer_opencv/run.sh";
const default_fw_path = "/home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/test_data/no_op/";
const default_stream_id = 0;
const default_num_frames = 100;
let streamerProcess = null;

function streamer_run() {
    /* global cockpit */
    streamerProcess = cockpit.spawn(["/bin/stdbuf", "-oL", "-eL", "/bin/bash", command.value, fwPath.value, streamId.value, numFrames.value]);
    streamerProcess.stream(streamer_output)
            .then(streamer_success)
            .catch(streamer_fail);

    result.textContent = "";
    output.textContent = "";
    
    // Update button states
    startButton.disabled = true;
    stopButton.disabled = false;
}

function streamer_success() {
    result.style.color = "green";
    result.textContent = "success";
    
    // Reset button states
    startButton.disabled = false;
    stopButton.disabled = true;
    streamerProcess = null;
}

function streamer_fail() {
    result.style.color = "red";
    result.textContent = "fail";
    
    // Reset button states
    startButton.disabled = false;
    stopButton.disabled = true;
    streamerProcess = null;
}

function streamer_output(data) {
    output.append(document.createTextNode(data));
}

function streamer_stop() {

    if (streamerProcess) {
        streamerProcess.close();
        result.style.color = "orange";
        result.textContent = "stopped";
        
        // Reset button states
        startButton.disabled = false;
        stopButton.disabled = true;
        streamerProcess = null;
    }
}

// Connect the button to starting the "ping" process
startButton.addEventListener("click", streamer_run);

// Connect the stop button to stopping the "ping" process
stopButton.addEventListener("click", streamer_stop);

clearButton.addEventListener("click", () => {
    output.textContent = "";
});

// Send a 'init' message.  This tells integration tests that we are ready to go
cockpit.transport.wait(function() {
    command.value = default_command;
    fwPath.value = default_fw_path;
    numFrames.value = default_num_frames;

    streamId.innerHTML = '';
    for (let i = 0; i <= 255; i++) {
        const option = document.createElement('option');
        option.value = i;
        option.text = i;
        if (i === default_stream_id) option.selected = true;
        streamId.appendChild(option);
    }
});
