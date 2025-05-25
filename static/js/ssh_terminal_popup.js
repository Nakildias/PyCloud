// static/js/ssh_terminal_popup.js
document.addEventListener('DOMContentLoaded', () => {
    const terminalContainer = document.getElementById('ssh-client-terminal-container-popup');
    const popupTerminalTitle = document.getElementById('popup-terminal-title');
    const popupDisconnectButton = document.getElementById('popup-disconnect-button');

    let socket;
    let isConnected = false;
    let passwordBuffer = '';
    let isPasswordPrompt = false;
    let passwordResetTimeout = null;

    // Safely initialize xterm.js Terminal
    let TerminalClass;
    if (typeof window.Terminal === 'function') {
        TerminalClass = window.Terminal;
    } else if (window.Terminal && typeof window.Terminal.Terminal === 'function') {
        TerminalClass = window.Terminal.Terminal;
    } else {
        console.error("Terminal (xterm.js) is not available.");
        // Consider a fallback or a warning for the user
        return;
    }

    const term = new TerminalClass({
        fontFamily: '"Cascadia Code", Consolas, "Liberation Mono", monospace',
        fontSize: 14,
        cursorBlink: true,
        allowTransparency: true,
        theme: {
            background: '#282c34', foreground: '#abb2bf', cursor: '#528bff',
            selection: '#3a3f4b', black: '#282c34', red: '#e06c75',
            green: '#98c379', yellow: '#e5c07b', blue: '#61afef',
            magenta: '#c678dd', cyan: '#56b6c2', white: '#abb2bf',
            brightBlack: '#5c6370', brightRed: '#e06c75', brightGreen: '#98c379',
            brightYellow: '#e5c07b', brightBlue: '#61afef', brightMagenta: '#c678dd',
            brightCyan: '#56b6c2', brightWhite: '#ffffff'
        }
    });

    let fitAddon = null;
    let FitAddonClass;
    if (window.FitAddon && typeof window.FitAddon.FitAddon === 'function') {
        FitAddonClass = window.FitAddon.FitAddon;
        fitAddon = new FitAddonClass();
        term.loadAddon(fitAddon);
    } else {
        console.error("FitAddon is not available.");
    }

    if (window.WebLinksAddon && typeof window.WebLinksAddon.WebLinksAddon === 'function') {
        term.loadAddon(new window.WebLinksAddon.WebLinksAddon());
    } else {
        console.warn("WebLinksAddon is not available, web links in terminal will not be clickable.");
    }

    term.open(terminalContainer);
    term.focus();

    // --- Core term.onData logic ---
    term.onData(data => {
        if (!isConnected || !socket) return;

        const charCode = data.charCodeAt(0);

        // Handle Tab key for completion
        if (charCode === 9) { // ASCII for Tab
            if (isPasswordPrompt) {
                // If it's a password prompt, treat Tab as a regular character or ignore
                // For simplicity, we'll send it as part of the password buffer, but it's unlikely to be useful.
                passwordBuffer += data;
            } else {
                // For regular command input, send Tab to the server for shell completion
                socket.emit('ssh_command', { command: data });
            }
            return; // Prevent default xterm.js behavior if any, and don't process further
        }

        if (isPasswordPrompt) {
            // Password Input Mode: buffer locally, do not echo to terminal
            if (charCode === 13 || charCode === 10) { // Enter key
                socket.emit('ssh_command', { command: passwordBuffer + '\n' });
                passwordBuffer = '';
                if (passwordResetTimeout) clearTimeout(passwordResetTimeout);
                passwordResetTimeout = setTimeout(() => {
                    isPasswordPrompt = false;
                    passwordBuffer = '';
                    passwordResetTimeout = null;
                }, 1000);
            } else if (charCode === 8 || charCode === 127) { // Backspace or Delete
                if (passwordBuffer.length > 0) {
                    passwordBuffer = passwordBuffer.slice(0, -1);
                }
            } else if (data.length === 1 && charCode >= 32 && charCode < 127) { // Printable ASCII
                passwordBuffer += data;
            } else { // Other control characters
                socket.emit('ssh_command', { command: data });
            }
        } else {
            // Regular Command Input Mode: Send raw data to server.
            socket.emit('ssh_command', { command: data });
        }
    });

    // ... (rest of your ssh_terminal_popup.js code remains the same) ...

    function writeToTerminal(text) {
        term.write(text);
    }

    function disconnectSshSession() {
        if (socket && isConnected) {
            socket.emit('ssh_disconnect_request');
            isConnected = false;
        }
    }

    function handleDisconnect() {
        if (socket) {
            socket.disconnect();
        }
        isConnected = false;
        popupTerminalTitle.textContent = "SSH Terminal: Disconnected";
        writeToTerminal("\r\n\x1b[33mSession disconnected.\r\n\x1b[0m");
        if (window.opener && window.opener.postMessage) {
            window.opener.postMessage({ type: 'SSH_DISCONNECTED_FROM_POPUP' }, window.location.origin);
        }
    }

    window.addEventListener('message', (event) => {
        if (event.origin !== window.location.origin) return;

        const data = event.data;

        if (data.type === 'SSH_CONNECT_DETAILS') {
            const { ip, port, username, password, csrf_token } = data;
            console.log('Received connection details in pop-up:', username, ip, port);

            popupTerminalTitle.textContent = `SSH Terminal: ${username}@${ip}`;
            term.reset();
            writeToTerminal(`Attempting to connect to ${username}@${ip}:${port}...\r\n`);

            if (socket) {
                socket.disconnect();
            }

            socket = io({
                path: '/socket.io/',
                transports: ['websocket'],
                auth: {
                    csrf_token: csrf_token
                }
            });

            socket.on('connect', () => {
                console.log('WebSocket connected in pop-up.');
                socket.emit('ssh_connect_request', {
                    ip: ip, port: port, username: username, password: password,
                    cols: term.cols, rows: term.rows
                });
            });

            socket.on('ssh_output', (data) => {
                writeToTerminal(data.output);
                const outputLower = data.output.toLowerCase();
                const currentUsernameValue = username.toLowerCase();

                const passwordPrompts = [
                    'password for ' + currentUsernameValue + ':',
                    '[sudo] password for ' + currentUsernameValue + ':',
                    'password:',
                    'passphrase for key'
                ];

                if (passwordPrompts.some(prompt => outputLower.includes(prompt))) {
                    if (!isPasswordPrompt) {
                        isPasswordPrompt = true;
                        passwordBuffer = '';
                    }
                    if (passwordResetTimeout) {
                        clearTimeout(passwordResetTimeout);
                        passwordResetTimeout = null;
                    }
                } else if (isPasswordPrompt) {
                    const failureMessages = ['sorry, try again', 'incorrect password', 'authentication failed', 'permission denied'];
                    const shellPromptIndicators = [`${username}@`, '$ ', '> ', '# '];

                    if (failureMessages.some(msg => outputLower.includes(msg))) {
                        passwordBuffer = '';
                        if (passwordResetTimeout) clearTimeout(passwordResetTimeout);
                    } else if (shellPromptIndicators.some(p => data.output.includes(p)) && !passwordPrompts.some(prompt => outputLower.includes(prompt))) {
                        isPasswordPrompt = false;
                        passwordBuffer = '';
                        if (passwordResetTimeout) {
                            clearTimeout(passwordResetTimeout);
                            passwordResetTimeout = null;
                        }
                    }
                }
            });

            socket.on('ssh_error', (data) => {
                writeToTerminal(`\x1b[31mError: ${data.message}\r\n\x1b[0m`);
                console.error(`SSH Error: ${data.message}`);
                handleDisconnect();
            });

            socket.on('ssh_connected', () => {
                writeToTerminal('\x1b[32mConnection established.\r\n\x1b[0m');
                isConnected = true;
                if (fitAddon) { // Ensure fitAddon exists before calling fit
                    fitAddon.fit();
                    socket.emit('ssh_resize', { cols: term.cols, rows: term.rows }); // Send initial size
                }
            });

            socket.on('ssh_disconnected', (message) => {
                const disconnectMsg = message ? message : 'SSH disconnected.';
                writeToTerminal(`\r\n\x1b[33m${disconnectMsg}\r\n\x1b[0m`);
                handleDisconnect();
            });

            socket.on('disconnect', (reason) => {
                console.log('WebSocket disconnected in pop-up:', reason);
                if (isConnected) {
                    writeToTerminal(`\x1b[31m\r\nWebSocket disconnected: ${reason}\r\n\x1b[0m`);
                }
                handleDisconnect();
            });

            socket.on('connect_error', (error) => {
                console.error('WebSocket connection error in pop-up:', error);
                writeToTerminal(`\x1b[31m\r\nWebSocket connection error: ${error.message || error}\r\n\x1b[0m`);
                handleDisconnect();
            });
        } else if (data.type === 'SSH_DISCONNECT_REQUEST') {
            console.log('Received disconnect request from opener.');
            disconnectSshSession();
        }
    });

    window.addEventListener('resize', () => {
        if (fitAddon) {
            fitAddon.fit();
            if (isConnected && socket) {
                socket.emit('ssh_resize', { cols: term.cols, rows: term.rows });
            }
        }
    });

    popupDisconnectButton.addEventListener('click', () => {
        disconnectSshSession();
    });

    window.addEventListener('beforeunload', () => {
        if (isConnected) {
            disconnectSshSession();
        }
        if (window.opener && window.opener.postMessage) {
            window.opener.postMessage({ type: 'SSH_DISCONNECTED_FROM_POPUP' }, window.location.origin);
        }
    });

    if (fitAddon) {
        fitAddon.fit();
    }
    term.focus();
    writeToTerminal('Waiting for connection details from main window...\r\n');
});
