document.addEventListener('DOMContentLoaded', function() {
    const csrfTokenEl = document.querySelector('meta[name="csrf-token"]');
    if (!csrfTokenEl) {
        console.error("CSRF token not found in notifications.js");
        return;
    }
    const csrfToken = csrfTokenEl.getAttribute('content');

    // Dismiss individual notification
    document.querySelectorAll('.notif-btn-dismiss').forEach(button => { // UPDATED CLASS
        button.addEventListener('click', function() {
            const notificationId = this.dataset.notificationId;
            const notificationItem = this.closest('.notif-item'); // UPDATED CLASS

            fetch(`/api/notifications/dismiss/${notificationId}`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    if (typeof showToast === 'function') showToast(data.message, 'success');
                    if (notificationItem) {
                        notificationItem.style.transition = 'opacity 0.5s ease, transform 0.5s ease'; // Added transform
                        notificationItem.style.opacity = '0';
                        notificationItem.style.transform = 'scale(0.95)'; // Shrink effect
                        setTimeout(() => {
                            notificationItem.remove();
                            // Check if the list is empty and show message
                            if (document.querySelectorAll('.notif-item').length === 0) { // UPDATED CLASS
                                const container = document.querySelector('.notif-page-container'); // UPDATED CLASS
                                if(container) {
                                    // Remove pagination if it exists
                                    const pagination = container.querySelector('.notif-pagination-nav');
                                    if(pagination) pagination.remove();

                                    // Remove "Mark all read" button if it exists
                                    const markAllReadBtn = document.getElementById('mark-all-read-btn'); // ID is kept
                                    if(markAllReadBtn) markAllReadBtn.closest('.notif-actions-bar').remove(); // Remove whole actions bar

                                    container.insertAdjacentHTML('beforeend', '<p class="notif-no-notifications-message">You have no notifications.</p>'); // UPDATED CLASS
                                }
                            }
                        }, 500);
                    }
                    // Update unread count in nav using the global function from base_notification.js
                    if (window.updateGlobalUnreadCount) {
                        window.updateGlobalUnreadCount(data.unread_count);
                    }
                } else {
                    if (typeof showToast === 'function') showToast(data.message || 'Error dismissing notification.', 'error');
                }
            })
            .catch(error => {
                console.error('Error dismissing notification:', error);
                if (typeof showToast === 'function') showToast('Client-side error dismissing notification.', 'error');
            });
        });
    });

    // Mark all as read
    const markAllReadButton = document.getElementById('mark-all-read-btn'); // ID is kept
    if (markAllReadButton) {
        markAllReadButton.addEventListener('click', function() {
            fetch(`/api/notifications/mark_all_read`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
            })
            .then(response => response.json())
            .then(data => {
                if (data.status === 'success') {
                    if (typeof showToast === 'function') showToast(data.message, 'success');
                    document.querySelectorAll('.notif-item.unread').forEach(item => { // UPDATED CLASS
                        item.classList.remove('unread');
                        item.querySelector('.notif-unread-indicator')?.remove(); // UPDATED CLASS
                    });
                    if (window.updateGlobalUnreadCount) { // Use global function
                        window.updateGlobalUnreadCount(0);
                    }
                    this.disabled = true;
                    this.textContent = 'All Read'; // Update button text
                } else {
                    if (typeof showToast === 'function') showToast(data.message || 'Error marking all as read.', 'error');
                }
            })
            .catch(error => {
                console.error('Error marking all as read:', error);
                if (typeof showToast === 'function') showToast('Client-side error marking all as read.', 'error');
            });
        });
    }

    // Convert timestamps to "time ago" - target the new class
    document.querySelectorAll('.notif-timestamp').forEach(function(element) { // UPDATED CLASS
        const timestamp = element.getAttribute('title'); // Assuming title attribute still holds ISO string
        if (timestamp) {
            element.textContent = timeSince(new Date(timestamp)) + ' ago';
        }
    });
});

// Helper function for "time since" - remains the same
function timeSince(date) {
    const seconds = Math.floor((new Date() - date) / 1000);
    let interval = seconds / 31536000;
    if (interval > 1) return Math.floor(interval) + " year" + (Math.floor(interval) > 1 ? "s" : "");
    interval = seconds / 2592000;
    if (interval > 1) return Math.floor(interval) + " month" + (Math.floor(interval) > 1 ? "s" : "");
    interval = seconds / 86400;
    if (interval > 1) return Math.floor(interval) + " day" + (Math.floor(interval) > 1 ? "s" : "");
    interval = seconds / 3600;
    if (interval > 1) return Math.floor(interval) + " hour" + (Math.floor(interval) > 1 ? "s" : "");
    interval = seconds / 60;
    if (interval > 1) return Math.floor(interval) + " minute" + (Math.floor(interval) > 1 ? "s" : "");
    if (seconds < 10) return "just now";
    return Math.floor(seconds) + " second" + (Math.floor(seconds) > 1 ? "s" : "");
}
