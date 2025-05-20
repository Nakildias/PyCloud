// static/js/base_friend_chat.js

// Ensure global constants from base.html are loaded before this script.
// e.g., CURRENT_USER_ID, CSRF_TOKEN, STATIC_PFP_PATH_BASE, EMB_DM_HISTORY_API_URL_BASE, API_USERS_ACTIVITY_STATUS_URL, etc.

document.addEventListener('DOMContentLoaded', () => {
    if (typeof CURRENT_USER_ID === 'undefined' || CURRENT_USER_ID === null) {
        return;
    }
    if (typeof EMB_DM_HISTORY_API_URL_BASE === 'undefined' ||
        typeof EMB_DM_SEND_API_URL_BASE === 'undefined' ||
        typeof EMB_DM_RECENT_MESSAGES_API_URL === 'undefined' ||
        typeof STATIC_PFP_PATH_BASE === 'undefined' ||
        typeof STATIC_ICONS_PATH_BASE === 'undefined' ||
        typeof USER_PROFILE_URL_BASE === 'undefined' ||
        typeof MAX_UPLOAD_MB_CONFIG === 'undefined' ||
        typeof CSRF_TOKEN === 'undefined' ||
        typeof API_USERS_ACTIVITY_STATUS_URL === 'undefined') {
        console.error("One or more required global constants for embedded chat are missing. Embedded chat will not initialize.");
    return;
        }

        const embeddedChatContainer = document.getElementById('base-embedded-chat-container');
        if (!embeddedChatContainer) {
            return;
        }

        let openChats = {}; // Stores state for all chats (minimized, maximized, explicitly closed)
let chatBubbles = {}; // Stores DOM elements for active bubbles only
const MAX_OPEN_CHAT_BOXES = 3;

const EMB_CHAT_FOCUSED_POLLING_INTERVAL = 3000;
const EMB_CHAT_BLURRED_POLLING_INTERVAL = 7000;
let currentEmbChatPollingInterval = EMB_CHAT_FOCUSED_POLLING_INTERVAL;
let embChatPollTimerId = null;

const RECENT_MSG_POLLING_INTERVAL = 10000;
let recentMsgPollTimerId = null;
const notificationSoundUrl = (typeof NOTIFICATION_SOUND_URL !== 'undefined') ? NOTIFICATION_SOUND_URL : null;
let notificationSound;
if (notificationSoundUrl) {
    notificationSound = new Audio(notificationSoundUrl);
    notificationSound.preload = 'auto';
}

// Initial setup
loadChatStates();
renderInitialChats(); // This will decide what to show based on loaded states
startRecentMessagesPolling();

// Start polling for active chats only if there are any non-minimized, non-closed chats initially
if (Object.values(openChats).some(chat => chat.element && !chat.minimized && !chat.isExplicitlyClosed)) {
    startActiveChatsPolling();
}

// Window focus/blur handlers to adjust polling interval
window.addEventListener('blur', () => {
    currentEmbChatPollingInterval = EMB_CHAT_BLURRED_POLLING_INTERVAL;
    if (Object.values(openChats).some(chat => chat.element && !chat.minimized && !chat.isExplicitlyClosed)) {
        startActiveChatsPolling(); // Restart with new interval
    }
});
window.addEventListener('focus', () => {
    currentEmbChatPollingInterval = EMB_CHAT_FOCUSED_POLLING_INTERVAL;
    if (Object.values(openChats).some(chat => chat.element && !chat.minimized && !chat.isExplicitlyClosed)) {
        startActiveChatsPolling(); // Restart with new interval
        pollActiveChats(); // Poll immediately on focus
    }
});

// Global function to open a chat
window.openEmbeddedChat = function(friendId, friendUsername, friendPfp) {
    const chatState = openChats[friendId];

    // If chat is already open and maximized, focus it and bring to front
    if (chatState && chatState.element && !chatState.minimized) {
        bringChatToFront(friendId);
        if (chatState.inputElement) chatState.inputElement.focus();
        fetchAndUpdateEmbUserStatus(friendId);
        return;
    }

    // If chat exists (either as bubble or was previously open)
    if (chatState) {
        chatState.minimized = false;
        chatState.isExplicitlyClosed = false; // Explicitly opening it clears the closed state
        // If it was a bubble, remove the bubble and create the chat box
        if (chatBubbles[friendId] && chatBubbles[friendId].element) {
            chatBubbles[friendId].element.remove();
            delete chatBubbles[friendId];
        }
        createChatBox(friendId, chatState.username || friendUsername, chatState.pfp || friendPfp, false);
    } else {
        // New chat
        createChatBox(friendId, friendUsername, friendPfp, true);
    }
    saveChatStates(); // Save changes (like isExplicitlyClosed = false)
};

function saveChatStates() {
    const savableOpenChats = {};
    for (const id in openChats) {
        const chat = openChats[id];
        // Only save if we have at least a username; avoids saving incomplete transient states
        if (chat && typeof chat.username !== 'undefined') {
            savableOpenChats[id] = {
                username: chat.username,
                pfp: chat.pfp || "",
                minimized: chat.minimized || false,
                isExplicitlyClosed: chat.isExplicitlyClosed || false, // *** FIX: Save this flag ***
                lastRead: chat.lastRead || new Date(0).toISOString(),
                          lastMsgId: chat.lastMsgId || 0
            };
        }
    }
    localStorage.setItem('pycloudEmbeddedChats', JSON.stringify(savableOpenChats));
}

function loadChatStates() {
    const saved = localStorage.getItem('pycloudEmbeddedChats');
    if (saved) {
        const loadedChats = JSON.parse(saved);
        openChats = {}; // Reset before loading
        for (const id in loadedChats) {
            const loadedChat = loadedChats[id];
            openChats[id] = {
                username: loadedChat.username || "User",
                pfp: loadedChat.pfp || "",
                minimized: loadedChat.minimized || false,
                isExplicitlyClosed: loadedChat.isExplicitlyClosed || false, // *** FIX: Load this flag ***
                lastRead: loadedChat.lastRead || new Date(0).toISOString(),
                          lastMsgId: loadedChat.lastMsgId || 0,
                          element: null, // DOM elements are not persisted
                          messagesElement: null,
                          inputElement: null,
                          fileInputElement: null
            };
        }
    }
}

function renderInitialChats() {
    let openBoxCount = 0;
    const chatIds = Object.keys(openChats);
    let statesModified = false;

    for (const friendId of chatIds) {
        const chatState = openChats[friendId];

        // *** FIX: If chat was explicitly closed, do not render it at all on load ***
        if (chatState.isExplicitlyClosed) {
            // Ensure its state reflects no UI element
            chatState.element = null;
            chatState.minimized = true; // Closed implies it's not an open box
            statesModified = true;
            continue;
        }

        // If not explicitly closed, attempt to render
        if (!chatState.minimized && openBoxCount < MAX_OPEN_CHAT_BOXES) {
            createChatBox(friendId, chatState.username, chatState.pfp, false); // false: not a "newly opened" chat by user action
            openBoxCount++;
        } else {
            // Becomes a bubble if it was minimized, or if max open boxes is reached
            if (!chatState.minimized) { // Becoming a bubble due to MAX_OPEN_CHAT_BOXES
                chatState.minimized = true;
                statesModified = true;
            }
            createChatBubble(friendId, chatState.username, chatState.pfp);
        }
    }
    if (statesModified) {
        saveChatStates(); // Save changes to minimized states if any occurred
    }
}

function createChatBox(friendId, friendUsername, friendPfp, isNewChatViaUserAction = true) {
    const chatState = openChats[friendId];
    const validUsername = friendUsername || (chatState ? chatState.username : "Chat");
    const validPfp = friendPfp || (chatState ? chatState.pfp : "");

    // If already maximized, just bring to front and focus
    if (chatState && chatState.element && !chatState.minimized) {
        bringChatToFront(friendId);
        if (chatState.inputElement) chatState.inputElement.focus();
        fetchAndUpdateEmbUserStatus(friendId);
        return;
    }

    // Remove bubble if it exists for this chat
    if (chatBubbles[friendId] && chatBubbles[friendId].element) {
        chatBubbles[friendId].element.remove();
        delete chatBubbles[friendId];
    }

    // Manage MAX_OPEN_CHAT_BOXES
    const currentlyMaximizedChats = Object.values(openChats).filter(c => c.element && !c.minimized && !c.isExplicitlyClosed);
    if (currentlyMaximizedChats.length >= MAX_OPEN_CHAT_BOXES) {
        // Find the oldest, non-current chat to minimize
        const sortedMaximizedChats = currentlyMaximizedChats
        .filter(c => String(Object.keys(openChats).find(key => openChats[key] === c)) !== String(friendId)) // Exclude current chat from minimization candidates
        .sort((a, b) => (new Date(a.lastRead || 0).getTime()) - (new Date(b.lastRead || 0).getTime()));

        if (sortedMaximizedChats.length > 0) {
            const chatToMinimizeState = sortedMaximizedChats[0];
            const idToMinimize = Object.keys(openChats).find(key => openChats[key] === chatToMinimizeState);
            if (idToMinimize) {
                minimizeChat(idToMinimize);
            }
        } else if (isNewChatViaUserAction) {
            // This case means all MAX_OPEN_CHAT_BOXES are for the current user, or some other edge case.
            // Fallback: convert the new chat to a bubble instead of failing.
            // Or, if this new chat *is* one of the existing ones being maximized, this shouldn't hit.
            // This primarily handles opening a 4th *distinct* chat when 3 are already open.
            createChatBubble(friendId, validUsername, validPfp);
            openChats[friendId] = { // Ensure state exists if it was a brand new attempt
                ...openChats[friendId], // Preserve existing data if any
                username: validUsername,
                pfp: validPfp,
                minimized: true,
                isExplicitlyClosed: false // It's a bubble, not closed
            };
            saveChatStates();
            return;
        }
    }

    const pfpSrc = validPfp ? `${STATIC_PFP_PATH_BASE}${validPfp}` : '';
    const pfpPlaceholder = validUsername ? validUsername.charAt(0).toUpperCase() : 'U';

    const chatBox = document.createElement('div');
    chatBox.className = 'emb-chat-box';
    chatBox.dataset.friendId = friendId;
    chatBox.style.zIndex = 1041; // Initial z-index, bringChatToFront will manage dynamically
    chatBox.innerHTML = `
    <div class="emb-chat-header">
    <div class="emb-user-info">
    <div class="emb-pfp-status-wrapper">
    ${pfpSrc ? `<img src="${pfpSrc}" alt="${escapeHtml(validUsername)}" class="emb-pfp">` : `<div class="emb-placeholder-pfp">${pfpPlaceholder}</div>`}
    <span class="emb-status-indicator offline" id="emb-status-indicator-${friendId}"></span>
    </div>
    <div class="emb-user-details">
    <span class="emb-username">${escapeHtml(validUsername)}</span>
    <small class="emb-status-text" id="emb-status-text-${friendId}">Offline</small>
    </div>
    </div>
    <div class="emb-actions">
    <button class="emb-minimize-btn" title="Minimize"><img src="${STATIC_ICONS_PATH_BASE}minimize.svg" alt="Minimize"></button>
    <button class="emb-close-btn" title="Close"><img src="${STATIC_ICONS_PATH_BASE}close.svg" alt="Close"></button>
    </div>
    </div>
    <div class="emb-chat-messages"></div>
    <div class="emb-chat-input-area">
    <form class="emb-dm-form">
    <input type="file" id="emb-file-${friendId}" class="visually-hidden emb-file-input" accept="image/*,video/*,audio/*,.pdf,.txt,.zip,.rar,.7z">
    <label for="emb-file-${friendId}" class="emb-btn-icon-input emb-attach-btn" title="Attach File (Max: ${MAX_UPLOAD_MB_CONFIG}MB)">
    <img src="${STATIC_ICONS_PATH_BASE}upload.svg" alt="Attach">
    </label>
    <textarea class="emb-message-input" rows="1" placeholder="Type a message..."></textarea>
    <button type="submit" class="emb-btn-icon-input emb-send-btn" aria-label="Send message">
    <img src="${STATIC_ICONS_PATH_BASE}send.svg" alt="Send">
    </button>
    </form>
    </div>`;
    embeddedChatContainer.appendChild(chatBox);
    bringChatToFront(friendId, chatBox); // Pass chatBox to avoid querySelector if new

    const messagesElem = chatBox.querySelector('.emb-chat-messages');
    const inputElem = chatBox.querySelector('.emb-message-input');
    const fileInputElem = chatBox.querySelector(`#emb-file-${friendId}`);

    if (!messagesElem || !inputElem || !fileInputElem) { // Should not happen with current innerHTML
        console.error("Failed to find essential elements in created chat box for friendId:", friendId);
        chatBox.remove();
        // If this was an attempt to restore from a loaded state, and it failed,
        // revert to bubble if it was supposed to be minimized.
        if (!isNewChatViaUserAction && openChats[friendId] && openChats[friendId].minimized) {
            createChatBubble(friendId, validUsername, validPfp);
        }
        // No need to saveChatStates here as openChats[friendId] might be inconsistent
        return;
    }

    // Update or create the state in openChats
    openChats[friendId] = {
        ...openChats[friendId], // Preserve lastRead, lastMsgId if they exist
        username: validUsername,
        pfp: validPfp,
        element: chatBox,
        messagesElement: messagesElem,
        inputElement: inputElem,
        fileInputElement: fileInputElem,
        minimized: false, // *** FIX: Newly created/maximized box is not minimized ***
        isExplicitlyClosed: false, // *** FIX: And not explicitly closed ***
    };

    setupChatBoxEventListeners(friendId);
    fetchAndRenderHistory(friendId, false); // false: load new messages since lastMsgId
    fetchAndUpdateEmbUserStatus(friendId);
    if (openChats[friendId].inputElement) {
        openChats[friendId].inputElement.focus();
        autoResizeTextarea(openChats[friendId].inputElement); // Initial resize
    }

    saveChatStates();
    // Start polling if this is the first active chat
    if (Object.values(openChats).filter(c => c.element && !c.minimized && !c.isExplicitlyClosed).length === 1) {
        startActiveChatsPolling();
    }
}

function bringChatToFront(friendId, chatBoxElement = null) {
    const chatBox = chatBoxElement || (openChats[friendId] ? openChats[friendId].element : null);
    if (!chatBox) return;

    const allBoxes = embeddedChatContainer.querySelectorAll('.emb-chat-box');
    let maxZ = 1040; // Base z-index for chat boxes
    allBoxes.forEach(box => {
        const currentZ = parseInt(window.getComputedStyle(box).zIndex, 10) || maxZ;
        if (currentZ > maxZ) maxZ = currentZ;
    });
        // Lower z-index of all other boxes slightly if they are at maxZ, to avoid continuous increment
        allBoxes.forEach(box => {
            if (box !== chatBox && (parseInt(window.getComputedStyle(box).zIndex, 10) || 0) >= maxZ) {
                box.style.zIndex = String(maxZ -1 < 1040 ? 1040 : maxZ -1);
            }
        });
        chatBox.style.zIndex = String(maxZ + 1);
}


function setupChatBoxEventListeners(friendId) {
    const chat = openChats[friendId];
    if (!chat || !chat.element) return;

    // Click on header (excluding buttons) to bring to front
    const header = chat.element.querySelector('.emb-chat-header');
    if (header) {
        header.addEventListener('mousedown', (e) => {
            if (!e.target.closest('button')) { // Only if not clicking a button in header
                bringChatToFront(friendId);
            }
        });
    }


    chat.element.querySelector('.emb-minimize-btn').addEventListener('click', () => minimizeChat(friendId));
    chat.element.querySelector('.emb-close-btn').addEventListener('click', () => closeChat(friendId));

    const form = chat.element.querySelector('.emb-dm-form');
    if (form) {
        form.addEventListener('submit', (e) => handleMessageSend(e, friendId));
    }

    if (chat.inputElement) {
        chat.inputElement.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                if (form) {
                    // Modern way to submit a form
                    if (typeof form.requestSubmit === "function") {
                        form.requestSubmit();
                    } else { // Fallback for older browsers
                        form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
                    }
                }
            }
            autoResizeTextarea(chat.inputElement); // Also resize on keydown for potential pastes
        });
        chat.inputElement.addEventListener('input', () => autoResizeTextarea(chat.inputElement));
    }
}

function minimizeChat(friendId) {
    const chatState = openChats[friendId];
    if (!chatState || chatState.minimized) return; // Already minimized or no state

    if (chatState.element) {
        chatState.element.remove();
        chatState.element = null; // Clear DOM element reference
        chatState.messagesElement = null;
        chatState.inputElement = null;
        chatState.fileInputElement = null;
    }
    chatState.minimized = true;
    chatState.isExplicitlyClosed = false; // Explicitly minimizing is not closing

    createChatBubble(friendId, chatState.username, chatState.pfp);
    saveChatStates();

    // If all chats are now minimized or closed, stop polling active chats
    if (Object.values(openChats).every(c => c.minimized || c.isExplicitlyClosed || !c.element)) {
        stopActiveChatsPolling();
    }
}

function closeChat(friendId) {
    // Remove bubble if it exists
    if (chatBubbles[friendId] && chatBubbles[friendId].element) {
        chatBubbles[friendId].element.remove();
        delete chatBubbles[friendId];
    }

    const chatState = openChats[friendId];
    if (chatState) {
        if (chatState.element) {
            chatState.element.remove();
            chatState.element = null; // Clear DOM element reference
            chatState.messagesElement = null;
            chatState.inputElement = null;
            chatState.fileInputElement = null;
        }
        chatState.minimized = true; // Closed implies it's not an open box
        chatState.isExplicitlyClosed = true; // *** FIX: Mark as explicitly closed ***
    } else {
        // If for some reason state didn't exist, create a minimal closed state
        openChats[friendId] = {
            username: "User", // Placeholder
            pfp: "",
            minimized: true,
            isExplicitlyClosed: true,
            lastRead: new Date(0).toISOString(),
                          lastMsgId: 0,
                          element: null
        };
    }

    saveChatStates();

    // If all chats are now minimized or closed, stop polling
    if (Object.values(openChats).every(c => c.minimized || c.isExplicitlyClosed || !c.element)) {
        stopActiveChatsPolling();
    }
}

function createChatBubble(friendId, friendUsername, friendPfp) {
    const validUsername = friendUsername || (openChats[friendId] ? openChats[friendId].username : "Chat");
    const validPfp = friendPfp || (openChats[friendId] ? openChats[friendId].pfp : "");

    // If bubble already exists, just update its info (e.g., unread count, potentially pfp/username)
    if (chatBubbles[friendId] && chatBubbles[friendId].element) {
        // Update username/pfp if they changed (e.g. from recent messages poll)
        const existingBubble = chatBubbles[friendId];
        if (existingBubble.username !== validUsername) {
            existingBubble.username = validUsername;
            existingBubble.element.title = validUsername;
            // Could update pfp/placeholder in bubble's innerHTML if necessary here
        }
        if (existingBubble.pfp !== validPfp) {
            existingBubble.pfp = validPfp;
            // Update pfp in bubble's innerHTML
            const pfpContainer = existingBubble.element.firstChild; // Assuming pfp/placeholder is the first child
            if (pfpContainer) {
                const newPfpSrc = validPfp ? `${STATIC_PFP_PATH_BASE}${validPfp}` : '';
                const newPfpPlaceholder = validUsername ? validUsername.charAt(0).toUpperCase() : 'U';
                pfpContainer.innerHTML = newPfpSrc ? `<img src="${newPfpSrc}" alt="${escapeHtml(validUsername)}" class="emb-pfp">` : `<div class="emb-placeholder-pfp">${newPfpPlaceholder}</div>`;
            }
        }
        updateBubbleUnreadCount(friendId); // Refresh unread count display
        return;
    }

    // Do not create a bubble if the corresponding chat box is open and maximized
    if (openChats[friendId] && openChats[friendId].element && !openChats[friendId].minimized) {
        return;
    }

    const pfpSrc = validPfp ? `${STATIC_PFP_PATH_BASE}${validPfp}` : '';
    const pfpPlaceholder = validUsername ? validUsername.charAt(0).toUpperCase() : 'U';

    const bubble = document.createElement('div');
    bubble.className = 'emb-chat-bubble';
    bubble.dataset.friendId = friendId;
    bubble.title = validUsername;
    bubble.innerHTML = `
    <div class="emb-bubble-pfp-wrapper">
    ${pfpSrc ? `<img src="${pfpSrc}" alt="${escapeHtml(validUsername)}" class="emb-pfp">` : `<div class="emb-placeholder-pfp">${pfpPlaceholder}</div>`}
    </div>
    <button class="emb-bubble-close-btn" title="Close Chat">&times;</button>
    <span class="emb-unread-message-indicator" style="display:none;">0</span>`;

    // Insert bubbles in a consistent order if desired, or just prepend/append
    // Prepending makes newest bubbles appear on the left (or top if vertical)
    const firstChatBox = embeddedChatContainer.querySelector('.emb-chat-box');
    if (firstChatBox) {
        embeddedChatContainer.insertBefore(bubble, firstChatBox);
    } else {
        embeddedChatContainer.appendChild(bubble); // If no chat boxes, just append
    }


    chatBubbles[friendId] = { username: validUsername, pfp: validPfp, element: bubble };

    // Ensure openChats has a state for this bubble, marked as minimized and not explicitly closed
    if (!openChats[friendId]) {
        openChats[friendId] = { username: validUsername, pfp: validPfp, minimized: true, isExplicitlyClosed: false, element: null, lastMsgId: 0, lastRead: new Date(0).toISOString() };
    } else {
        openChats[friendId].username = validUsername; // Update if needed
        openChats[friendId].pfp = validPfp;         // Update if needed
        openChats[friendId].minimized = true;
        openChats[friendId].isExplicitlyClosed = false; // If a bubble is created, it implies it's not "explicitly closed" in the hidden sense
        openChats[friendId].element = null; // No chat box element for a bubble
    }

    bubble.addEventListener('click', (e) => {
        if (e.target.classList.contains('emb-bubble-close-btn') || e.target.closest('.emb-bubble-close-btn')) {
            return; // Let the close button's own listener handle it
        }
        maximizeChatFromBubble(friendId);
    });
    bubble.querySelector('.emb-bubble-close-btn').addEventListener('click', (e) => {
        e.stopPropagation(); // Prevent bubble click from firing
        closeChat(friendId);
    });

    updateBubbleUnreadCount(friendId); // Calculate and show initial unread count
    saveChatStates();
}

function maximizeChatFromBubble(friendId) {
    const bubbleInfo = chatBubbles[friendId];
    const usernameFromBubble = bubbleInfo ? bubbleInfo.username : (openChats[friendId] ? openChats[friendId].username : "Chat");
    const pfpFromBubble = bubbleInfo ? bubbleInfo.pfp : (openChats[friendId] ? openChats[friendId].pfp : "");

    if (openChats[friendId]) {
        openChats[friendId].minimized = false;
        openChats[friendId].isExplicitlyClosed = false; // Maximizing clears this
    } else {
        // Should ideally not happen if bubble exists, but as a fallback:
        openChats[friendId] = { username: usernameFromBubble, pfp: pfpFromBubble, minimized: false, isExplicitlyClosed: false, element: null, lastMsgId: 0, lastRead: new Date(0).toISOString() };
    }

    // Remove the bubble
    if (bubbleInfo && bubbleInfo.element) {
        bubbleInfo.element.remove();
        delete chatBubbles[friendId];
    }

    createChatBox(friendId, usernameFromBubble, pfpFromBubble, false); // Not a "new" chat in terms of user intent
    // saveChatStates() is called within createChatBox
}


async function fetchAndRenderHistory(friendId, loadOlder = false) {
    const chat = openChats[friendId];
    if (!chat || !chat.messagesElement || !chat.username) return;

    let apiUrl = `${EMB_DM_HISTORY_API_URL_BASE}${chat.username}`;
    const currentLastMsgId = chat.lastMsgId || 0;
    // Only add since_message_id if not loading older and we have a last message ID
    if (!loadOlder && currentLastMsgId > 0) {
        apiUrl += `?since_message_id=${currentLastMsgId}`;
    } else if (loadOlder) {
        // Logic for loading older messages would go here (e.g., before_message_id)
        // For now, loadOlder isn't fully implemented beyond not using since_message_id
        // This means if loadOlder is true, it fetches the entire history or latest page.
    }


    try {
        const response = await fetch(apiUrl, { headers: { 'X-CSRFToken': CSRF_TOKEN } });
        if (!response.ok) {
            if (response.status === 404 && chat.element) {
                if (typeof showToast === 'function') showToast(`Chat with ${escapeHtml(chat.username)} is no longer available.`, "warning");
                closeChat(friendId); // This will also save state
            } else {
                console.error(`API error fetching history for ${escapeHtml(chat.username)}: ${response.status}`);
            }
            return;
        }
        const data = await response.json();

        if (data.status === 'success' && data.messages) {
            let newMessagesRendered = false;
            let latestTimestampInFetch = chat.lastRead || new Date(0).toISOString();
            let newLastMsgId = chat.lastMsgId || 0;

            data.messages.sort((a, b) => a.id - b.id); // Ensure messages are in correct order

            data.messages.forEach(msg => {
                if (!chat.messagesElement.querySelector(`.dc-message-wrapper[data-message-id="${msg.id}"]`)) {
                    renderMessage(friendId, msg);
                    newMessagesRendered = true;
                    if (msg.id > newLastMsgId) newLastMsgId = msg.id;
                    if (msg.timestamp > latestTimestampInFetch) latestTimestampInFetch = msg.timestamp;
                }
            });

            chat.lastMsgId = newLastMsgId; // Update lastMsgId with the latest from this fetch

            if (newMessagesRendered && !loadOlder) { // Only auto-scroll for new messages, not when loading older history
                scrollToBottom(friendId);
            }

            // Update lastRead time if the chat is open, focused, and new messages arrived
            if (!chat.minimized && chat.element && (document.hasFocus() || chat.inputElement === document.activeElement) && newMessagesRendered) {
                const nowISO = new Date().toISOString();
                // Use the timestamp of the latest message fetched or now, whichever is later (should be latest message)
                chat.lastRead = latestTimestampInFetch > nowISO ? latestTimestampInFetch : nowISO;
                updateBubbleUnreadVisuals(friendId, 0); // Clear unread count for this user IF a bubble existed
            }
            saveChatStates(); // Save updated lastMsgId and lastRead
        } else if (data.status !== 'success') {
            console.error(`API error fetching history (data.status not success) for ${escapeHtml(chat.username)}: ${data.message}`);
        }
    } catch (error) {
        console.error(`Network or JSON error fetching history for ${escapeHtml(chat.username)}:`, error);
    }
}

function renderMessage(friendId, msg) {
    const chat = openChats[friendId];
    if (!chat || !chat.messagesElement) return;

    const isSent = String(msg.sender_id) === String(CURRENT_USER_ID);
    const wrapper = document.createElement('div');
    wrapper.className = `dc-message-wrapper ${isSent ? 'sent' : 'received'}`;
    wrapper.dataset.messageId = msg.id;

    const pfpFilename = isSent ? CURRENT_USER_PFP_FILENAME : msg.sender_profile_picture_filename;
    const pfpUsername = isSent ? CURRENT_USER_USERNAME : (msg.sender_username || 'User');
    const pfpInitial = pfpUsername ? pfpUsername.charAt(0).toUpperCase() : 'U';
    let pfpHTML = pfpFilename ?
    `<div class="dc-pfp-container-bubble"><img src="${STATIC_PFP_PATH_BASE}${pfpFilename}" alt="${escapeHtml(pfpUsername)}'s PFP" class="dc-pfp"></div>` :
    `<div class="dc-pfp-placeholder-bubble">${pfpInitial}</div>`;

    let fileHTML = '';
    if (msg.shared_file) {
        const sf = msg.shared_file;
        fileHTML = `<div class="dc-message-file-attachment"><p class="dc-file-name"><a href="${sf.download_url}" target="_blank" download="${escapeHtml(sf.original_filename)}">${escapeHtml(sf.original_filename)}</a></p><div class="dc-file-preview">`;
        if (sf.mime_type && sf.view_url) {
            if (sf.mime_type.startsWith('image/')) fileHTML += `<img src="${sf.view_url}" alt="Preview" style="max-width:100%; cursor:pointer;" onclick="window.open('${sf.view_url}', '_blank');">`;
            else if (sf.mime_type.startsWith('video/')) fileHTML += `<video src="${sf.view_url}" controls style="max-width:100%;"></video>`;
            else if (sf.mime_type.startsWith('audio/')) fileHTML += `<audio src="${sf.view_url}" controls style="width:100%;"></audio>`;
            else if (sf.mime_type === 'text/plain' && typeof sf.preview_content !== 'undefined') fileHTML += `<div class="dc-text-file-preview"><pre>${escapeHtml(sf.preview_content)}</pre></div>`;
            else fileHTML += `<small>Preview not available.</small>`;
        }  else fileHTML += `<small>Preview not available.</small>`;
        fileHTML += `</div></div>`;
    }
    wrapper.innerHTML = `
    ${pfpHTML}
    <div class="dc-message">
    <div class="dc-message-header">
    <a href="${USER_PROFILE_URL_BASE}${escapeHtml(pfpUsername)}" class="dc-message-sender" target="_blank">${escapeHtml(pfpUsername)}</a>
    <span class="dc-message-timestamp">${formatTimestamp(msg.timestamp)}</span>
    </div>
    ${msg.content ? `<p class="dc-message-content">${escapeHtmlWithLinks(msg.content)}</p>` : ''}
    ${fileHTML}
    </div>`;
    chat.messagesElement.appendChild(wrapper);
}


async function handleMessageSend(event, friendId) {
    event.preventDefault();
    const chat = openChats[friendId];
    if (!chat || !chat.inputElement || !chat.fileInputElement || !chat.username) return;

    const content = chat.inputElement.value.trim();
    const file = chat.fileInputElement.files[0];

    if (!content && !file) return;

    const formData = new FormData();
    formData.append('content', content);
    if (file) {
        if (file.size > MAX_UPLOAD_MB_CONFIG * 1024 * 1024) {
            if (typeof showToast === 'function') showToast(`File exceeds max size of ${MAX_UPLOAD_MB_CONFIG}MB.`, 'danger');
            chat.fileInputElement.value = null; // Clear the file input
            return;
        }
        formData.append('file', file);
    }

    const sendButton = chat.element.querySelector('.emb-send-btn');
    chat.inputElement.disabled = true;
    if (sendButton) sendButton.disabled = true;

    try {
        const response = await fetch(`${EMB_DM_SEND_API_URL_BASE}${chat.username}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': CSRF_TOKEN, 'Accept': 'application/json' },
            body: formData
        });
        const data = await response.json();

        if (response.ok && data.status === 'success' && data.message) {
            renderMessage(friendId, data.message); // Render the sent message immediately
            scrollToBottom(friendId);
            if (data.message.id > (chat.lastMsgId || 0) ) chat.lastMsgId = data.message.id;

            chat.inputElement.value = '';
            chat.fileInputElement.value = null; // Clear file input after successful send
            autoResizeTextarea(chat.inputElement);
            chat.lastRead = new Date().toISOString(); // Update lastRead to now
            saveChatStates();
        } else {
            if (typeof showToast === 'function') showToast(data.message || 'Could not send message.', 'danger');
        }
    } catch (error) {
        console.error("Error sending message:", error);
        if (typeof showToast === 'function') showToast('Network error sending DM.', 'danger');
    } finally {
        chat.inputElement.disabled = false;
        if (sendButton) sendButton.disabled = false;
        if (chat.inputElement) chat.inputElement.focus();
    }
}

async function fetchAndUpdateEmbUserStatus(friendId) {
    if (!API_USERS_ACTIVITY_STATUS_URL || !CSRF_TOKEN) {
        // console.warn("Activity status API URL or CSRF token not defined for embedded chat status.");
        return;
    }
    // Try to get the chatBox from openChats first
    const chatBox = openChats[friendId] ? openChats[friendId].element : null;

    // If chatBox is not directly in openChats.element (e.g., it was just created and not yet assigned),
    // try to query it from DOM as a fallback, though ideally it should be available via openChats.
    const finalChatBox = chatBox || document.querySelector(`.emb-chat-box[data-friend-id="${friendId}"]`);

    if (!finalChatBox) {
        // console.log(`Chatbox for friend ${friendId} not found in DOM for status update.`);
        return;
    }

    const indicator = finalChatBox.querySelector(`#emb-status-indicator-${friendId}`);
    const statusTextElement = finalChatBox.querySelector(`#emb-status-text-${friendId}`);

    if (!indicator || !statusTextElement) {
        // console.log(`Status elements not found in chatbox for friend ${friendId}.`);
        return;
    }

    try {
        const response = await fetch(API_USERS_ACTIVITY_STATUS_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': CSRF_TOKEN
            },
            body: JSON.stringify({ user_ids: [friendId] })
        });

        if (!response.ok) {
            // Don't throw error for typical HTTP errors like 404 if user status is just unavailable
            // console.warn(`Network response not ok for status update: ${response.status} for friend ${friendId}`);
            // Default to offline visually if request fails
            indicator.className = 'emb-status-indicator offline';
            statusTextElement.textContent = 'Offline';
            return;
        }

        const data = await response.json();

        if (data.user_statuses && typeof data.user_statuses[friendId] !== 'undefined') {
            const status = String(data.user_statuses[friendId].status || data.user_statuses[friendId]).toLowerCase(); // Accommodate direct string or {status: "string"}

            indicator.classList.remove('online', 'afk', 'offline', 'dnd'); // Remove all possible status classes
            indicator.classList.add(status); // Add the new status class

            let displayStatus = 'Offline'; // Default
            if (status === 'online') displayStatus = 'Online';
            else if (status === 'afk') displayStatus = 'Away';
            else if (status === 'dnd') displayStatus = 'Do Not Disturb';
            // Keep 'Offline' for 'offline' or any other unhandled status

            statusTextElement.textContent = displayStatus;
        } else {
            // Default to offline if status not found in response
            indicator.classList.remove('online', 'afk', 'dnd');
            indicator.classList.add('offline');
            statusTextElement.textContent = 'Offline';
        }
    } catch (error) {
        console.error(`Error fetching activity status for friend ${friendId} in embedded chat:`, error);
        // Default to offline on error
        if (indicator) {
            indicator.classList.remove('online', 'afk', 'dnd');
            indicator.classList.add('offline');
        }
        if (statusTextElement) {
            statusTextElement.textContent = 'Offline';
        }
    }
}

function scrollToBottom(friendId) {
    const chat = openChats[friendId];
    if (chat && chat.messagesElement) {
        // Using a small timeout can help ensure rendering is complete before scrolling
        setTimeout(() => {
            chat.messagesElement.scrollTop = chat.messagesElement.scrollHeight;
        }, 50);
    }
}

function autoResizeTextarea(textarea) {
    if(!textarea) return;
    textarea.style.height = 'auto'; // Temporarily shrink to get correct scrollHeight
    const newScrollHeight = textarea.scrollHeight;
    // Max height of 80px (approx 3-4 lines)
    textarea.style.height = (newScrollHeight > 80 ? 80 : newScrollHeight) + 'px';
}

function formatTimestamp(isoString) {
    if (!isoString) return 'Sending...'; // For optimistic updates
    try {
        const date = new Date(isoString);
        if (isNaN(date.getTime())) return 'Invalid Date';
        // Format to show time like "10:30 AM"
        return date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit', hour12: true });
    } catch (e) {
        console.error("Error formatting timestamp:", isoString, e);
        return 'Invalid Date';
    }
}

function escapeHtml(unsafe) {
    if (unsafe === null || typeof unsafe === 'undefined') return '';
    return unsafe.toString()
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function escapeHtmlWithLinks(unsafe) {
    if (unsafe === null || typeof unsafe === 'undefined') return '';
    let text = unsafe.toString()
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");

    // Basic URL detection (http, https, www)
    const urlRegex = /(\b(https?|ftp|file):\/\/[-A-Z0-9+&@#\/%?=~_|!:,.;]*[-A-Z0-9+&@#\/%=~_|])|(\bwww\.[-A-Z0-9+&@#\/%?=~_|!:,.;]*[-A-Z0-9+&@#\/%=~_|])/ig;
    return text.replace(urlRegex, function(url) {
        let fullUrl = url;
        if (url.toLowerCase().startsWith('www.')) {
            fullUrl = 'http://' + url;
        }
        return `<a href="${fullUrl}" target="_blank" rel="noopener noreferrer">${url}</a>`;
    });
}


function startActiveChatsPolling() {
    stopActiveChatsPolling(); // Clear existing timer
    // Only poll if there are chats that are actual DOM elements, not minimized, and not explicitly closed
    const activeChatsExist = Object.values(openChats).some(c => c.element && !c.minimized && !c.isExplicitlyClosed && c.username);
    if (activeChatsExist) {
        embChatPollTimerId = setInterval(pollActiveChats, currentEmbChatPollingInterval);
        // pollActiveChats(); // Initial poll if needed, but window focus also polls
    }
}

function stopActiveChatsPolling() {
    if (embChatPollTimerId) {
        clearInterval(embChatPollTimerId);
        embChatPollTimerId = null;
    }
}

function pollActiveChats() {
    Object.keys(openChats).forEach(friendId => {
        const chat = openChats[friendId];
        if (chat && chat.element && !chat.minimized && !chat.isExplicitlyClosed && chat.username) {
            fetchAndRenderHistory(friendId, false); // false means fetch new messages
            fetchAndUpdateEmbUserStatus(friendId); // Also refresh status for open chats
        }
    });
}

function startRecentMessagesPolling() {
    stopRecentMessagesPolling(); // Clear existing timer
    recentMsgPollTimerId = setInterval(pollForRecentMessages, RECENT_MSG_POLLING_INTERVAL);
    pollForRecentMessages(); // Initial poll
}

function stopRecentMessagesPolling() {
    if (recentMsgPollTimerId) {
        clearInterval(recentMsgPollTimerId);
        recentMsgPollTimerId = null;
    }
}

async function pollForRecentMessages() {
    try {
        const response = await fetch(EMB_DM_RECENT_MESSAGES_API_URL, { headers: { 'X-CSRFToken': CSRF_TOKEN } });
        if (!response.ok) {
            console.error(`Error polling recent messages: ${response.status}`);
            // Potentially stop polling on certain errors like 401/403 after some retries
            return;
        }
        const data = await response.json();

        if (data.status === 'success' && data.recent_messages) {
            let stateChangedThisPoll = false;
            data.recent_messages.forEach(msg => {
                const friendId = String(msg.sender_id); // Assuming sender_id is the friend's ID
                if (friendId === String(CURRENT_USER_ID)) return; // Ignore self-sent messages here

                let chatState = openChats[friendId];

                // If chat is open and maximized, new messages are handled by active polling, so skip here
                if (chatState && chatState.element && !chatState.minimized && !chatState.isExplicitlyClosed) {
                    return;
                }

                let isGenuinelyNewForBubble = false;
                if (!chatState) {
                    // This is a new contact bubbling up
                    openChats[friendId] = {
                        username: msg.sender_username,
                        pfp: msg.sender_profile_picture_filename,
                        minimized: true, // Start as bubble
                        isExplicitlyClosed: false, // Not closed if it's a new message
                        lastMsgId: msg.message_id,
                        lastRead: new Date(0).toISOString(), // Mark as unread
                                         element: null
                    };
                    chatState = openChats[friendId];
                    isGenuinelyNewForBubble = true;
                    stateChangedThisPoll = true;
                } else {
                    // Update username/pfp in case they changed
                    chatState.username = msg.sender_username;
                    chatState.pfp = msg.sender_profile_picture_filename;

                    if (msg.message_id > (chatState.lastMsgId || 0)) {
                        isGenuinelyNewForBubble = true;
                        chatState.lastMsgId = msg.message_id;
                        stateChangedThisPoll = true;
                        // If it was explicitly closed and a new message arrives, make it a bubble again
                        // This is a design choice: new message re-opens a closed chat as a bubble.
                        // If you want explicitly closed chats to stay hidden, remove this next line.
                        if (chatState.isExplicitlyClosed) {
                            chatState.isExplicitlyClosed = false;
                        }
                    }
                }

                // If new message for a bubble-able chat (not explicitly closed in a "hidden" state)
                if (isGenuinelyNewForBubble && !chatState.isExplicitlyClosed) {
                    if (!chatBubbles[friendId] || !chatBubbles[friendId].element) {
                        createChatBubble(friendId, chatState.username, chatState.pfp);
                    } else {
                        // If bubble already exists, just update its unread count
                        updateBubbleUnreadCount(friendId);
                    }
                    if (notificationSound) { // Play sound only if tab is not focused
                        notificationSound.play().catch(error => console.warn("Notification sound play failed:", error));
                    }
                } else if (chatState.isExplicitlyClosed) {
                    // If it's still marked explicitly closed, ensure no bubble exists.
                    // This handles the case where a message might have been fetched *before* `isExplicitlyClosed` was saved/loaded correctly.
                    if (chatBubbles[friendId] && chatBubbles[friendId].element) {
                        chatBubbles[friendId].element.remove();
                        delete chatBubbles[friendId];
                        stateChangedThisPoll = true;
                    }
                }
            });
            if (stateChangedThisPoll) {
                saveChatStates();
            }
        }
    } catch (error) {
        console.error('Error polling for recent messages:', error);
    }
}

function updateBubbleUnreadVisuals(friendId, count) {
    const bubbleState = chatBubbles[friendId];
    if (bubbleState && bubbleState.element) {
        const indicator = bubbleState.element.querySelector('.emb-unread-message-indicator');
        if (indicator) {
            if (count > 0) {
                indicator.textContent = count > 9 ? '9+' : String(count);
                indicator.style.display = 'flex'; // Use flex for centering if CSS is set up for it
            } else {
                indicator.style.display = 'none';
            }
        }
    }
}

async function updateBubbleUnreadCount(friendId) {
    const chatState = openChats[friendId];
    // If no chat state or no username (cannot fetch history), or if chatbox is open and not minimized (unread handled by lastRead)
    if (!chatState || !chatState.username || (chatState.element && !chatState.minimized)) {
        updateBubbleUnreadVisuals(friendId, 0);
        return;
    }

    const lastReadTime = chatState.lastRead || new Date(0).toISOString();
    let unreadCount = 0;

    // Fetch full history to count messages newer than lastRead.
    // This could be optimized by an API endpoint that returns only the count.
    try {
        // Fetch all messages to compare timestamps. API might need adjustment for efficiency.
        // Using since_message_id=0 effectively asks for all relevant recent history.
        const historyUrl = `${EMB_DM_HISTORY_API_URL_BASE}${chatState.username}?since_message_id=0`;
        const response = await fetch(historyUrl, { headers: { 'X-CSRFToken': CSRF_TOKEN }});
        if (!response.ok) {
            console.warn(`Could not fetch history for unread count for ${escapeHtml(chatState.username)}: ${response.status}`);
            updateBubbleUnreadVisuals(friendId, 0);
            return;
        }
        const data = await response.json();
        if (data.status === 'success' && data.messages) {
            data.messages.forEach(m => {
                if (String(m.sender_id) !== String(CURRENT_USER_ID) && m.timestamp > lastReadTime) {
                    unreadCount++;
                }
            });
        }
        updateBubbleUnreadVisuals(friendId, unreadCount);
    } catch (e) {
        console.error(`Error calculating unread count for bubble ${friendId}:`, e);
        updateBubbleUnreadVisuals(friendId, 0); // Default to 0 on error
    }
}
});
