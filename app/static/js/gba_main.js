// FlaskGBA/static/js/main.js

import mGBA from './emulator_gba_core.js';

// --- Global Variables ---
let gbaInstance;
let audioContext;
let gbaAudioNode;
let romBuffer = null;
let currentGameName = ""; // To store the base name of the loaded ROM (e.g., "MyGame" from "MyGame.gba")
let gameRunning = false;

// --- DOM Element References ---
const canvas = document.getElementById('gba-canvas');
const romFileInput = document.getElementById('rom-file-input');
const romFileNameSpan = document.getElementById('rom-file-name');
const startButton = document.getElementById('start-button');
const pauseButton = document.getElementById('pause-button');
const resetButton = document.getElementById('reset-button');
const statusMessage = document.getElementById('status-message');

// Save/Load State Buttons (Replaced .sav buttons)
const downloadStateButton = document.getElementById('download-state-button');
const loadStateFileInput = document.getElementById('load-state-file-input');
const stateFileNameSpan = document.getElementById('state-file-name-display');

// Slot-specific Save/Load State Buttons (Existing)
const saveStateButton = document.getElementById('save-state-button');
const loadStateButton = document.getElementById('load-state-button');

// --- Constants ---
const BIOS_EMSC_PATH = "/gba_bios.bin";
const ROM_EMSC_DIR = "/data/games/";
const SAVES_EMSC_DIR = "/data/saves/";
const STATES_EMSC_DIR = "/data/states/";
const GBA_TARGET_FPS = 59.7275;
const GBA_TARGET_FRAME_TIME_MS = 1000 / GBA_TARGET_FPS;
const SAVE_STATE_SLOT = 0; // Default slot for UI buttons


// --- mGBA Configuration Object ---
const mGBAConfig = {
    canvas: canvas,
    mainScriptUrlOrBlob: '/static/js/emulator_gba_core.js',
    print: (text) => console.log('WASM stdout:', text),
    printErr: (text) => console.error('WASM stderr:', text),
    preRun: [],
    onRuntimeInitialized: function() {
        console.log("GBA WASM Core onRuntimeInitialized.");
        if (!gbaInstance) gbaInstance = this;
        initializeAudio();
        if (this.toggleInput) {
            this.toggleInput(true);
            console.log("mGBA input event handling enabled via onRuntimeInitialized.");
        }
        const fs = gbaInstance.FS || FS;
        if (fs && fs.mkdirTree) {
            if (!fs.analyzePath("/data").exists) fs.mkdir("/data");
            if (!fs.analyzePath(ROM_EMSC_DIR).exists) fs.mkdirTree(ROM_EMSC_DIR);
            if (!fs.analyzePath(SAVES_EMSC_DIR).exists) fs.mkdirTree(SAVES_EMSC_DIR);
            if (!fs.analyzePath(STATES_EMSC_DIR).exists) fs.mkdirTree(STATES_EMSC_DIR);
            console.log("Ensured critical Emscripten FS directories exist:", ROM_EMSC_DIR, SAVES_EMSC_DIR, STATES_EMSC_DIR);
        }
    }
};

// --- Initialize mGBA ---
statusMessage.textContent = "Status: Loading emulator core...";
mGBA(mGBAConfig).then(async instance => {
    console.log("mGBA module factory promise resolved. Instance received.");
    if (!gbaInstance) gbaInstance = instance;
    if (!gbaInstance) {
        console.error("Critical: gbaInstance is not available after mGBA promise.");
        statusMessage.textContent = "Status: FATAL - Core instance failed.";
        return;
    }
    statusMessage.textContent = "Status: Initializing mGBA filesystem (FSInit)...";
    if (gbaInstance.FSInit) {
        try {
            await gbaInstance.FSInit();
            console.log("gbaInstance.FSInit() successful.");
        } catch (e) {
            console.error("Error during gbaInstance.FSInit():", e);
            statusMessage.textContent = "Status: Ready for ROM.";
            return;
        }
    } else {
        console.warn("gbaInstance.FSInit not found. Manual FS setup might be needed if not handled by onRuntimeInitialized.");
    }
    statusMessage.textContent = "Status: Loading BIOS...";
    try {
        const fsObject = gbaInstance.FS || FS;
        if (!fsObject || !fsObject.createDataFile) {
            throw new Error("FS.createDataFile is not available for BIOS loading.");
        }
        const response = await fetch("/static/bios/gba_bios.bin");
        if (!response.ok) throw new Error(`HTTP error ${response.status} fetching BIOS.`);
        const biosArrayBuffer = await response.arrayBuffer();
        fsObject.createDataFile("/", "gba_bios.bin", new Uint8Array(biosArrayBuffer), true, false, false);
        console.log("BIOS loaded into Emscripten FS at " + BIOS_EMSC_PATH);
    } catch (err) {
        console.error("Error loading BIOS (post-instance):", err);
        statusMessage.textContent = "Status: Error loading BIOS.";
    }
    statusMessage.textContent = "Status: Core ready. Load a ROM.";
}).catch(err => {
    console.error("Fatal error initializing mGBA module:", err);
    if (err.message && err.message.includes("WebAssembly.Memory") && err.message.includes("Cross-Origin-Opener-Policy")) {
        statusMessage.innerHTML = `Status: Error initializing core. <br>Required COOP/COEP headers might be missing or incorrect. <br>Verify server headers. <br>Error: ${err.name} - ${err.message}`;
    } else {
        statusMessage.textContent = `Status: FATAL - Failed to initialize emulator core. Error: ${err.name}`;
    }
});

// --- Audio Setup ---
async function initializeAudio() {
    if (!window.AudioContext && !window.webkitAudioContext) {
        console.warn("Web Audio API not supported."); return;
    }
    audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const resumeAudio = async () => {
        if (audioContext.state === 'suspended') {
            await audioContext.resume().catch(e => console.error("AudioContext resume failed:", e));
        }
    };
    document.addEventListener('click', resumeAudio, { once: true });
    document.addEventListener('keydown', resumeAudio, { once: true });
    try {
        await audioContext.audioWorklet.addModule('/static/js/gba_audio_processor.js');
        gbaAudioNode = new AudioWorkletNode(audioContext, 'gba-audio-processor');
        gbaAudioNode.connect(audioContext.destination);
        console.log("AudioWorklet initialized.");
    } catch (e) {
        console.error("Failed to initialize AudioWorklet:", e);
    }
}

// --- ROM Loading Event Listener ---
romFileInput.addEventListener('change', async (event) => {
    console.log("romFileInput 'change' event fired.");
    const file = event.target.files[0];

    if (file) {
        if (gbaInstance && romBuffer) {
            console.log("A previous ROM was active. Attempting to unload/quit it first.");
            statusMessage.textContent = "Status: Unloading previous game...";
            if (gameRunning && gbaInstance.pauseGame) {
                try { gbaInstance.pauseGame(); } catch (e) { console.warn("Could not pause game before unloading:", e); }
            }
            if (gbaInstance.quitGame) {
                try { gbaInstance.quitGame(); console.log("Previous game quit successfully."); }
                catch (e) { console.error("Error calling gbaInstance.quitGame():", e); }
            }
        }
        romBuffer = null; gameRunning = false; currentGameName = "";
        console.log("JS state reset for new ROM.");

        if (romFileNameSpan) romFileNameSpan.textContent = file.name;
        statusMessage.textContent = `Status: Loading ${file.name}...`;

        const parts = file.name.split('.');
        if (parts.length > 1) parts.pop();
        currentGameName = parts.join('.');
        console.log(`Current game base name set to: ${currentGameName}`);

        try {
            const loadedFileBuffer = await file.arrayBuffer();
            await loadRomIntoEmulator(file.name, loadedFileBuffer);
        } catch (err) {
            console.error("Error in ROM file 'change' listener (reading or loading):", err);
            statusMessage.textContent = "Status: Error processing ROM.";
            if (romFileNameSpan) romFileNameSpan.textContent = "Error loading ROM";
            romBuffer = null; gameRunning = false; currentGameName = "";
        }
    } else {
        if (romFileNameSpan) romFileNameSpan.textContent = "No ROM selected";
    }
});

async function loadRomIntoEmulator(fileName, loadedFileBuffer) {
    if (!gbaInstance || !(gbaInstance.FS || FS) || !((gbaInstance.FS || FS).createDataFile) || !gbaInstance.loadGame) {
        statusMessage.textContent = "Status: Emulator core or FS not fully ready for ROM loading.";
        romBuffer = null; gameRunning = false; return;
    }
    const fsObject = gbaInstance.FS || FS;
    const romPathInFS = `${ROM_EMSC_DIR}${fileName}`;
    try {
        if (fsObject.analyzePath(romPathInFS).exists) {
            fsObject.unlink(romPathInFS);
        }
        fsObject.createDataFile(ROM_EMSC_DIR, fileName, new Uint8Array(loadedFileBuffer), true, true, false);
        const loadResult = gbaInstance.loadGame(romPathInFS, null);

        if (loadResult) {
            romBuffer = loadedFileBuffer;
            statusMessage.textContent = `Status: ROM "${fileName}" loaded. Press Start.`;
            if (gbaInstance.setMainLoopTiming) {
                gbaInstance.setMainLoopTiming(0, GBA_TARGET_FRAME_TIME_MS);
            }
            if (gbaInstance.FSSync && gbaInstance.saveName) {
                console.log("Syncing FS to load potential existing in-game save data (.sav)...");
                await new Promise((resolve, reject) => {
                    fsObject.syncfs(true, (err) => {
                        if (err) {
                            console.warn("FSSync(true) for loading .sav failed:", err);
                            reject(err);
                        } else {
                            console.log("Filesystem syncfs(true) complete (for loading .sav).");
                            const expectedSaveName = gbaInstance.saveName;
                            if (expectedSaveName && fsObject.analyzePath(expectedSaveName).exists) {
                                console.log(`In-game save file ${expectedSaveName} found in Emscripten FS after sync.`);
                            } else {
                                console.log(`Expected in-game save file ${expectedSaveName || (SAVES_EMSC_DIR + currentGameName + '.sav')} not found after sync.`);
                            }
                            resolve();
                        }
                    });
                });
            }
        } else {
            statusMessage.textContent = `Status: Failed to load ROM "${fileName}" in mGBA core.`;
            romBuffer = null; gameRunning = false; currentGameName = "";
        }
    } catch (e) {
        console.error(`Exception during ROM loading for "${fileName}":`, e);
        statusMessage.textContent = "Status: Exception during ROM load process.";
        romBuffer = null; gameRunning = false; currentGameName = "";
    }
}

// --- Input Handling ---
const gbaKeyMapJsToCore = {
    'ArrowUp': 'up', 'ArrowDown': 'down', 'ArrowLeft': 'left', 'ArrowRight': 'right',
    'KeyZ': 'b', 'KeyX': 'a', 'KeyA': 'l', 'KeyS': 'r',
    'Enter': 'start', 'ShiftRight': 'select', 'Backspace': 'select'
};
function handleGBAInput(eventCode, isPressed) {
    if (!gbaInstance || !gameRunning) return;
    const buttonName = gbaKeyMapJsToCore[eventCode];
    if (buttonName) {
        try {
            if (isPressed) { if (gbaInstance.buttonPress) gbaInstance.buttonPress(buttonName); }
            else { if (gbaInstance.buttonUnpress) gbaInstance.buttonUnpress(buttonName); }
        } catch (e) { console.error(`Input error for ${buttonName}:`, e); }
    }
}
window.addEventListener('keydown', (event) => {
    if (event.repeat) return;
    handleGBAInput(event.code, true);
    if (gameRunning && gbaKeyMapJsToCore[event.code]) event.preventDefault();
});
window.addEventListener('keyup', (event) => {
    handleGBAInput(event.code, false);
    if (gameRunning && gbaKeyMapJsToCore[event.code]) event.preventDefault();
});

// --- Emulation Control Buttons ---
startButton.addEventListener('click', async () => {
    if (!gbaInstance) { statusMessage.textContent = "Status: Emulator core not ready."; return; }
    if (!romBuffer) { statusMessage.textContent = "Status: No ROM loaded."; return; }
    try {
        if (audioContext && audioContext.state === 'suspended') { await audioContext.resume(); }
        if (gbaInstance.setMainLoopTiming) { gbaInstance.setMainLoopTiming(0, GBA_TARGET_FRAME_TIME_MS); }
        if (gbaInstance.resumeGame) {
            gbaInstance.resumeGame();
            gameRunning = true;
            statusMessage.textContent = "Status: Running.";
        } else { gameRunning = false; statusMessage.textContent = "Status: Error: Cannot start."; }
    } catch (e) { gameRunning = false; statusMessage.textContent = "Status: Error during start."; console.error("Error in startButton:", e); }
});

pauseButton.addEventListener('click', () => {
    if (!gbaInstance) { statusMessage.textContent = "Status: Emulator core not ready."; return; }
    if (gameRunning) {
        if (gbaInstance.pauseGame) {
            try {
                gbaInstance.pauseGame();
                gameRunning = false;
                statusMessage.textContent = "Status: Paused.";
            } catch (e) { statusMessage.textContent = "Status: Error pausing."; console.error("Error pausing:", e); }
        } else { statusMessage.textContent = "Status: Error: Cannot pause."; }
    } else if (!romBuffer) {
        statusMessage.textContent = "Status: No ROM loaded to pause.";
    } else {
        statusMessage.textContent = "Status: Already paused or not running.";
    }
});

resetButton.addEventListener('click', async () => {
    if (!gbaInstance) { statusMessage.textContent = "Status: Emulator core not ready."; return; }
    if (!romBuffer) { statusMessage.textContent = "Status: No ROM loaded to reset."; return; }
    if (gbaInstance.quickReload) {
        try {
            gbaInstance.quickReload();
            if (gbaInstance.setMainLoopTiming) { gbaInstance.setMainLoopTiming(0, GBA_TARGET_FRAME_TIME_MS); }
            if (audioContext && audioContext.state === 'suspended') { await audioContext.resume(); }
            if (gbaInstance.resumeGame) {
                gbaInstance.resumeGame();
                gameRunning = true;
                statusMessage.textContent = "Status: Game Reset. Running.";
            } else {
                gameRunning = false;
                statusMessage.textContent = "Status: Game Reset (cannot auto-resume).";
            }
        } catch (e) { gameRunning = false; statusMessage.textContent = "Status: Error resetting game."; console.error("Error resetting:", e); }
    } else { statusMessage.textContent = "Status: Error: Cannot reset."; }
});


// --- Save/Load Functionality ---

// --- New Download Save State (Export state from Slot 0) ---
if (downloadStateButton) {
    downloadStateButton.addEventListener('click', async () => {
        if (!gbaInstance || !romBuffer || !currentGameName) {
            statusMessage.textContent = "Status: No ROM loaded to download state for.";
            console.error("Download State: Pre-conditions not met (no instance, ROM, or game name).");
            return;
        }
        const fsObject = gbaInstance.FS || FS;
        if (!fsObject || !fsObject.readFile || !fsObject.analyzePath || !fsObject.syncfs || !fsObject.readdir ) {
            statusMessage.textContent = "Status: Download state feature not fully available (FS methods missing).";
            console.error("Download State: Critical FS methods (readFile, analyzePath, syncfs, readdir) are not defined on fsObject:", fsObject);
            return;
        }

        statusMessage.textContent = `Status: Preparing state (Slot ${SAVE_STATE_SLOT}) for download...`;
        console.log(`Download State: Initiated for game: "${currentGameName}", slot: ${SAVE_STATE_SLOT}`);
        try {
            // CORRECTED: Use .ss0 extension for slot 0, as observed in logs
            const stateFileExtension = `.ss${SAVE_STATE_SLOT}`;
            const stateFileName = `${currentGameName}${stateFileExtension}`;
            const stateFilePath = `${STATES_EMSC_DIR}${stateFileName}`;
            console.log(`Download State: Expected state file path in MEMFS: "${stateFilePath}"`);

            console.log("Download State: Attempting to sync IDBFS to MEMFS to ensure latest state is loaded...");
            await new Promise((resolve, reject) => {
                fsObject.syncfs(true, (err) => {
                    if (err) {
                        console.error("Download State: Error syncing IDBFS to MEMFS:", err);
                        reject(new Error("Failed to sync filesystem from persistent storage. Original error: " + (err.message || err)));
                    } else {
                        console.log("Download State: IDBFS to MEMFS sync successful.");
                        resolve();
                    }
                });
            });

            console.log(`Download State: Checking existence of file at "${stateFilePath}" in MEMFS after sync.`);
            const pathAnalysis = fsObject.analyzePath(stateFilePath);

            if (!pathAnalysis.exists) {
                console.warn(`Download State: State file "${stateFilePath}" does NOT exist in MEMFS after sync.`);
                console.log("Download State: Path analysis result:", pathAnalysis);
                const statesDirNodePath = STATES_EMSC_DIR.endsWith('/') ? STATES_EMSC_DIR.slice(0, -1) : STATES_EMSC_DIR;
                console.log(`Download State: Checking contents of directory: "${statesDirNodePath}"`);
                const statesDirAnalysis = fsObject.analyzePath(statesDirNodePath);
                if (statesDirAnalysis.exists && statesDirAnalysis.object && statesDirAnalysis.object.isFolder) {
                    try {
                        const filesInStatesDir = fsObject.readdir(statesDirNodePath);
                        console.log(`Download State: Contents of "${statesDirNodePath}":`, filesInStatesDir);
                        if (filesInStatesDir.includes(stateFileName)) {
                            console.log(`Download State: File "${stateFileName}" IS in readdir list! analyzePath might be behaving unexpectedly for this file.`);
                        } else {
                            console.log(`Download State: File "${stateFileName}" is NOT in readdir list. This suggests it's not in MEMFS at "${statesDirNodePath}".`);
                        }
                    } catch (readdirError) {
                        console.error(`Download State: Error listing contents of directory "${statesDirNodePath}":`, readdirError);
                    }
                } else {
                    console.warn(`Download State: Directory "${statesDirNodePath}" does not exist or is not a folder. Analysis:`, statesDirAnalysis);
                }
                statusMessage.textContent = `Status: State file for Slot ${SAVE_STATE_SLOT} (expected: ${stateFileName}) not found. Save it first and ensure sync.`;
                return;
            }

            console.log(`Download State: State file "${stateFilePath}" confirmed to exist in MEMFS. Reading file...`);
            const stateData = fsObject.readFile(stateFilePath);
            console.log(`Download State: Read ${stateData.length} bytes from "${stateFilePath}".`);

            if (stateData && stateData.length > 0) {
                const blob = new Blob([stateData], { type: 'application/octet-stream' });
                const fileNameToDownload = stateFileName;

                const link = document.createElement('a');
                link.href = URL.createObjectURL(blob);
                link.download = fileNameToDownload;
                document.body.appendChild(link);
                link.click();
                document.body.removeChild(link);
                URL.revokeObjectURL(link.href);

                statusMessage.textContent = `Status: State for "${fileNameToDownload}" downloaded.`;
                console.log(`Download State: State data downloaded as "${fileNameToDownload}".`);
            } else {
                statusMessage.textContent = `Status: No state data found for Slot ${SAVE_STATE_SLOT} or file is empty after read.`;
                console.warn(`Download State: readFile for "${stateFilePath}" returned empty or no data, despite the file existing.`);
            }
        } catch (e) {
            statusMessage.textContent = "Status: Error preparing or downloading state data.";
            console.error("Download State: General error during state data download process:", e);
            if (e.message && e.message.includes("Failed to sync filesystem")) {
                statusMessage.textContent = "Status: Filesystem sync error. Cannot download state.";
            }
        }
    });
}

// --- Modal Controls ---
const showControlsModalButton = document.getElementById('show-controls-modal-button');
const controlsModal = document.getElementById('controls-modal');
const closeControlsModalButton = document.getElementById('close-controls-modal-button');

if (showControlsModalButton && controlsModal && closeControlsModalButton) {
    showControlsModalButton.addEventListener('click', () => {
        controlsModal.style.display = 'flex'; // Use 'flex' to align content center
    });

    closeControlsModalButton.addEventListener('click', () => {
        controlsModal.style.display = 'none';
    });

    // Optional: Close modal if user clicks on the overlay (outside the content)
    controlsModal.addEventListener('click', (event) => {
        if (event.target === controlsModal) { // Check if the click is on the overlay itself
            controlsModal.style.display = 'none';
        }
    });
} else {
    console.warn("Modal control buttons or modal element not found. Controls popup might not work.");
}

// --- New Load Save State (Import state to Slot 0) ---
if (loadStateFileInput) {
    loadStateFileInput.addEventListener('change', async (event) => {
        const file = event.target.files[0];
        if (!file) {
            if(stateFileNameSpan) stateFileNameSpan.textContent = "No State selected";
            return;
        }

        if (!gbaInstance || !romBuffer || !currentGameName) {
            statusMessage.textContent = "Status: Load a ROM first before loading a state file.";
            if(stateFileNameSpan) stateFileNameSpan.textContent = "Load ROM first";
            loadStateFileInput.value = "";
            return;
        }

        const fsObject = gbaInstance.FS || FS;
        if (!fsObject || !fsObject.writeFile || !fsObject.mkdirTree || !fsObject.analyzePath || (gbaInstance.FSSync === undefined) || !gbaInstance.loadState) {
            statusMessage.textContent = "Status: Required state load functions not available.";
            console.error("Load State: Critical FS methods, FSSync, or loadState is not defined.");
            loadStateFileInput.value = "";
            return;
        }

        if(stateFileNameSpan) stateFileNameSpan.textContent = file.name;
        statusMessage.textContent = `Status: Loading state from ${file.name} into Slot ${SAVE_STATE_SLOT}...`;

        // CORRECTED: Use .ss0 extension for slot 0
        const stateFileExtension = `.ss${SAVE_STATE_SLOT}`;
        const stateFileNameInFS = `${currentGameName}${stateFileExtension}`;
        const stateFilePathInFS = `${STATES_EMSC_DIR}${stateFileNameInFS}`;
        console.log(`Load State: Target path in Emscripten FS: "${stateFilePathInFS}"`);

        try {
            const fileBuffer = await file.arrayBuffer();
            const uint8Array = new Uint8Array(fileBuffer);

            if (!fsObject.analyzePath(STATES_EMSC_DIR).exists) {
                fsObject.mkdirTree(STATES_EMSC_DIR);
                console.log(`Load State: Created directory ${STATES_EMSC_DIR}`);
            }

            fsObject.writeFile(stateFilePathInFS, uint8Array);
            console.log(`Load State: State file "${file.name}" written to Emscripten FS at "${stateFilePathInFS}".`);

            await gbaInstance.FSSync();
            console.log(`Load State: State file "${stateFilePathInFS}" synced to IndexedDB.`);

            statusMessage.textContent = `Status: State "${file.name}" prepared for Slot ${SAVE_STATE_SLOT}. Loading...`;

            if (gameRunning && gbaInstance.pauseGame) {
                try { gbaInstance.pauseGame(); } catch(e) { console.warn("Load State: Could not pause game before loading state:", e); }
            }

            if (audioContext && audioContext.state === 'suspended') { await audioContext.resume(); }
            const loadSuccess = gbaInstance.loadState(SAVE_STATE_SLOT);

            if (loadSuccess) {
                statusMessage.textContent = `Status: State loaded from "${file.name}" into Slot ${SAVE_STATE_SLOT}. Resuming...`;
                if (gbaInstance.setMainLoopTiming) { gbaInstance.setMainLoopTiming(0, GBA_TARGET_FRAME_TIME_MS); }
                if (gbaInstance.resumeGame) {
                    gbaInstance.resumeGame();
                    gameRunning = true;
                } else {
                    gameRunning = false;
                    statusMessage.textContent = `Status: State loaded from "${file.name}". (Cannot auto-resume).`;
                }
            } else {
                statusMessage.textContent = `Status: Failed to load state from "${file.name}" (Slot ${SAVE_STATE_SLOT}). File might be incompatible or corrupt.`;
                console.warn(`Load State: gbaInstance.loadState(${SAVE_STATE_SLOT}) failed. The file written to "${stateFilePathInFS}" might be an issue, or the internal load mechanism expects something specific from that path.`);
            }

        } catch (uploadProcessError) {
            statusMessage.textContent = "Status: Error processing uploaded state file.";
            console.error("Load State: Error in loadStateFileInput 'change' listener:", uploadProcessError);
        } finally {
            loadStateFileInput.value = "";
        }
    });
}


// Save State (Slot 0 - Existing functionality)
if (saveStateButton) {
    saveStateButton.addEventListener('click', async () => {
        if (!gbaInstance || !romBuffer) {
            statusMessage.textContent = "Status: No ROM loaded to save state.";
            return;
        }
        if (!gbaInstance.saveState || (gbaInstance.FSSync === undefined)) {
            statusMessage.textContent = "Status: Save state feature not available.";
            console.error("Save State: gbaInstance.saveState or FSSync is undefined.");
            return;
        }
        statusMessage.textContent = `Status: Saving state to slot ${SAVE_STATE_SLOT}...`;
        try {
            const success = gbaInstance.saveState(SAVE_STATE_SLOT);
            if (success) {
                await gbaInstance.FSSync();
                statusMessage.textContent = `Status: State saved to slot ${SAVE_STATE_SLOT}.`;
                // Log the expected filename based on .ss0 for verification
                const stateFileExtension = `.ss${SAVE_STATE_SLOT}`;
                const expectedFileName = `${currentGameName}${stateFileExtension}`;
                console.log(`Save State: Slot ${SAVE_STATE_SLOT} saved and synced. Expected file in ${STATES_EMSC_DIR}: ${expectedFileName}`);
            } else {
                statusMessage.textContent = `Status: Failed to save state to slot ${SAVE_STATE_SLOT}.`;
                console.error(`Save State: gbaInstance.saveState(${SAVE_STATE_SLOT}) returned false.`);
            }
        } catch (e) {
            statusMessage.textContent = "Status: Error saving state.";
            console.error("Save State: Error saving state:", e);
        }
    });
}

// Load State (Slot 0 - Existing functionality)
if (loadStateButton) {
    loadStateButton.addEventListener('click', async () => {
        if (!gbaInstance || !romBuffer) {
            statusMessage.textContent = "Status: No ROM loaded to load state from.";
            return;
        }
        if (!gbaInstance.loadState) {
            statusMessage.textContent = "Status: Load state feature not available.";
            return;
        }

        const fsObject = gbaInstance.FS || FS;
        if (fsObject && fsObject.syncfs) {
            // Log the expected filename for context
            const stateFileExtension = `.ss${SAVE_STATE_SLOT}`;
            const expectedFileName = `${currentGameName}${stateFileExtension}`;
            statusMessage.textContent = `Status: Syncing states from storage for Slot ${SAVE_STATE_SLOT} (expecting ${expectedFileName})...`;
            console.log(`Load State (Button): Syncing for Slot ${SAVE_STATE_SLOT}, expecting ${STATES_EMSC_DIR}${expectedFileName}`);
            try {
                await new Promise((resolve, reject) => { // Modified to reject on error
                    fsObject.syncfs(true, (err) => {
                        if (err) {
                            console.warn("Load State (Button): Error syncing FS from persistent storage before loadState:", err);
                            reject(new Error("Failed to sync for Load State button. " + (err.message || err) ));
                        } else {
                            console.log("Load State (Button): FS synced from persistent storage before loadState.");
                            resolve();
                        }
                    });
                });
            } catch (e) {
                console.warn("Load State (Button): Exception during pre-loadState FS sync:", e);
                statusMessage.textContent = "Status: Error syncing filesystem for load.";
                // Optionally, do not proceed if sync fails critically
                // return;
            }
        }

        statusMessage.textContent = `Status: Loading state from slot ${SAVE_STATE_SLOT}...`;
        try {
            if (audioContext && audioContext.state === 'suspended') { await audioContext.resume(); }

            const success = gbaInstance.loadState(SAVE_STATE_SLOT);
            if (success) {
                statusMessage.textContent = `Status: State loaded from slot ${SAVE_STATE_SLOT}. Resuming...`;
                if (gbaInstance.setMainLoopTiming) { gbaInstance.setMainLoopTiming(0, GBA_TARGET_FRAME_TIME_MS); }
                if (gbaInstance.resumeGame) {
                    gbaInstance.resumeGame();
                    gameRunning = true;
                } else {
                    gameRunning = false;
                    statusMessage.textContent = `Status: State loaded from slot ${SAVE_STATE_SLOT}. (Cannot auto-resume).`;
                }
            } else {
                statusMessage.textContent = `Status: Failed to load state from slot ${SAVE_STATE_SLOT}. (Is ${currentGameName}.ss${SAVE_STATE_SLOT} present and valid?).`;
                console.error(`Load State (Button): gbaInstance.loadState(${SAVE_STATE_SLOT}) returned false.`);
            }
        } catch (e) {
            statusMessage.textContent = "Status: Error loading state.";
            console.error("Load State (Button): Error loading state:", e);
        }
    });
}
