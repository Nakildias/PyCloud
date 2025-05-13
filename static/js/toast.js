// static/js/toast.js

/**
 * Displays a toast notification.
 * @param {string} message The message to display.
 * @param {string} type The type of toast (e.g., 'info', 'success', 'error', 'warning'). Maps to CSS classes.
 * @param {number} duration Duration in milliseconds before the toast automatically disappears.
 */
function showToast(message, type = 'info', duration = 5000) {
    // Use the ID defined in base.html for the container
    const containerId = 'base-toast-container'; // Updated ID
    let toastContainer = document.getElementById(containerId);

    // Create container if it doesn't exist (should always exist from base.html)
    if (!toastContainer) {
        console.warn('Toast container #base-toast-container not found. Creating dynamically, but it should be in base.html.');
        toastContainer = document.createElement('div');
        toastContainer.id = containerId;
        // Add class for styling if it was missed in base.html
        toastContainer.classList.add('base-toast-container-wrapper');
        document.body.appendChild(toastContainer);
    }

    // Create toast element
    const toast = document.createElement('div');
    toast.classList.add('base-toast-message'); // Updated class

    // Map Flask categories to CSS classes
    let toastTypeClass = 'toast-info'; // Default modifier class
    switch (type) {
        case 'success':
            toastTypeClass = 'toast-success';
            break;
        case 'danger':
            toastTypeClass = 'toast-error';
            break;
        case 'warning':
            toastTypeClass = 'toast-warning';
            break;
        case 'info':
            toastTypeClass = 'toast-info';
            break;
    }
    toast.classList.add(toastTypeClass); // Add modifier class like .toast-success

    toast.textContent = message;

    toastContainer.appendChild(toast);

    setTimeout(() => {
        toast.classList.add('toast-show'); // Modifier class for showing
    }, 10);

    const fadeOutDuration = 400;
    setTimeout(() => {
        toast.classList.remove('toast-show');
    }, duration - fadeOutDuration);

    setTimeout(() => {
        if (toast && toast.parentNode === toastContainer) {
            toastContainer.removeChild(toast);
        }
    }, duration);
}
