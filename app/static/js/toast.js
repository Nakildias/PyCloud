// static/js/toast.js

/**
 * Displays a toast notification.
 * @param {string} message The message to display.
 * @param {string} type The type of toast (e.g., 'info', 'success', 'error', 'warning'). Maps to CSS classes.
 * @param {number} duration Duration in milliseconds before the toast automatically disappears.
 */
function showToast(message, type = 'info', duration = 5000) {
    console.log('[Toast.js] showToast CALLED. Message:', message, 'Type:', type, 'Duration:', duration);

    const containerId = 'base-toast-container';
    let toastContainer = document.getElementById(containerId);

    if (!toastContainer) {
        console.warn('[Toast.js] Toast container #base-toast-container not found in DOM. Attempting to create dynamically...');
        toastContainer = document.createElement('div');
        toastContainer.id = containerId;
        toastContainer.classList.add('base-toast-container-wrapper'); // Ensure this class matches your CSS for positioning
        document.body.appendChild(toastContainer);
        console.log('[Toast.js] Dynamically created and appended toast container:', toastContainer);
    } else {
        console.log('[Toast.js] Found toast container element:', toastContainer);
    }

    // Create toast element
    const toast = document.createElement('div');
    toast.classList.add('base-toast-message');

    let toastTypeClass = 'toast-info'; // Default modifier class
    switch (type) {
        case 'success':
            toastTypeClass = 'toast-success';
            break;
        case 'danger': // Flask typically uses 'danger' for errors
            toastTypeClass = 'toast-error';
            break;
        case 'warning':
            toastTypeClass = 'toast-warning';
            break;
        case 'info':
            toastTypeClass = 'toast-info';
            break;
        default:
            console.warn(`[Toast.js] Unknown toast type category '${type}', using default 'toast-info'.`);
            break;
    }
    toast.classList.add(toastTypeClass);
    console.log('[Toast.js] Applied type class:', toastTypeClass);

    toast.textContent = message;
    toastContainer.appendChild(toast);
    console.log('[Toast.js] Toast element appended to container. Current children count:', toastContainer.children.length);

    // Short delay to allow CSS transitions to apply after append
    setTimeout(() => {
        toast.classList.add('toast-show'); // Modifier class for showing (triggers fade-in/appear animation)
    console.log('[Toast.js] Applied "toast-show" class. Toast should be visible if CSS is correct.');
    }, 10); // 10ms delay

    const fadeOutStartDelay = duration - 400; // Assuming 400ms fade-out
    const removalDelay = duration;

    if (fadeOutStartDelay < 0) {
        console.warn("[Toast.js] Toast duration is less than fadeOutDuration. Toast may not fade out as expected.");
    }

    setTimeout(() => {
        toast.classList.remove('toast-show'); // Triggers fade-out animation
        console.log('[Toast.js] Removed "toast-show" class to start fade-out for message:', message);
    }, Math.max(0, fadeOutStartDelay)); // Ensure delay is not negative

    setTimeout(() => {
        if (toast && toast.parentNode === toastContainer) {
            toastContainer.removeChild(toast);
            console.log('[Toast.js] Removed toast element from DOM for message:', message);
        } else if (toast) {
            console.warn('[Toast.js] Toast element was not a child of the container during removal attempt, or toast was null for message:', message);
        }
    }, Math.max(10, removalDelay)); // Ensure removal is not before fadeOut
}

// This function is INTENDED to be called EXPLICITLY from base.html
function processFlashedMessagesOnLoad() {
    console.log('[Toast.js] processFlashedMessagesOnLoad CALLED EXPLICITLY.');
    if (typeof window.flashedMessages !== 'undefined' && Array.isArray(window.flashedMessages)) {
        if (window.flashedMessages.length > 0) {
            console.log('[Toast.js] flashedMessages found by processFlashedMessagesOnLoad:', JSON.stringify(window.flashedMessages));
        } else {
            console.log('[Toast.js] flashedMessages array is empty (called by processFlashedMessagesOnLoad). No toasts to show from flashed messages.');
            return; // Exit if no messages
        }

        // Create a copy to iterate over, in case the original array is modified elsewhere or by showToast (unlikely)
        const messagesToProcess = [...window.flashedMessages];

        messagesToProcess.forEach(function(flashTuple, index) {
            console.log(`[Toast.js] Processing flashTuple #${index} (called by processFlashedMessagesOnLoad):`, flashTuple);
            if (flashTuple && flashTuple.length === 2) {
                const category = flashTuple[0];
                const message = flashTuple[1];
                showToast(message, category);
            } else {
                console.warn('[Toast.js] Invalid flashTuple structure in processFlashedMessagesOnLoad:', flashTuple);
            }
        });

        // Clear the global array after processing to prevent re-display if this function is accidentally called again
        // or on certain types of page/JS reloads without a full Flask request.
        console.log('[Toast.js] Clearing window.flashedMessages after processing.');
        window.flashedMessages = [];
    } else {
        console.log('[Toast.js] window.flashedMessages is undefined or not an array when processFlashedMessagesOnLoad was called.');
    }
}

// Ensure NO document.addEventListener('DOMContentLoaded', ...) listener here
// that also calls processFlashedMessagesOnLoad() or directly processes window.flashedMessages.
// The call should only come from the inline script in base.html.
