/*
 * This file is part of Cockpit.
 *
 * Copyright (C) 2020 Red Hat, Inc.
 *
 * Cockpit is free software; you can redistribute it and/or modify it
 * under the terms of the GNU Lesser General Public License as published by
 * the Free Software Foundation; either version 2.1 of the License, or
 * (at your option) any later version.
 *
 * Cockpit is distributed in the hope that it will be useful, but
 * WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
 * Lesser General Public License for more details.
 *
 * You should have received a copy of the GNU Lesser General Public License
 * along with Cockpit; If not, see <https://www.gnu.org/licenses/>.
 */

/* Manage a long-running precious process that runs independently from a Cockpit
 * session in a transient systemd service unit. See
 * examples/long-running-process/README.md for details.
 *
 * The unit will run as user, in the user's systemd session. This allows each user
 * to manage their own long-running processes independently.
 */

/* global cockpit */

// systemd D-Bus API names
const O_SD_OBJ = "/org/freedesktop/systemd1";
const I_SD_MGR = "org.freedesktop.systemd1.Manager";
const I_SD_UNIT = "org.freedesktop.systemd1.Unit";
const I_DBUS_PROP = "org.freedesktop.DBus.Properties";

/* Possible LongRunningProcess.state values */
export const ProcessState = {
    INIT: 'init',
    STOPPED: 'stopped',
    RUNNING: 'running',
    FAILED: 'failed',
};

export class LongRunningProcess {
    /* serviceName: systemd unit name to start or reattach to
     * updateCallback: function that gets called whenever the state changed; first and only
     *                 argument is `this` LongRunningProcess instance.
     */
    constructor(serviceName, updateCallback) {
        this.systemdClient = cockpit.dbus("org.freedesktop.systemd1", {"bus" : "session"});
        this.serviceName = serviceName;
        this.updateCallback = updateCallback;
        this._setState(ProcessState.INIT);
        this.startTimestamp = null; // µs since epoch
        this.terminated = false;
        this.subscription = null;
        this.jobSubscription = null;
        this.periodicCheck = null;

        // Watch for start event of the service
        this.jobSubscription = this.systemdClient.subscribe({ interface: I_SD_MGR, member: "JobNew" }, (path, iface, signal, args) => {
            // console.log("JobNew event received:", args);
            if (args[2] == this.serviceName) {
                // console.log("JobNew for our service, checking state");
                this._checkState();
            }
        });

        // Check if it is already running
        // console.log("Checking initial state for service:", this.serviceName);
        this._checkState();
        
        // Start periodic fallback checking in case D-Bus events are missed
        this._startPeriodicStateCheck();
    }

    /* Start long-running process. Only call this in states STOPPED or FAILED.
     * This runs as user, in the user's systemd session.
     * Return cockpit.spawn promise. You need to handle exceptions, but not success.
     */
    run(argv, options) {
        if (this.state !== ProcessState.STOPPED && this.state !== ProcessState.FAILED)
            throw new Error(`cannot start LongRunningProcess in state ${this.state}`);

        // no need to directly react to this -- JobNew and _checkState() will pick up when the unit runs
        // Use SIGINT (Ctrl+C) instead of SIGTERM when stopping the service
        const result = cockpit.spawn(["systemd-run", "--user", "--unit", this.serviceName, "--service-type=oneshot", "--no-block", "--property=KillSignal=SIGINT", "--"].concat(argv),
                             { err: "message", ...options });
        
        // Force immediate state check after starting
        setTimeout(() => {
            // console.log("Forcing state check after run");
            this._checkState();
        }, 200);
        
        return result;
    }

    /*  Stop long-running process while it is RUNNING, or reset a FAILED one */
    terminate() {
        if (this.state !== ProcessState.RUNNING && this.state !== ProcessState.FAILED)
            throw new Error(`cannot terminate LongRunningProcess in state ${this.state}`);

        /* This sends a SIGINT (Ctrl+C) to the unit, causing it to go into "failed" state. This would not
         * happen with `systemd-run -p SuccessExitStatus=0`, but that does not yet work on older
         * OSes with systemd ≤ 241 So let checkState() know that a failure is due to termination. */
        this.terminated = true;
        const result = this.systemdClient.call(O_SD_OBJ, I_SD_MGR, "StopUnit", [this.serviceName, "replace"], { type: "ss" });
        
        // Force immediate state check after terminating
        setTimeout(() => {
            // console.log("Forcing state check after terminate");
            this._checkState();
        }, 200);
        
        return result;
    }

    reset() {
        if (this.state === ProcessState.FAILED) {
            const result = this.systemdClient.call(O_SD_OBJ, I_SD_MGR, "ResetFailedUnit", [this.serviceName], { type: "s" });
            
            // Force immediate state check after reset
            setTimeout(() => {
                // console.log("Forcing state check after reset");
                this._checkState();
            }, 200);
            
            return result;
        } else {
            throw new Error(`cannot reset LongRuningProcess in state ${this.state}`);
        }
    }

    // Start periodic state checking as a fallback
    _startPeriodicStateCheck() {
        if (this.periodicCheck) {
            clearInterval(this.periodicCheck);
        }
        
        // Check every 2 seconds as a fallback for missed D-Bus events
        this.periodicCheck = setInterval(() => {
            // console.log("Periodic state check");
            this._checkState();
        }, 2000);
    }
    
    // Stop periodic state checking  
    _stopPeriodicStateCheck() {
        if (this.periodicCheck) {
            clearInterval(this.periodicCheck);
            this.periodicCheck = null;
        }
    }

    // Clean up subscriptions when the object is no longer needed
    cleanup() {
        if (this.subscription) {
            this.subscription.remove();
            this.subscription = null;
        }
        if (this.jobSubscription) {
            this.jobSubscription.remove();
            this.jobSubscription = null;
        }
        this._stopPeriodicStateCheck();
    }

    /*
     * below are internal private methods
     */

    _setState(state) {
        /* PropertiesChanged often gets fired multiple times with the same values, avoid UI flicker */
        if (state === this.state)
            return;
        
        // console.debug(`LongRunningProcess: State change from ${this.state} to ${state}`);
        this.state = state;
        this.terminated = false;
        if (this.updateCallback)
            this.updateCallback(this);
    }

    _setStateFromProperties(activeState, stateChangeTimestamp) {
        // console.log("Setting state from properties:", activeState, stateChangeTimestamp);
        switch (activeState) {
        case 'activating':
        case 'active':
            this.startTimestamp = stateChangeTimestamp;
            this._setState(ProcessState.RUNNING);
            break;
        case 'failed':
            this.startTimestamp = null; // TODO: can we derive this from InvocationID?
            if (this.terminated) {
                /* terminating causes failure; reset that and do not announce it as failed */
                this.systemdClient.call(O_SD_OBJ, I_SD_MGR, "ResetFailedUnit", [this.serviceName], { type: "s" });
            } else {
                this._setState(ProcessState.FAILED);
            }
            break;
        case 'inactive':
            this._setState(ProcessState.STOPPED);
            break;
        case 'deactivating':
            /* ignore these transitions */
            break;
        default:
            throw new Error(`unexpected state of unit ${this.serviceName}: ${activeState}`);
        }
    }

    // check if the transient unit for our command is running
    _checkState() {
        // console.log("_checkState called for service:", this.serviceName);
        this.systemdClient.call(O_SD_OBJ, I_SD_MGR, "GetUnit", [this.serviceName], { type: "s" })
                .then(([unitObj]) => {
                    // console.log("Unit found:", unitObj);
                    /* Some time may pass between getting JobNew and the unit actually getting activated;
                     * we may get an inactive unit here; watch for state changes. This will also update
                     * the UI if the unit stops. */
                    
                    // Remove existing subscription if any
                    if (this.subscription) {
                        this.subscription.remove();
                        this.subscription = null;
                    }
                    
                    this.subscription = this.systemdClient.subscribe(
                        { interface: I_DBUS_PROP, member: "PropertiesChanged", path: unitObj },
                        (path, iface, signal, args) => {
                            // console.log("PropertiesChanged event:", path, args);
                            if (path === unitObj && args && args[1] && args[1].ActiveState && args[1].StateChangeTimestamp) {
                                // console.log("State change detected:", args[1].ActiveState.v);
                                this._setStateFromProperties(args[1].ActiveState.v, args[1].StateChangeTimestamp.v);
                            }
                        });

                    this.systemdClient.call(unitObj, I_DBUS_PROP, "GetAll", [I_SD_UNIT], { type: "s" })
                            .then(([props]) => {
                                // console.log("Initial properties:", props.ActiveState.v);
                                this._setStateFromProperties(props.ActiveState.v, props.StateChangeTimestamp.v);
                                // Force an immediate callback to update UI
                                if (this.updateCallback) {
                                    this.updateCallback(this);
                                }
                            })
                            .catch(ex => {
                                throw new Error(`unexpected failure of GetAll(${unitObj}): ${ex.toString()}`);
                            });
                })
                .catch(ex => {
                    if (ex.name === "org.freedesktop.systemd1.NoSuchUnit") {
                        // console.log("No such unit, setting to STOPPED");
                        if (this.subscription) {
                            this.subscription.remove();
                            this.subscription = null;
                        }
                        this._setState(ProcessState.STOPPED);
                    } else {
                        throw new Error(`unexpected failure of GetUnit(${this.serviceName}): ${ex.toString()}`);
                    }
                });
    }
}
