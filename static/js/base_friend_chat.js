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
        typeof API_USERS_ACTIVITY_STATUS_URL === 'undefined') { // Added check for activity status URL
            console.error("One or more required global constants for embedded chat are missing. Embedded chat will not initialize.");
            return;
        }

        const embeddedChatContainer = document.getElementById('base-embedded-chat-container');
        if (!embeddedChatContainer) {
            return;
        }

        let openChats = {};
        let chatBubbles = {};
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

        loadChatStates();
        renderInitialChats();
        startRecentMessagesPolling();
        if (Object.values(openChats).some(chat => chat.element && !chat.minimized)) {
            startActiveChatsPolling();
        }

        window.addEventListener('blur', () => {
            currentEmbChatPollingInterval = EMB_CHAT_BLURRED_POLLING_INTERVAL;
            if (Object.values(openChats).some(chat => chat.element && !chat.minimized)) startActiveChatsPolling();
        });
            window.addEventListener('focus', () => {
                currentEmbChatPollingInterval = EMB_CHAT_FOCUSED_POLLING_INTERVAL;
                if (Object.values(openChats).some(chat => chat.element && !chat.minimized)) {
                    startActiveChatsPolling();
                    pollActiveChats(); // Poll immediately on focus
                }
            });

            window.openEmbeddedChat = function(friendId, friendUsername, friendPfp) {
                if (openChats[friendId] && openChats[friendId].element && !openChats[friendId].minimized) {
                    openChats[friendId].element.style.zIndex = (parseInt(window.getComputedStyle(openChats[friendId].element).zIndex) || 1040) + 1;
                    if (openChats[friendId].inputElement) openChats[friendId].inputElement.focus();
                    fetchAndUpdateEmbUserStatus(friendId); // Refresh status on focus/re-open
                    return;
                }
                if (chatBubbles[friendId] || (openChats[friendId] && openChats[friendId].minimized)) {
                    maximizeChatFromBubble(friendId, friendUsername, friendPfp);
                    return;
                }
                createChatBox(friendId, friendUsername, friendPfp, true);
            };

            function saveChatStates() {
                const savableOpenChats = {};
                for (const id in openChats) {
                    if (openChats[id] && typeof openChats[id].username !== 'undefined' && typeof openChats[id].minimized !== 'undefined') {
                        savableOpenChats[id] = {
                            username: openChats[id].username,
                            pfp: openChats[id].pfp || "",
                            minimized: openChats[id].minimized,
                            lastRead: openChats[id].lastRead || new Date(0).toISOString(),
                          lastMsgId: openChats[id].lastMsgId || 0
                        };
                    }
                }
                localStorage.setItem('pycloudEmbeddedChats', JSON.stringify(savableOpenChats));
            }

            function loadChatStates() {
                const saved = localStorage.getItem('pycloudEmbeddedChats');
                if (saved) {
                    const loadedChats = JSON.parse(saved);
                    openChats = {};
                    for(const id in loadedChats) {
                        openChats[id] = {
                            username: loadedChats[id].username || "User",
                          pfp: loadedChats[id].pfp || "",
                          minimized: loadedChats[id].minimized,
                          lastRead: loadedChats[id].lastRead || new Date(0).toISOString(),
                          lastMsgId: loadedChats[id].lastMsgId || 0,
                          element: null, messagesElement: null, inputElement: null, fileInputElement: null
                        };
                    }
                }
            }

            function renderInitialChats() {
                let openBoxCount = 0;
                const chatIds = Object.keys(openChats);
                for (const friendId of chatIds) {
                    const chatState = openChats[friendId];
                    if (!chatState.minimized && openBoxCount < MAX_OPEN_CHAT_BOXES) {
                        createChatBox(friendId, chatState.username, chatState.pfp, false);
                        openBoxCount++;
                    } else {
                        chatState.minimized = true;
                        createChatBubble(friendId, chatState.username, chatState.pfp);
                    }
                }
            }

            function createChatBox(friendId, friendUsername, friendPfp, isNewChat = true) {
                const validUsername = friendUsername || (openChats[friendId] ? openChats[friendId].username : null) || "Chat";
                const validPfp = friendPfp || (openChats[friendId] ? openChats[friendId].pfp : null) || "";

                if (openChats[friendId] && openChats[friendId].element && !openChats[friendId].minimized) {
                    openChats[friendId].element.style.zIndex = (parseInt(window.getComputedStyle(openChats[friendId].element).zIndex) || 1040) +1;
                    if(openChats[friendId].inputElement) openChats[friendId].inputElement.focus();
                    fetchAndUpdateEmbUserStatus(friendId); // Refresh status
                    return;
                }

                if (chatBubbles[friendId] && chatBubbles[friendId].element) {
                    chatBubbles[friendId].element.remove();
                    delete chatBubbles[friendId];
                }

                const currentlyMaximizedChats = Object.values(openChats).filter(c => c.element && !c.minimized);
                if (currentlyMaximizedChats.length >= MAX_OPEN_CHAT_BOXES) {
                    const sortedMaximizedChats = currentlyMaximizedChats.sort((a,b) => (new Date(a.lastRead || 0).getTime()) - (new Date(b.lastRead || 0).getTime()));
                    let chatToMinimizeId = null;
                    for (const chatState of sortedMaximizedChats) {
                        const idToMinimize = Object.keys(openChats).find(key => openChats[key] === chatState);
                        if (idToMinimize && String(idToMinimize) !== String(friendId)) {
                            chatToMinimizeId = idToMinimize;
                            break;
                        }
                    }
                    if (chatToMinimizeId) {
                        minimizeChat(chatToMinimizeId);
                    } else {
                        if(isNewChat) {
                            createChatBubble(friendId, validUsername, validPfp);
                            if(openChats[friendId]) openChats[friendId].minimized = true; else openChats[friendId] = {username: validUsername, pfp: validPfp, minimized: true};
                            saveChatStates();
                            return;
                        }
                    }
                }

                const pfpSrc = validPfp ? `${STATIC_PFP_PATH_BASE}${validPfp}` : '';
                const pfpPlaceholder = validUsername ? validUsername.charAt(0).toUpperCase() : 'U';

                const chatBox = document.createElement('div');
                chatBox.className = 'emb-chat-box';
                chatBox.dataset.friendId = friendId;
                chatBox.style.zIndex = 1041;
                chatBox.innerHTML = `
                <div class="emb-chat-header">
                <div class="emb-user-info">
                <div class="emb-pfp-status-wrapper">
                ${pfpSrc ? `<img src="${pfpSrc}" alt="${validUsername}" class="emb-pfp">` : `<div class="emb-placeholder-pfp">${pfpPlaceholder}</div>`}
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
                </div>
                `;
                embeddedChatContainer.appendChild(chatBox);

                const messagesElem = chatBox.querySelector('.emb-chat-messages');
                const inputElem = chatBox.querySelector('.emb-message-input');
                const fileInputElem = chatBox.querySelector(`#emb-file-${friendId}`);

                if (!messagesElem || !inputElem || !fileInputElem) {
                    chatBox.remove();
                    if (!isNewChat) {
                        createChatBubble(friendId, validUsername, validPfp);
                        if(openChats[friendId]) openChats[friendId].minimized = true;
                    }
                    saveChatStates();
                    return;
                }
                chatBox.addEventListener('mousedown', () => {
                    const allBoxes = embeddedChatContainer.querySelectorAll('.emb-chat-box');
                    let maxZ = 1040;
                    allBoxes.forEach(box => {
                        const currentZ = parseInt(window.getComputedStyle(box).zIndex);
                        if (currentZ > maxZ) maxZ = currentZ;
                        box.style.zIndex = '1040';
                    });
                    chatBox.style.zIndex = maxZ + 1;
                });
                openChats[friendId] = {
                    ...openChats[friendId],
                    username: validUsername,
                    pfp: validPfp,
                    element: chatBox,
                    messagesElement: messagesElem,
                    inputElement: inputElem,
                    fileInputElement: fileInputElem,
                    minimized: false,
                    isExplicitlyClosed: false,
                    lastMsgId: (openChats[friendId] && openChats[friendId].lastMsgId) ? openChats[friendId].lastMsgId : 0
                };
                setupChatBoxEventListeners(friendId);
                fetchAndRenderHistory(friendId, false);
                fetchAndUpdateEmbUserStatus(friendId); // Fetch status when box is created
                if (openChats[friendId].inputElement) openChats[friendId].inputElement.focus();
                saveChatStates();
                if (Object.values(openChats).filter(c => c.element && !c.minimized).length > 0 && !embChatPollTimerId) {
                    startActiveChatsPolling();
                }
            }

            function setupChatBoxEventListeners(friendId) {
                const chat = openChats[friendId];
                if (!chat || !chat.element) return;
                chat.element.querySelector('.emb-minimize-btn').addEventListener('click', () => minimizeChat(friendId));
                chat.element.querySelector('.emb-close-btn').addEventListener('click', () => closeChat(friendId));
                const form = chat.element.querySelector('.emb-dm-form');
                if (form) form.addEventListener('submit', (e) => handleMessageSend(e, friendId));
                if (chat.inputElement) {
                    chat.inputElement.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                            e.preventDefault();
                            if (form) form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit', {cancelable: true, bubbles: true}));
                        }
                        autoResizeTextarea(chat.inputElement);
                    });
                    chat.inputElement.addEventListener('input', () => autoResizeTextarea(chat.inputElement));
                }
            }

            function minimizeChat(friendId) {
                const chatState = openChats[friendId];
                if (!chatState || chatState.minimized) return;
                if (chatState.element) {
                    chatState.element.remove();
                    chatState.element = null;
                }
                chatState.minimized = true;
                createChatBubble(friendId, chatState.username, chatState.pfp);
                saveChatStates();
                if (Object.values(openChats).every(c => !c.element || c.minimized)) {
                    stopActiveChatsPolling();
                }
            }

            function closeChat(friendId) {
                if (chatBubbles[friendId] && chatBubbles[friendId].element) {
                    chatBubbles[friendId].element.remove();
                    delete chatBubbles[friendId];
                }
                if (openChats[friendId]) {
                    if (openChats[friendId].element) openChats[friendId].element.remove();
                    openChats[friendId].isExplicitlyClosed = true;
                    openChats[friendId].minimized = true;
                    openChats[friendId].element = null;
                } else {
                    openChats[friendId] = {
                        username: "User", pfp: "", minimized: true, isExplicitlyClosed: true, element: null, lastMsgId: 0, lastRead: new Date(0).toISOString()
                    };
                }
                saveChatStates();
                if (Object.values(openChats).every(c => !c.element || c.minimized)) {
                    stopActiveChatsPolling();
                }
            }

            function createChatBubble(friendId, friendUsername, friendPfp) {
                const validUsername = friendUsername || (openChats[friendId] ? openChats[friendId].username : "Chat");
                const validPfp = friendPfp || (openChats[friendId] ? openChats[friendId].pfp : "");

                if (chatBubbles[friendId] && chatBubbles[friendId].element) {
                    chatBubbles[friendId].username = validUsername;
                    chatBubbles[friendId].pfp = validPfp;
                    if(chatBubbles[friendId].element) chatBubbles[friendId].element.title = validUsername;
                    updateBubbleUnreadCount(friendId);
                    return;
                }
                if (openChats[friendId] && openChats[friendId].element && !openChats[friendId].minimized) return;

                const pfpSrc = validPfp ? `${STATIC_PFP_PATH_BASE}${validPfp}` : '';
                const pfpPlaceholder = validUsername ? validUsername.charAt(0).toUpperCase() : 'U';

                const bubble = document.createElement('div');
                bubble.className = 'emb-chat-bubble';
                bubble.dataset.friendId = friendId;
                bubble.title = validUsername;
                bubble.innerHTML = `
                ${pfpSrc ? `<img src="${pfpSrc}" alt="${validUsername}" class="emb-pfp">` : `<div class="emb-placeholder-pfp">${pfpPlaceholder}</div>`}
                <button class="emb-bubble-close-btn" title="Close Chat">&times;</button>
                <span class="emb-unread-message-indicator" style="display:none;">0</span>
                `;
                embeddedChatContainer.insertBefore(bubble, embeddedChatContainer.firstChild);
                chatBubbles[friendId] = { username: validUsername, pfp: validPfp, element: bubble };

                if (!openChats[friendId]) {
                    openChats[friendId] = {
                        username: validUsername, pfp: validPfp, minimized: true, isExplicitlyClosed: false, element: null, lastMsgId: 0, lastRead: new Date(0).toISOString()
                    };
                } else {
                    openChats[friendId].username = validUsername;
                    openChats[friendId].pfp = validPfp;
                    openChats[friendId].minimized = true;
                    openChats[friendId].element = null;
                }
                bubble.addEventListener('click', (e) => {
                    if (e.target.classList.contains('emb-bubble-close-btn')) return;
                    maximizeChatFromBubble(friendId, validUsername, validPfp);
                });
                bubble.querySelector('.emb-bubble-close-btn').addEventListener('click', (e) => {
                    e.stopPropagation();
                    closeChat(friendId);
                });
                updateBubbleUnreadCount(friendId);
                saveChatStates();
            }

            function maximizeChatFromBubble(friendId, usernameFromBubble, pfpFromBubble) {
                const chatState = openChats[friendId];
                if (!chatState) {
                    createChatBox(friendId, usernameFromBubble, pfpFromBubble, true);
                    if(openChats[friendId]) openChats[friendId].isExplicitlyClosed = false;
                    return;
                }
                chatState.isExplicitlyClosed = false;
                chatState.minimized = false;
                if (chatBubbles[friendId] && chatBubbles[friendId].element) {
                    chatBubbles[friendId].element.remove();
                    delete chatBubbles[friendId];
                }
                const usernameToUse = usernameFromBubble || chatState.username;
                const pfpToUse = pfpFromBubble || chatState.pfp;
                createChatBox(friendId, usernameToUse, pfpToUse, false); // fetchAndUpdateEmbUserStatus is called within createChatBox
                saveChatStates();
            }

            async function fetchAndRenderHistory(friendId, loadOlder = false) {
                const chat = openChats[friendId];
                if (!chat || !chat.messagesElement || !chat.username) return;
                let apiUrl = `${EMB_DM_HISTORY_API_URL_BASE}${chat.username}`;
                const currentLastMsgId = chat.lastMsgId || 0;
                if (!loadOlder && currentLastMsgId > 0) apiUrl += `?since_message_id=${currentLastMsgId}`;

                try {
                    const response = await fetch(apiUrl, { headers: { 'X-CSRFToken': CSRF_TOKEN } });
                    if (!response.ok) {
                        if(response.status === 404 && chat.element) {
                            if(typeof showToast === 'function') showToast(`Chat with ${chat.username} is no longer available.`, "warning");
                            closeChat(friendId);
                        }
                        return;
                    }
                    const data = await response.json();
                    if (data.status === 'success' && data.messages) {
                        let newMessagesRendered = false;
                        let latestTimestampThisFetch = chat.lastRead || new Date(0).toISOString();
                        data.messages.sort((a, b) => a.id - b.id);
                        data.messages.forEach(msg => {
                            if (!chat.messagesElement.querySelector(`.dc-message-wrapper[data-message-id="${msg.id}"]`)) {
                                renderMessage(friendId, msg);
                                newMessagesRendered = true;
                                if (msg.id > chat.lastMsgId) chat.lastMsgId = msg.id;
                                if (msg.timestamp > latestTimestampThisFetch) latestTimestampThisFetch = msg.timestamp;
                            }
                        });
                        if (newMessagesRendered && !loadOlder) scrollToBottom(friendId);
                        if (!chat.minimized && chat.element && document.hasFocus() && newMessagesRendered) {
                            const nowISO = new Date().toISOString();
                            chat.lastRead = latestTimestampThisFetch > nowISO ? latestTimestampThisFetch : nowISO;
                            updateBubbleUnreadVisuals(friendId, 0);
                        }
                        saveChatStates();
                    } else if (data.status !== 'success') {
                        console.error(`API error fetching history for ${chat.username}: ${data.message}`);
                    }
                } catch (error) {
                    console.error(`Network or JSON error fetching history for ${chat.username}:`, error);
                }
            }

            function renderMessage(friendId, msg) {
                const chat = openChats[friendId];
                if (!chat || !chat.messagesElement) return;
                const isSent = msg.sender_id === CURRENT_USER_ID;
                const wrapper = document.createElement('div');
                wrapper.className = `dc-message-wrapper ${isSent ? 'sent' : 'received'}`;
                wrapper.dataset.messageId = msg.id;

                const pfpFilename = isSent ? CURRENT_USER_PFP_FILENAME : msg.sender_profile_picture_filename;
                const pfpUsername = isSent ? CURRENT_USER_USERNAME : (msg.sender_username || 'User');
                const pfpInitial = pfpUsername.charAt(0).toUpperCase();
                let pfpHTML = pfpFilename ?
                `<div class="dc-pfp-container-bubble"><img src="${STATIC_PFP_PATH_BASE}${pfpFilename}" alt="${escapeHtml(pfpUsername)}'s PFP" class="dc-pfp"></div>` :
                `<div class="dc-pfp-placeholder-bubble">${pfpInitial}</div>`;

                let fileHTML = '';
                if (msg.shared_file) {
                    const sf = msg.shared_file;
                    fileHTML = `<div class="dc-message-file-attachment"><p class="dc-file-name"><a href="${sf.download_url}" target="_blank" download="${escapeHtml(sf.original_filename)}">${escapeHtml(sf.original_filename)}</a></p><div class="dc-file-preview">`;
                    if (sf.mime_type && sf.view_url) {
                        if (sf.mime_type.startsWith('image/')) fileHTML += `<img src="${sf.view_url}" alt="Preview" style="cursor:pointer;" onclick="window.open('${sf.view_url}', '_blank');">`;
                        else if (sf.mime_type.startsWith('video/')) fileHTML += `<video src="${sf.view_url}" controls></video>`;
                        else if (sf.mime_type.startsWith('audio/')) fileHTML += `<audio src="${sf.view_url}" controls></audio>`;
                        else if (sf.mime_type === 'text/plain' && typeof sf.preview_content !== 'undefined') fileHTML += `<div class="dc-text-file-preview"><pre>${escapeHtml(sf.preview_content)}</pre></div>`;
                    }
                    fileHTML += `</div></div>`;
                }
                wrapper.innerHTML = `
                ${pfpHTML}
                <div class="dc-message">
                <div class="dc-message-header">
                <a href="${USER_PROFILE_URL_BASE}${escapeHtml(pfpUsername)}" class="dc-message-sender" target="_blank">${escapeHtml(pfpUsername)}</a>
                <span class="dc-message-timestamp">${formatTimestamp(msg.timestamp)}</span>
                </div>
                <p class="dc-message-content">${msg.content ? escapeHtml(msg.content) : ''}</p>
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
                        if(typeof showToast === 'function') showToast(`File exceeds max size of ${MAX_UPLOAD_MB_CONFIG}MB.`, 'danger');
                        chat.fileInputElement.value = null;
                        return;
                    }
                    formData.append('file', file);
                }
                const sendButton = chat.element.querySelector('.emb-send-btn');
                chat.inputElement.disabled = true;
                if(sendButton) sendButton.disabled = true;
                try {
                    const response = await fetch(`${EMB_DM_SEND_API_URL_BASE}${chat.username}`, { method: 'POST', headers: { 'X-CSRFToken': CSRF_TOKEN, 'Accept': 'application/json' }, body: formData });
                    const data = await response.json();
                    if (response.ok && data.status === 'success' && data.message) {
                        renderMessage(friendId, data.message);
                        scrollToBottom(friendId);
                        if (data.message.id > chat.lastMsgId) chat.lastMsgId = data.message.id;
                        chat.inputElement.value = '';
                        chat.fileInputElement.value = null;
                        autoResizeTextarea(chat.inputElement);
                        chat.lastRead = new Date().toISOString();
                        saveChatStates();
                    } else {
                        if(typeof showToast === 'function') showToast(data.message || 'Could not send message.', 'danger');
                    }
                } catch (error) {
                    if(typeof showToast === 'function') showToast('Network error sending DM.', 'danger');
                } finally {
                    chat.inputElement.disabled = false;
                    if(sendButton) sendButton.disabled = false;
                    if (chat.inputElement) chat.inputElement.focus();
                }
            }

            // --- START: New function to fetch and update user status in embedded chat header ---
            async function fetchAndUpdateEmbUserStatus(friendId) {
                if (!API_USERS_ACTIVITY_STATUS_URL || !CSRF_TOKEN) {
                    console.warn("Activity status API URL or CSRF token not defined for embedded chat status.");
                    return;
                }
                const indicator = document.getElementById(`emb-status-indicator-${friendId}`);
                const statusTextElement = document.getElementById(`emb-status-text-${friendId}`);

                if (!indicator || !statusTextElement) {
                    // Elements might not be in DOM if chatbox is not fully created or was removed
                    return;
                }

                try {
                    const response = await fetch(API_USERS_ACTIVITY_STATUS_URL, {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json',
                            'X-CSRFToken': CSRF_TOKEN
                        },
                        body: JSON.stringify({ user_ids: [friendId] }) // API expects a list
                    });
                    if (!response.ok) {
                        throw new Error(`Network response was not ok: ${response.status}`);
                    }
                    const data = await response.json();

                    if (data.user_statuses && data.user_statuses[friendId]) {
                        const status = data.user_statuses[friendId]; // 'online', 'afk', 'offline'

                        indicator.classList.remove('online', 'afk', 'offline');
                        indicator.classList.add(status);

                        let displayStatus = 'Offline';
                        if (status === 'online') displayStatus = 'Online';
                        else if (status === 'afk') displayStatus = 'Away';
                        statusTextElement.textContent = displayStatus;
                    } else {
                        // Default to offline if status not found
                        indicator.classList.remove('online', 'afk');
                        indicator.classList.add('offline');
                        statusTextElement.textContent = 'Offline';
                    }
                } catch (error) {
                    console.error(`Error fetching activity status for friend ${friendId} in embedded chat:`, error);
                    // Default to offline on error
                    if (indicator) {
                        indicator.classList.remove('online', 'afk');
                        indicator.classList.add('offline');
                    }
                    if (statusTextElement) {
                        statusTextElement.textContent = 'Offline';
                    }
                }
            }
            // --- END: New function ---


            function scrollToBottom(friendId) {
                const chat = openChats[friendId];
                if (chat && chat.messagesElement) setTimeout(() => chat.messagesElement.scrollTop = chat.messagesElement.scrollHeight, 50);
            }
            function autoResizeTextarea(textarea) {
                if(!textarea) return;
                textarea.style.height = 'auto';
                const newScrollHeight = textarea.scrollHeight;
                textarea.style.height = (newScrollHeight > 80 ? 80 : newScrollHeight) + 'px';
            }
            function formatTimestamp(isoString) {
                if (!isoString) return 'Sending...';
                try {
                    const date = new Date(isoString);
                    return isNaN(date.getTime()) ? 'Invalid Date' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: true });
                } catch (e) { return 'Invalid Date'; }
            }
            function escapeHtml(unsafe) {
                if (unsafe === null || typeof unsafe === 'undefined') return '';
                return unsafe.toString().replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
            }

            function startActiveChatsPolling() {
                stopActiveChatsPolling();
                const activeChatIds = Object.keys(openChats).filter(id => openChats[id].element && !openChats[id].minimized && openChats[id].username);
                if (activeChatIds.length > 0) {
                    embChatPollTimerId = setInterval(pollActiveChats, currentEmbChatPollingInterval);
                    pollActiveChats();
                }
            }
            function stopActiveChatsPolling() {
                if (embChatPollTimerId) clearInterval(embChatPollTimerId);
                embChatPollTimerId = null;
            }
            function pollActiveChats() {
                Object.keys(openChats).forEach(friendId => {
                    const chat = openChats[friendId];
                    if (chat && chat.element && !chat.minimized && chat.username) {
                        fetchAndRenderHistory(friendId, false);
                        // Optionally, refresh status here too if more frequent updates are desired for open chats
                        // fetchAndUpdateEmbUserStatus(friendId); // This would poll status for all open chats
                    }
                });
            }

            function startRecentMessagesPolling() {
                stopRecentMessagesPolling();
                recentMsgPollTimerId = setInterval(pollForRecentMessages, RECENT_MSG_POLLING_INTERVAL);
                pollForRecentMessages();
            }
            function stopRecentMessagesPolling() {
                if (recentMsgPollTimerId) clearInterval(recentMsgPollTimerId);
                recentMsgPollTimerId = null;
            }

            async function pollForRecentMessages() {
                try {
                    const response = await fetch(EMB_DM_RECENT_MESSAGES_API_URL, { headers: { 'X-CSRFToken': CSRF_TOKEN } });
                    if (!response.ok) throw new Error(`HTTP error! status: ${response.status}`);
                    const data = await response.json();

                    if (data.status === 'success' && data.recent_messages) {
                        let stateChangedThisPoll = false;
                        data.recent_messages.forEach(msg => {
                            const friendId = String(msg.sender_id);
                            if (friendId === String(CURRENT_USER_ID)) return;
                            if (openChats[friendId] && openChats[friendId].element && !openChats[friendId].minimized) return;

                            let currentChatState = openChats[friendId];
                            let isGenuinelyNewMessageForBubble = false;

                            if (!currentChatState) {
                                openChats[friendId] = {
                                    username: msg.sender_username, pfp: msg.sender_profile_picture_filename, minimized: true, isExplicitlyClosed: false, lastMsgId: msg.message_id, lastRead: new Date(0).toISOString(), element: null
                                };
                                currentChatState = openChats[friendId];
                                isGenuinelyNewMessageForBubble = true;
                                stateChangedThisPoll = true;
                            } else {
                                currentChatState.username = msg.sender_username;
                                currentChatState.pfp = msg.sender_profile_picture_filename;
                                if (msg.message_id > (currentChatState.lastMsgId || 0)) {
                                    isGenuinelyNewMessageForBubble = true;
                                    currentChatState.lastMsgId = msg.message_id;
                                    stateChangedThisPoll = true;
                                    if (currentChatState.isExplicitlyClosed) currentChatState.isExplicitlyClosed = false;
                                }
                            }
                            if (isGenuinelyNewMessageForBubble && !currentChatState.isExplicitlyClosed) {
                                if (!chatBubbles[friendId] || !chatBubbles[friendId].element) {
                                    createChatBubble(friendId, currentChatState.username, currentChatState.pfp);
                                } else {
                                    updateBubbleUnreadCount(friendId);
                                }
                                if (notificationSound) notificationSound.play().catch(error => console.warn("Notification sound failed.", error));
                            } else if (currentChatState.isExplicitlyClosed && chatBubbles[friendId] && chatBubbles[friendId].element) {
                                chatBubbles[friendId].element.remove();
                                delete chatBubbles[friendId];
                                stateChangedThisPoll = true;
                            }
                        });
                        if (stateChangedThisPoll) saveChatStates();
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
                            indicator.textContent = count > 9 ? '9+' : count;
                            indicator.style.display = 'flex';
                        } else {
                            indicator.style.display = 'none';
                        }
                    }
                }
            }

            async function updateBubbleUnreadCount(friendId) {
                const chatState = openChats[friendId];
                if (!chatState || !chatState.username) {
                    updateBubbleUnreadVisuals(friendId, 0);
                    return;
                }
                const lastReadTime = chatState.lastRead || new Date(0).toISOString();
                let unreadCount = 0;
                try {
                    const historyUrl = `${EMB_DM_HISTORY_API_URL_BASE}${chatState.username}?since_message_id=0`;
                    const response = await fetch(historyUrl, { headers: { 'X-CSRFToken': CSRF_TOKEN }});
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
                    updateBubbleUnreadVisuals(friendId, 0);
                }
            }
});
