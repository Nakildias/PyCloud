// static/toast.js

/**
 * Displays a toast notification.
 * @param {string} message The message to display.
 * @param {string} type The type of toast (e.g., 'info', 'success', 'error', 'warning'). Maps to CSS classes.
 * @param {number} duration Duration in milliseconds before the toast automatically disappears.
 */
function showToast(message, type = 'info', duration = 5000) {
    const containerId = 'toast-container';
    let toastContainer = document.getElementById(containerId);

    // Create container if it doesn't exist
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.id = containerId;
        // Apply necessary styles if they weren't globally set,
        // but it's better to have them in style.css as you already do.
        // toastContainer.style.position = 'fixed';
        // toastContainer.style.top = '20px';
        // toastContainer.style.right = '20px';
        // toastContainer.style.zIndex = '1050';
        // toastContainer.style.display = 'flex';
        // toastContainer.style.flexDirection = 'column-reverse';
        // toastContainer.style.gap = '10px';
        // toastContainer.style.alignItems = 'flex-end';
        document.body.appendChild(toastContainer);
    }

    // Create toast element
    const toast = document.createElement('div');
    toast.classList.add('toast-message');

    // Map Flask categories to CSS classes (adjust if your categories differ)
    let toastTypeClass = 'toast-info'; // Default
    switch (type) {
        case 'success':
            toastTypeClass = 'toast-success';
            break;
        case 'danger': // Flask uses 'danger' for errors
            toastTypeClass = 'toast-error';
            break;
        case 'warning':
            toastTypeClass = 'toast-warning';
            break;
        case 'info':
            toastTypeClass = 'toast-info';
            break;
    }
    toast.classList.add(toastTypeClass);

    toast.textContent = message; // Set the message content

    // Add toast to container
    toastContainer.appendChild(toast);

    // --- Animation and Removal ---

    // 1. Trigger the "show" transition shortly after adding to DOM
    //    This allows the initial state (opacity 0, transform) to be rendered first.
    setTimeout(() => {
        toast.classList.add('toast-show');
    }, 10); // Small delay

    // 2. Start fade out before removing the element
    //    Make this duration slightly less than the full duration to allow fade out effect.
    const fadeOutDuration = 400; // Match CSS transition duration
    setTimeout(() => {
        toast.classList.remove('toast-show');
    }, duration - fadeOutDuration);

    // 3. Remove the element from DOM after the fade out transition completes
    setTimeout(() => {
        if (toast && toast.parentNode === toastContainer) {
            toastContainer.removeChild(toast);
            // Optional: Remove container if it's empty
            if (toastContainer.childElementCount === 0) {
                // document.body.removeChild(toastContainer); // Or just leave it
            }
        }
    }, duration);
}
