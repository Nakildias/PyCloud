// static/js/base_notification.js

document.addEventListener('DOMContentLoaded', function() {
    // --- Display Flashed Messages ---
    // Assumes 'flashedMessages' is made available globally by an inline script in base.html
    if (typeof flashedMessages !== 'undefined' && flashedMessages && flashedMessages.length > 0) {
        flashedMessages.forEach(function(flash) {
            const category = flash[0];
            const message = flash[1];
            // Assumes showToast is globally available from toast.js
            if (typeof showToast === 'function') {
                showToast(message, category);
            } else {
                console.warn('showToast function not found. Flashed message:', message);
            }
        });
    }

    // --- Navbar Unread Notification Count Script ---
    // Assumes CURRENT_USER_ID is globally available
    if (typeof CURRENT_USER_ID !== 'undefined' && CURRENT_USER_ID !== null) {
        // UPDATED ID HERE
        const unreadCountElement = document.getElementById('base-notification-unread-count');
        if (!unreadCountElement) {
            // console.warn("Unread count element #base-notification-unread-count not found."); // Optional: more verbose warning
            return;
        }

        // Assumes API_UNREAD_NOTIFICATION_COUNT_URL is globally available
        if (typeof API_UNREAD_NOTIFICATION_COUNT_URL === 'undefined') {
            console.error("API_UNREAD_NOTIFICATION_COUNT_URL is not defined. Cannot fetch notification count.");
            return;
        }
        const notificationSoundUrl = (typeof NOTIFICATION_SOUND_URL !== 'undefined') ? NOTIFICATION_SOUND_URL : null;
        let notificationSound;
        if (notificationSoundUrl) {
            notificationSound = new Audio(notificationSoundUrl);
            notificationSound.preload = 'auto';
        }


        let previousUnreadCount = 0;
        let isInitialNotificationFetch = true;

        let focusedNotificationInterval = 5000; // Poll every 5 seconds when focused
        let blurredNotificationInterval = 10000; // Poll every 10 seconds when blurred
        let currentNotificationInterval = focusedNotificationInterval;
        let notificationPollTimerId = null;

        function stopNotificationPolling() {
            if (notificationPollTimerId) {
                clearInterval(notificationPollTimerId);
                notificationPollTimerId = null;
            }
        }

        function startNotificationPolling() {
            stopNotificationPolling(); // Clear existing timer before starting a new one
            notificationPollTimerId = setInterval(fetchUnreadCount, currentNotificationInterval);
            fetchUnreadCount(); // Initial fetch
        }

        function fetchUnreadCount() {
            fetch(API_UNREAD_NOTIFICATION_COUNT_URL)
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    const newUnreadCount = parseInt(data.unread_count, 10) || 0;
                    if (newUnreadCount > previousUnreadCount && !isInitialNotificationFetch && notificationSound) {
                        notificationSound.play().catch(error => console.warn("Notification sound failed to play.", error));
                    }
                    unreadCountElement.textContent = newUnreadCount > 0 ? newUnreadCount : '';
                    unreadCountElement.style.display = newUnreadCount > 0 ? 'inline-block' : 'none';
                    previousUnreadCount = newUnreadCount;
                    if (isInitialNotificationFetch) isInitialNotificationFetch = false;
                } else {
                    console.error('Failed to fetch navbar unread count:', data.message);
                    if (isInitialNotificationFetch) isInitialNotificationFetch = false; // Ensure flag is reset even on error
                }
            })
            .catch(error => {
                console.error('Error fetching navbar unread count:', error);
                if (isInitialNotificationFetch) isInitialNotificationFetch = false; // Ensure flag is reset on network error
            });
        }

        // Set initial interval based on focus and start polling
        currentNotificationInterval = document.hasFocus() ? focusedNotificationInterval : blurredNotificationInterval;
        startNotificationPolling();

        // Expose a global function to allow other scripts (like notifications.js) to update the count
        window.updateGlobalUnreadCount = function(count) {
            const currentCount = parseInt(count, 10) || 0;
            unreadCountElement.textContent = currentCount > 0 ? currentCount : '';
            unreadCountElement.style.display = currentCount > 0 ? 'inline-block' : 'none';
            previousUnreadCount = currentCount; // Update previous count to avoid sound on manual update
        };

        // Adjust polling interval based on window focus/blur
        window.addEventListener('blur', () => {
            currentNotificationInterval = blurredNotificationInterval;
            startNotificationPolling(); // Restart with new interval
        });
        window.addEventListener('focus', () => {
            currentNotificationInterval = focusedNotificationInterval;
            startNotificationPolling(); // Restart with new interval
            fetchUnreadCount(); // Also fetch immediately on focus
        });
    }
});
