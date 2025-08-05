const address = document.getElementById("address");
const output = document.getElementById("output");
const result = document.getElementById("result");
const button = document.getElementById("ping");
const stopButton = document.getElementById("stop");

let pingProcess = null;

function ping_run() {
    /* global cockpit */
    pingProcess = cockpit.spawn(["ping", address.value]);
    pingProcess.stream(ping_output)
            .then(ping_success)
            .catch(ping_fail);

    result.textContent = "";
    output.textContent = "";
    
    // Update button states
    button.disabled = true;
    stopButton.disabled = false;
}

function ping_success() {
    result.style.color = "green";
    result.textContent = "success";
    
    // Reset button states
    button.disabled = false;
    stopButton.disabled = true;
    pingProcess = null;
}

function ping_fail() {
    result.style.color = "red";
    result.textContent = "fail";
    
    // Reset button states
    button.disabled = false;
    stopButton.disabled = true;
    pingProcess = null;
}

function ping_output(data) {
    output.append(document.createTextNode(data));
}

function ping_stop() {

    if (pingProcess) {
        pingProcess.close();
        result.style.color = "orange";
        result.textContent = "stopped";
        
        // Reset button states
        button.disabled = false;
        stopButton.disabled = true;
        pingProcess = null;
    }
}

// Connect the button to starting the "ping" process
button.addEventListener("click", ping_run);

// Connect the stop button to stopping the "ping" process
stopButton.addEventListener("click", ping_stop);

// Send a 'init' message.  This tells integration tests that we are ready to go
cockpit.transport.wait(function() { });
