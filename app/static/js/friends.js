// static/js/friends.js
document.addEventListener('DOMContentLoaded', () => {
    // Ensure CSRF token is available if needed for future API calls from this page
    const csrfTokenEl = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfTokenEl ? csrfTokenEl.getAttribute('content') : null;

    // URLs and data from the template
    // These are assumed to be available globally or passed via data attributes/script tags
    // For example, API_USERS_ACTIVITY_STATUS_URL would be defined in base.html or similar
    const activityStatusApiUrl = typeof API_USERS_ACTIVITY_STATUS_URL !== 'undefined' ? API_USERS_ACTIVITY_STATUS_URL : null;
    const friendsDataRaw = document.getElementById('friends-data-json')?.textContent;
    const initialFriendStatusesRaw = document.getElementById('initial-friend-statuses-json')?.textContent;

    let friendsData = [];
    if (friendsDataRaw) {
        try {
            friendsData = JSON.parse(friendsDataRaw);
        } catch (e) {
            console.error("Error parsing friends-data-json:", e);
        }
    }

    let initialFriendStatuses = {};
    if (initialFriendStatusesRaw) {
        try {
            initialFriendStatuses = JSON.parse(initialFriendStatusesRaw);
        } catch (e) {
            console.error("Error parsing initial-friend-statuses-json:", e);
        }
    }


    // Initialize friend list interactions
    const friendListItems = document.querySelectorAll('.fr-item'); // UPDATED CLASS
    friendListItems.forEach(item => {
        item.addEventListener('click', function() {
            const friendId = this.dataset.friendId;
            const friendUsername = this.dataset.friendUsername;
            const friendPfp = this.dataset.friendPfp; // pfp filename

            // Call the global function from base_friend_chat.js to open the embedded chat
            if (window.openEmbeddedChat) {
                window.openEmbeddedChat(friendId, friendUsername, friendPfp);
            } else {
                console.error('Embedded chat function (openEmbeddedChat) not found.');
                if (window.showToast) { // Check if showToast is available
                    window.showToast('Could not open chat. Please try again later.', 'danger');
                }
            }
        });
    });


    // --- Activity Status Update Logic ---
    function updateActivityStatuses() {
        if (!activityStatusApiUrl || friendsData.length === 0 || !csrfToken) {
            if (!activityStatusApiUrl) console.warn("Activity status API URL not defined.");
            if (!csrfToken) console.warn("CSRF token not available for activity status update.");
            return;
        }

        const friendIds = friendsData; // friendsData is now just the list of IDs
        if (friendIds.length === 0) return;

        fetch(activityStatusApiUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ user_ids: friendIds })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`Network response was not ok: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            if (data.user_statuses) {
                for (const userId in data.user_statuses) {
                    const status = data.user_statuses[userId]; // 'online', 'afk', 'offline'
                    // IDs for status indicators and text are kept as is (dynamic)
                    const indicator = document.getElementById(`status-indicator-${userId}`);
                    const statusTextElement = document.getElementById(`status-text-${userId}`);

                    if (indicator) {
                        // Remove old status classes, add new one
                        indicator.classList.remove('online', 'afk', 'offline');
                        indicator.classList.add(status); // Assumes status string matches CSS class
                    }
                    if (statusTextElement) {
                        let displayStatus = 'Offline'; // Default
                        if (status === 'online') displayStatus = 'Online';
                        else if (status === 'afk') displayStatus = 'Away';
                        statusTextElement.textContent = displayStatus;
                    }
                }
            }
        })
        .catch(error => console.error('Error fetching activity statuses:', error));
    }

    // Initial status update and set interval for polling
    if (friendsData.length > 0) {
        // Set initial statuses based on what was passed from the template
        for (const friendId in initialFriendStatuses) {
            const status = initialFriendStatuses[friendId];
            const indicator = document.getElementById(`status-indicator-${friendId}`);
            const statusTextElement = document.getElementById(`status-text-${friendId}`);
            if (indicator) {
                indicator.classList.remove('online', 'afk', 'offline');
                indicator.classList.add(status);
            }
            if (statusTextElement) {
                let displayStatus = 'Offline';
                if (status === 'online') displayStatus = 'Online';
                else if (status === 'afk') displayStatus = 'Away';
                statusTextElement.textContent = displayStatus;
            }
        }
        // Start polling for updates
        if (activityStatusApiUrl && csrfToken) {
            updateActivityStatuses(); // Initial call to get latest
            setInterval(updateActivityStatuses, 30000); // Poll every 30 seconds
        }
    }
    // --- End Activity Status Update Logic ---
});
