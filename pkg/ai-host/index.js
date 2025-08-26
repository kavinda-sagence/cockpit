/* global cockpit */

import { LongRunningProcess, ProcessState } from './long-running-process.js';

// DOM objects
const state = document.getElementById("state");
const command = document.getElementById("command");
const runButton = document.getElementById("run");
const output = document.getElementById("output");
const clearButton = document.getElementById("clear");
const numStreams = document.getElementById('num_streams');
const fwPath = document.getElementById('fw_path');

// default shell command for the long-running process to run
const default_command = "/home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/out_runtime_test_app/aix/bin/deb64-x86_64/release/runtime/ai_host/run.sh";
const default_fw_path = "/home/kavinda/Desktop/MySpace/code/sg_sw/sw_ss/Linux86/RT/runtime_test_app/test_data/no_op/";
const default_num_streams = 1;

// follow live output of the given unit, put into "output" <pre> area
function showJournal(unitName, filter_arg) {
    // run at most one instance of journal tailing
    if (showJournal.journalctl)
        return;

    // reset previous output
    output.textContent = "";

    const argv = ["journalctl", "--user", "--output=cat", "--unit", unitName, "--follow", "--lines=all", filter_arg];
    showJournal.journalctl = cockpit.spawn(argv, { err: "message" })
            .stream(data => output.append(document.createTextNode(data)))
            .catch(ex => { output.textContent = JSON.stringify(ex) });
}

function update(process) {
    // console.log("Update called with state:", process.state);
    state.textContent = cockpit.format("$0 $1", process.serviceName, process.state);

    switch (process.state) {
    case ProcessState.INIT:
        break;
    case ProcessState.STOPPED:
        runButton.removeAttribute("disabled");
        runButton.textContent = "Start";
        break;
    case ProcessState.RUNNING:
        runButton.removeAttribute("disabled");
        runButton.textContent = "Terminate";
        // StateChangeTimestamp property is in µs since epoch, but journalctl expects seconds
        showJournal(process.serviceName, "--since=@" + Math.floor(process.startTimestamp / 1000000));
        break;
    case ProcessState.FAILED:
        runButton.removeAttribute("disabled");
        runButton.textContent = "Reset";
        // Show the whole journal of this boot
        showJournal(process.serviceName, "--boot");
        break;
    default:
        throw new Error("unexpected process.state: " + process.state);
    }
}

// called once after page initializes; set up the page
cockpit.transport.wait(() => {

    numStreams.innerHTML = '';
    for (let i = 1; i <= 256; i++) {
        const option = document.createElement('option');
        option.value = i;
        option.text = i;
        if (i === default_num_streams) option.selected = true;
        numStreams.appendChild(option);
    }

    clearButton.addEventListener("click", () => {
        output.textContent = "";
    });

    command.value = default_command;
    fwPath.value = default_fw_path;

    /* Build a service name which contains exactly the identifying properties for the
     * command to re-attach to. For a single static command this is just the page name,
     * but it could also include the command name or path, arguments, or a playbook name,
     * etc.  if the page is dealing with multiple commands. */
    const serviceName = "cockpit-ai-host.service";

    // Set up process manager; update() is called whenever the running state changes
    const process = new LongRunningProcess(serviceName, update);

    /* Start process on clicking the "Start" button
     * This runs as user, in the user's systemd session.
     */
    runButton.addEventListener("click", () => {

        if (process.state === ProcessState.RUNNING) {
            process.terminate();
        }
        else if (process.state === ProcessState.FAILED) {
            process.reset();
        }
        else {
            output.textContent = "";

            if("" === fwPath.value) {
                state.textContent = "Error: Firmware Path cannot be empty";
                fwPath.focus();
                return;
            }

            if("" === command.value) {
                state.textContent = "Error: Command cannot be empty";
                command.focus();
                return;
            }
            
            process.run(["/bin/stdbuf", "-oL", "-eL", "/bin/bash", command.value, fwPath.value, numStreams.value])
                    .catch(ex => {
                        state.textContent = "Error: " + ex.toString();
                        runButton.setAttribute("disabled", "");
                    });
        }

    });

});
