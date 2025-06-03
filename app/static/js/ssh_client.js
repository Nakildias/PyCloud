// static/js/ssh_client.js
document.addEventListener('DOMContentLoaded', () => {
    // Form Elements
    const connectForm = document.getElementById('ssh-connect-form');
    const ipInput = document.getElementById('ssh-client-input-ip');
    const portInput = document.getElementById('ssh-client-input-port');
    const usernameInput = document.getElementById('ssh-client-input-username');
    const passwordInput = document.getElementById('ssh-client-input-password');
    const connectButton = connectForm.querySelector('.ssh-client-btn-connect');
    const formDisconnectButton = connectForm.querySelector('.ssh-client-btn-disconnect');

    let sshWindow = null; // To keep a reference to the pop-out window

    // Function to set initial connection state UI on the main page
    function setConnectionState(connected) {
        connectButton.style.display = connected ? 'none' : 'inline-block';
        formDisconnectButton.style.display = connected ? 'inline-block' : 'none';
        // Enable/disable form inputs based on connection state
        [ipInput, portInput, usernameInput, passwordInput].forEach(el => el.disabled = connected);
    }

    // Connect Form Submission
    connectForm.addEventListener('submit', (e) => {
        e.preventDefault();
        if (sshWindow && !sshWindow.closed) {
            if (window.showToast) window.showToast('SSH terminal already open.', 'info');
            sshWindow.focus(); // Bring existing window to front
            return;
        }

        const ip = ipInput.value.trim();
        const port = portInput.value.trim();
        const username = usernameInput.value.trim();
        const sshPasswordVal = passwordInput.value;

        if (!ip || !port || !username) {
            if (window.showToast) window.showToast('IP, Port, and Username are required.', 'warning');
            return;
        }

        // Open a new pop-out window
        // The URL should point to the Flask route that renders ssh_terminal_popup.html
        const popupUrl = `/tools/ssh_terminal_popup`; // Assuming you'll create this route
        const windowFeatures = 'width=1000,height=600,resizable=yes,scrollbars=no,status=no,titlebar=yes';

        sshWindow = window.open(popupUrl, '_blank', windowFeatures);

        if (!sshWindow) {
            if (window.showToast) window.showToast('Pop-up blocked! Please allow pop-ups for this site.', 'danger');
            return;
        }

        // Pass connection details to the new window after it loads
        sshWindow.onload = () => {
            if (sshWindow.postMessage) {
                sshWindow.postMessage({
                    type: 'SSH_CONNECT_DETAILS',
                    ip: ip,
                    port: port,
                    username: username,
                    password: sshPasswordVal,
                    csrf_token: typeof CSRF_TOKEN !== 'undefined' ? CSRF_TOKEN : ''
                }, window.location.origin); // Specify origin for security
            } else {
                console.error("PostMessage is not supported by the pop-up window.");
                if (window.showToast) window.showToast('Pop-up window communication failed.', 'danger');
                sshWindow.close();
            }
        };

        // Listen for messages from the pop-out window (e.g., disconnection event)
        window.addEventListener('message', (event) => {
            if (event.origin !== window.location.origin) return; // Verify the origin

            if (event.data && event.data.type === 'SSH_DISCONNECTED_FROM_POPUP') {
                console.log('Received disconnection event from pop-up.');
                setConnectionState(false);
                if (sshWindow && !sshWindow.closed) {
                    sshWindow.close(); // Ensure it's closed
                }
            }
        });

        // Detect when the pop-out window is closed manually by the user
        const checkPopupClosed = setInterval(() => {
            if (sshWindow && sshWindow.closed) {
                console.log('Pop-out window was closed by the user.');
                setConnectionState(false);
                clearInterval(checkPopupClosed);
            }
        }, 500);

        setConnectionState(true); // Update UI on main page as "connected"
    });

    // Disconnect button on the main form
    formDisconnectButton.addEventListener('click', () => {
        if (sshWindow && !sshWindow.closed) {
            // Send a message to the pop-out window to initiate disconnect
            if (sshWindow.postMessage) {
                sshWindow.postMessage({ type: 'SSH_DISCONNECT_REQUEST' }, window.location.origin);
            }
        } else {
            setConnectionState(false); // Update UI if state is inconsistent
        }
    });

    // Initial setup
    setConnectionState(false);
});
