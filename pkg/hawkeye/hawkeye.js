const address = "127.0.0.0"
const output = document.getElementById("output");
const result = document.getElementById("result");
const button = document.getElementById("start");
const stopButton = document.getElementById("stop");

let hostProcess = null;

function host_run() {
    /* global cockpit */
    hostProcess = cockpit.spawn(["ping", address]);
    hostProcess.stream(host_output)
            .then(host_success)
            .catch(host_fail);

    result.textContent = "";
    output.textContent = "";
    
    // Update button states
    button.disabled = true;
    stopButton.disabled = false;
}

function host_success() {
    result.style.color = "green";
    result.textContent = "success";
    
    // Reset button states
    button.disabled = false;
    stopButton.disabled = true;
    hostProcess = null;
}

function host_fail() {
    result.style.color = "red";
    result.textContent = "fail";
    
    // Reset button states
    button.disabled = false;
    stopButton.disabled = true;
    hostProcess = null;
}

function host_output(data) {
    output.append(document.createTextNode(data));
}

function host_stop() {

    if (hostProcess) {
        hostProcess.close();
        result.style.color = "orange";
        result.textContent = "stopped";
        
        // Reset button states
        button.disabled = false;
        stopButton.disabled = true;
        hostProcess = null;
    }
}

// Connect the button to starting the "host" process
button.addEventListener("click", host_run);

// Connect the stop button to stopping the "host" process
stopButton.addEventListener("click", host_stop);

// Send a 'init' message.  This tells integration tests that we are ready to go
cockpit.transport.wait(function() { });
