// static/group_chat.js

// --- Global variable declarations ---
let chatHistoryDiv;
let chatForm;
let messageInput;
let fileInput;
let sendButton;

// For editing
let editMessageContainer;
let editMessageInput;
let saveEditButton;
let cancelEditButton;
let currentEditingMessageId = null;

let currentUserIdGlobal;
let csrfTokenGlobal;
let historyApiUrlGlobal;
let sendApiUrlGlobal;
let editApiUrlBaseGlobal;   // For editing messages
let deleteApiUrlBaseGlobal; // For deleting messages
let isAdminGlobal = false; // Initialize admin status (needs to be set in initChat)

let lastMessageId = 0;
let pollingInterval = 500; // Poll every 0.5 seconds
let pollTimerId = null;     // Initialize as null
let isShiftHeld = false;
let clientMaxKnownEditTimestamp = null; // Track latest known edit/update timestamp (ISO string)

// --- Helper Functions ---

/**
 * Scrolls the chat history div to the bottom if scrollable.
 * Uses a small timeout to allow DOM updates to render first.
 */
function scrollToBottom() {
    setTimeout(() => {
        if (chatHistoryDiv) {
            const scrollHeight = chatHistoryDiv.scrollHeight;
            const clientHeight = chatHistoryDiv.clientHeight;
            if (scrollHeight > clientHeight) {
                chatHistoryDiv.scrollTop = scrollHeight;
            }
        } else {
            console.error("[Group Chat] scrollToBottom: chatHistoryDiv not found!");
        }
    }, 1);
}

/**
 * Resizes the textarea height based on its content.
 * @param {HTMLTextAreaElement} textarea - The textarea element to resize.
 */
function resizeTextarea(textarea) {
    if (!textarea) return;
    requestAnimationFrame(() => {
        textarea.style.height = 'auto';
        const newScrollHeight = textarea.scrollHeight;
        textarea.style.height = (newScrollHeight + 2) + 'px';
    });
}

/**
 * Formats an ISO timestamp string into a locale-friendly string.
 * @param {string} isoString - The ISO timestamp string.
 * @returns {string} - The formatted date/time string or 'Invalid Date'.
 */
function formatTimestamp(isoString) {
    try {
        const date = new Date(isoString);
        if (isNaN(date.getTime())) {
            console.warn("[Group Chat] Invalid timestamp received:", isoString);
            return 'Invalid Date';
        }
        return date.toLocaleString([], { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true });
    } catch (e) {
        console.error("[Group Chat] Error formatting timestamp:", isoString, e);
        return 'Invalid Date';
    }
}

/**
 * Renders a single message object into the chat history div.
 * This function should only be called for messages that are not soft-deleted.
 * @param {object} msg - The message object from the backend.
 * @param {boolean} isInitialLoad - Flag indicating if this is part of the initial page load.
 */
function renderMessage(msg, isInitialLoad = false) {
    // Remove 'empty chat' message if it exists
    const emptyChatMsg = document.getElementById('empty-chat-msg');
    if (emptyChatMsg && emptyChatMsg.parentNode === chatHistoryDiv) {
        chatHistoryDiv.removeChild(emptyChatMsg);
    }

    const messageWrapper = document.createElement('div');
    messageWrapper.classList.add('chat-message-wrapper');
    messageWrapper.dataset.messageId = msg.id;
    if (msg.edited_at) {
        messageWrapper.dataset.editedAt = msg.edited_at;
    }
    if (msg.user_id === currentUserIdGlobal) {
        messageWrapper.classList.add('current-user');
    }

    const pfpDiv = document.createElement('div');
    pfpDiv.classList.add('chat-message-pfp-container');

    const pfpImg = document.createElement('img');
    pfpImg.classList.add('chat-message-pfp');
    if (msg.sender_profile_picture_filename) {
        // Construct the URL assuming pics are in static/uploads/profile_pics/
        pfpImg.src = `/static/uploads/profile_pics/${msg.sender_profile_picture_filename}`;
        pfpImg.alt = `${msg.sender_username}'s profile picture`;
    } else {
        // Fallback to a default image or placeholder if needed
        pfpImg.src = '/static/icons/default-pfp.png'; // CREATE a default image or remove this line
        pfpImg.alt = 'Default profile picture';
    }
    pfpDiv.appendChild(pfpImg);

    const messageDiv = document.createElement('div');
    messageDiv.classList.add('chat-message');
    messageDiv.style.position = 'relative'; // For absolute positioning of actions

    // Header
    const headerDiv = document.createElement('div');
    headerDiv.classList.add('message-header');
    const senderLink = document.createElement('a'); // Create an anchor tag
    senderLink.href = `/user/${msg.sender_username}`; // Link to the user's profile
    senderLink.classList.add('message-sender');
    senderLink.textContent = msg.sender_username || `User ${msg.user_id}`;
    headerDiv.appendChild(senderLink);
    const senderSpan = document.createElement('span');
    senderSpan.classList.add('message-sender');
    const timestampSpan = document.createElement('span');
    timestampSpan.classList.add('message-timestamp');
    timestampSpan.textContent = formatTimestamp(msg.timestamp);

    const editedSpan = document.createElement('span');
    editedSpan.classList.add('message-edited-marker');
    editedSpan.style.fontSize = '0.8em';
    editedSpan.style.marginLeft = '5px';
    editedSpan.style.opacity = '0.7';
    if (msg.is_edited) {
        editedSpan.textContent = '(edited)';
    }

    headerDiv.appendChild(senderSpan);
    headerDiv.appendChild(timestampSpan);
    headerDiv.appendChild(editedSpan);
    messageDiv.appendChild(headerDiv);

    // Content Paragraph
    const contentP = document.createElement('p');
    contentP.classList.add('message-content');
    if (msg.content) {
        contentP.textContent = msg.content;
    } else if (msg.shared_file && !msg.content) {
        contentP.innerHTML = '&nbsp;'; // Keep P tag for structure if only file
    }
    messageDiv.appendChild(contentP);

    // File Attachment Logic
    if (msg.shared_file) {
        const fileDiv = document.createElement('div');
        fileDiv.classList.add('message-file-attachment');
        const fileNameP = document.createElement('p');
        fileNameP.classList.add('file-name');
        fileNameP.textContent = `Attachment: `;
        const fileLink = document.createElement('a');
        fileLink.href = msg.shared_file.download_url || '#';
        fileLink.textContent = msg.shared_file.original_filename || 'file';
        if (msg.shared_file.original_filename) fileLink.setAttribute('download', msg.shared_file.original_filename);
        fileLink.target = "_blank";
        fileNameP.appendChild(fileLink);
        fileDiv.appendChild(fileNameP);

        const previewContainer = document.createElement('div');
        previewContainer.classList.add('file-preview');
        const mimeType = msg.shared_file.mime_type;
        const viewUrl = msg.shared_file.view_url;
        if (mimeType && viewUrl) {
            if (mimeType.startsWith('image/')) {
                const img = document.createElement('img');
                img.src = viewUrl; img.alt = `Preview`; img.style.cursor = 'pointer';
                img.onclick = () => window.open(viewUrl, '_blank');
                previewContainer.appendChild(img);
            } else if (mimeType.startsWith('video/')) {
                const video = document.createElement('video');
                video.src = viewUrl; video.controls = true;
                previewContainer.appendChild(video);
            } else if (mimeType.startsWith('audio/')) {
                const audio = document.createElement('audio');
                audio.src = viewUrl; audio.controls = true;
                previewContainer.appendChild(audio);
            } else if (mimeType === 'text/plain' && msg.shared_file.preview_content) {
                const textPreviewDiv = document.createElement('div');
                textPreviewDiv.classList.add('text-file-preview');
                const pre = document.createElement('pre');
                pre.textContent = msg.shared_file.preview_content || '[No preview]';
                textPreviewDiv.appendChild(pre);
                previewContainer.appendChild(textPreviewDiv);
            }
        } else if (mimeType) {
            const p = document.createElement('p'); p.textContent = `(${mimeType})`; previewContainer.appendChild(p);
        }
        if (previewContainer.hasChildNodes()) fileDiv.appendChild(previewContainer);
        messageDiv.appendChild(fileDiv);
    }

    // Edit/Delete Buttons Logic
    if (msg.user_id === currentUserIdGlobal || isAdminGlobal) {
        const actionsDiv = document.createElement('div');
        actionsDiv.classList.add('message-actions');
        actionsDiv.style.position = 'absolute';
        actionsDiv.style.top = '5px';
        actionsDiv.style.right = '5px';
        actionsDiv.style.display = 'none';
        actionsDiv.style.gap = '5px';
        actionsDiv.style.background = 'rgba(50, 50, 50, 0.7)';
        actionsDiv.style.padding = '2px 4px';
        actionsDiv.style.borderRadius = '4px';
        actionsDiv.style.zIndex = '5';

        if (msg.user_id === currentUserIdGlobal && !msg.shared_file) { // Edit only own text messages
            const editButton = document.createElement('button');
            editButton.classList.add('btn', 'btn-sm', 'btn-edit-message');
            editButton.innerHTML = `<img src="/static/icons/edit.svg" alt="Edit" style="width:0.9em; height:0.9em; vertical-align: middle;">`;
            editButton.style.lineHeight = '1';
            editButton.title = "Edit message";
            editButton.onclick = () => handleEditMessageClick(msg.id, contentP.textContent);
            actionsDiv.appendChild(editButton);
        }

        if (msg.user_id === currentUserIdGlobal || isAdminGlobal) { // Delete own or any if admin
            const deleteButton = document.createElement('button');
            deleteButton.classList.add('btn', 'btn-sm', 'btn-delete-message');
            deleteButton.innerHTML = `<img src="/static/icons/trash.svg" alt="Delete" style="width:0.9em; height:0.9em; vertical-align: middle;">`;
            deleteButton.style.lineHeight = '1';
            deleteButton.title = "Delete message";
            deleteButton.onclick = () => handleDeleteMessageClick(msg.id);
            actionsDiv.appendChild(deleteButton);
        }

        if (actionsDiv.hasChildNodes()) {
            messageDiv.appendChild(actionsDiv);
        }
    }

    if (msg.user_id !== currentUserIdGlobal) {
        messageWrapper.appendChild(pfpDiv); // PFP first for received messages
    }
    messageWrapper.appendChild(messageDiv);
    if (msg.user_id === currentUserIdGlobal) {
        messageWrapper.appendChild(pfpDiv); // PFP last for sent messages
    }
    chatHistoryDiv.appendChild(messageWrapper);

    // Update clientMaxKnownEditTimestamp when rendering/updating any message that has an edit timestamp
    if (msg.edited_at) {
        if (!clientMaxKnownEditTimestamp || msg.edited_at > clientMaxKnownEditTimestamp) {
            clientMaxKnownEditTimestamp = msg.edited_at;
        }
    }

    // Update lastMessageId (ID of the last message processed, not necessarily rendered)
    if (!isInitialLoad && msg.id > lastMessageId) {
        lastMessageId = msg.id;
    } else if (isInitialLoad && msg.id > lastMessageId) {
        lastMessageId = msg.id;
    }
}


// --- Core Functions ---

/**
 * Initializes the chat interface elements and functionality.
 */
function initChat(initialHistory, userId, csrf, historyUrl, sendUrl, editUrlBase, deleteUrlBase, isAdmin = false) {
    chatHistoryDiv = document.getElementById('chat-history');
    chatForm = document.getElementById('chat-form');
    messageInput = document.getElementById('message-input');
    fileInput = document.getElementById('file-input');
    sendButton = document.getElementById('send-button');

    editMessageContainer = document.getElementById('edit-message-container');
    editMessageInput = document.getElementById('edit-message-input');
    saveEditButton = document.getElementById('save-edit-button');
    cancelEditButton = document.getElementById('cancel-edit-button');

    if (!chatHistoryDiv || !chatForm || !messageInput || !fileInput || !sendButton || !editMessageContainer || !editMessageInput || !saveEditButton || !cancelEditButton) {
        console.error("[Group Chat] Initialization failed: Essential elements missing.");
        if (typeof showToast === 'function') showToast("Chat UI Error.", "danger", 10000);
        return;
    }

    currentUserIdGlobal = userId;
    csrfTokenGlobal = csrf;
    historyApiUrlGlobal = historyUrl;
    sendApiUrlGlobal = sendUrl;
    editApiUrlBaseGlobal = editUrlBase;
    deleteApiUrlBaseGlobal = deleteUrlBase;
    isAdminGlobal = isAdmin;

    if (initialHistory && initialHistory.length > 0) {
        const emptyChatMsg = document.getElementById('empty-chat-msg');
        if (emptyChatMsg) emptyChatMsg.remove();

        initialHistory.forEach(msg => {
            // Only render if not soft-deleted during initial load
            if (!msg.is_deleted) {
                renderMessage(msg, true);
            }
            // Track max edit timestamp during initial load from all messages (deleted or not)
            if (msg.edited_at && (!clientMaxKnownEditTimestamp || msg.edited_at > clientMaxKnownEditTimestamp)) {
                clientMaxKnownEditTimestamp = msg.edited_at;
            }
            // Ensure lastMessageId is correctly set from initial history
            if (msg.id > lastMessageId) {
                lastMessageId = msg.id;
            }
        });
        console.log("[Group Chat] Initial load complete. Last message ID:", lastMessageId, "Max known edit TS:", clientMaxKnownEditTimestamp);
    } else {
        console.log("[Group Chat] Initial load - No history.");
    }

    if (messageInput) {
        resizeTextarea(messageInput);
        messageInput.addEventListener('input', function() { resizeTextarea(this); });
        messageInput.addEventListener('keydown', handleMessageInputKeydown);
    }

    chatForm.addEventListener('submit', handleFormSubmit);
    saveEditButton.addEventListener('click', handleSaveEdit);
    cancelEditButton.addEventListener('click', handleCancelEdit);
    editMessageInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter') { event.preventDefault(); handleSaveEdit(); }
        else if (event.key === 'Escape') { handleCancelEdit(); }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Shift' && !isShiftHeld) { isShiftHeld = true; toggleMessageActions(true); }
    });
    document.addEventListener('keyup', (event) => {
        if (event.key === 'Shift') { isShiftHeld = false; if (editMessageContainer.style.display === 'none') toggleMessageActions(false); }
    });
    window.addEventListener('blur', () => {
        if (isShiftHeld) { isShiftHeld = false; if (editMessageContainer.style.display === 'none') toggleMessageActions(false); }
    });

    startPolling();
    scrollToBottom();
    console.log("[Group Chat] Initialization complete.");
}

/**
 * Toggles the visibility of edit/delete buttons on messages.
 */
function toggleMessageActions(show) {
    const actionButtons = document.querySelectorAll('.chat-message .message-actions');
    actionButtons.forEach(actions => {
        actions.style.display = show ? 'flex' : 'none';
    });
}

/**
 * Handles keydown events on the message input textarea.
 */
function handleMessageInputKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (!sendButton.disabled) chatForm.requestSubmit(sendButton);
    }
    resizeTextarea(event.target);
}

/**
 * Handles the chat form submission (sending message/file).
 */
async function handleFormSubmit(event) {
    event.preventDefault();
    if (sendButton.disabled) return;

    const content = messageInput.value.trim();
    const file = fileInput.files[0];

    if (!content && !file) {
        if (typeof showToast === 'function') showToast('Please type a message or attach a file.', 'warning');
        return;
    }

    sendButton.disabled = true;
    if (typeof showToast === 'function') showToast(file ? 'Uploading...' : 'Sending...', 'info', 1500);

    const formData = new FormData();
    formData.append('content', content);
    if (file) formData.append('file', file);

    try {
        const response = await fetch(sendApiUrlGlobal, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfTokenGlobal, 'Accept': 'application/json' },
            body: formData
        });
        const data = await response.json();

        if (response.ok && data.status === 'success') {
            messageInput.value = '';
            fileInput.value = null;
            resizeTextarea(messageInput);
            await fetchNewMessages(); // Fetch updates after sending
            scrollToBottom();
        } else {
            const errorMsg = data.message || 'Could not send message.';
            if (typeof showToast === 'function') showToast(`Error: ${errorMsg}`, 'danger');
        }
    } catch (error) {
        console.error('[Group Chat] Send message error:', error);
        if (typeof showToast === 'function') showToast('Network error sending message.', 'danger');
    } finally {
        sendButton.disabled = false;
    }
}

/**
 * Fetches new messages AND processes potential updates (edits/deletions) from the server.
 */
async function fetchNewMessages() {
    console.log(`[${new Date().toLocaleTimeString()}] Polling: fetchNewMessages called. LastMsgID: ${lastMessageId}, LastEditTS: ${clientMaxKnownEditTimestamp}`);
    if (!historyApiUrlGlobal) {
        console.error("History API URL missing.");
        stopPolling();
        return;
    }
    try {
        let shouldScroll = false;
        if (chatHistoryDiv) {
            shouldScroll = chatHistoryDiv.scrollTop + chatHistoryDiv.clientHeight >= chatHistoryDiv.scrollHeight - 50;
        }

        let fetchUrl = `${historyApiUrlGlobal}?last_message_id=${lastMessageId}`;
        if (clientMaxKnownEditTimestamp) {
            fetchUrl += `&last_edit_ts=${encodeURIComponent(clientMaxKnownEditTimestamp)}`;
        }

        const response = await fetch(fetchUrl);
        if (!response.ok) {
            console.error('[Group Chat] Failed to fetch new messages:', response.status);
            if (response.status === 401 || response.status === 403) {
                if (typeof showToast === 'function') showToast("Session invalid. Please reload.", "danger", 10000);
                stopPolling();
            }
            return;
        }
        const data = await response.json();

        // Process server's latest known edit timestamp (if provided by backend)
        // if (data.latest_server_edit_ts && (!clientMaxKnownEditTimestamp || data.latest_server_edit_ts > clientMaxKnownEditTimestamp)) {
        //     clientMaxKnownEditTimestamp = data.latest_server_edit_ts;
        // }

        if (data.status === 'success' && data.messages && data.messages.length > 0) {
            let messageAddedOrUpdatedOrDeleted = false;
            data.messages.forEach(msg => {
                const existingMessageWrapper = chatHistoryDiv.querySelector(`.chat-message-wrapper[data-message-id="${msg.id}"]`);

                if (existingMessageWrapper) {
                    // --- Message exists in DOM: Check for soft deletion or update ---
                    if (msg.is_deleted) {
                        existingMessageWrapper.remove();
                        console.log(`[Group Chat] Removed soft-deleted message ID ${msg.id} from DOM via polling.`);
                        messageAddedOrUpdatedOrDeleted = true;
                        if (currentEditingMessageId === msg.id && editMessageContainer.style.display !== 'none') {
                            handleCancelEdit();
                            if (typeof showToast === 'function') showToast('Message was deleted.', 'info');
                        }
                    } else {
                        // Message not deleted, proceed with update logic
                        const existingContentEl = existingMessageWrapper.querySelector('.message-content');
                        const existingEditedMarkerEl = existingMessageWrapper.querySelector('.message-edited-marker');
                        const currentWrapperEditTimestamp = existingMessageWrapper.dataset.editedAt || null;
                        let updated = false;

                        if (existingContentEl && existingContentEl.textContent !== msg.content) {
                            existingContentEl.textContent = msg.content;
                            updated = true;
                        }
                        if (existingEditedMarkerEl) {
                            const newMarkerText = msg.is_edited ? '(edited)' : '';
                            if (existingEditedMarkerEl.textContent !== newMarkerText) {
                                existingEditedMarkerEl.textContent = newMarkerText;
                                updated = true;
                            }
                        }
                        if (msg.edited_at && msg.edited_at !== currentWrapperEditTimestamp) {
                            existingMessageWrapper.dataset.editedAt = msg.edited_at;
                            // No explicit 'updated = true' for timestamp change alone, but it's useful for tracking
                        }

                        if (updated) {
                            messageAddedOrUpdatedOrDeleted = true;
                            if (currentEditingMessageId === msg.id && editMessageContainer.style.display !== 'none') {
                                handleCancelEdit();
                                if (typeof showToast === 'function') showToast('Message was updated by another source.', 'info');
                            }
                        }
                    }
                } else {
                    // --- New message: Render only if not soft-deleted ---
                    if (!msg.is_deleted) {
                        renderMessage(msg); // isInitialLoad defaults to false
                        messageAddedOrUpdatedOrDeleted = true;
                    } else {
                        console.log(`[Group Chat] Skipped rendering new message ID ${msg.id} as it's already soft-deleted (via polling).`);
                    }
                }

                // Update lastMessageId with the ID of the last message *processed* from server
                if (msg.id > lastMessageId) {
                    lastMessageId = msg.id;
                }
                // Update clientMaxKnownEditTimestamp with the latest edit timestamp *seen* from server
                if (msg.edited_at) { // This includes regular edits and soft-deletes if backend updates edited_at
                    if (!clientMaxKnownEditTimestamp || msg.edited_at > clientMaxKnownEditTimestamp) {
                        clientMaxKnownEditTimestamp = msg.edited_at;
                    }
                }
            });

            if (messageAddedOrUpdatedOrDeleted && shouldScroll) {
                scrollToBottom();
            }
        }
    } catch (error) {
        console.error('[Group Chat] Error polling or processing messages:', error);
    }
}


// --- Edit Functions ---

/**
 * Handles click on the 'Edit' button for a message.
 */
function handleEditMessageClick(messageId, currentContent) {
    currentEditingMessageId = messageId;
    editMessageInput.value = currentContent;
    editMessageContainer.style.display = 'flex';
    editMessageInput.focus();
    editMessageInput.select();
    toggleMessageActions(true); // Keep actions visible
}

/**
 * Handles saving the edited message content.
 */
async function handleSaveEdit() {
    if (currentEditingMessageId === null) return;
    const newContent = editMessageInput.value.trim();
    if (!newContent) {
        if (typeof showToast === 'function') showToast('Message cannot be empty.', 'warning');
        return;
    }

    editMessageInput.disabled = true;
    saveEditButton.disabled = true;
    cancelEditButton.disabled = true;

    try {
        const response = await fetch(`${editApiUrlBaseGlobal}${currentEditingMessageId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfTokenGlobal, 'Accept': 'application/json' },
            body: JSON.stringify({ content: newContent })
        });
        const data = await response.json();

        if (response.ok && data.status === 'success' && data.updated_message) {
            if (typeof showToast === 'function') showToast('Message updated!', 'success', 1500);

            const messageWrapper = chatHistoryDiv.querySelector(`.chat-message-wrapper[data-message-id="${currentEditingMessageId}"]`);
            if (messageWrapper) {
                const contentElement = messageWrapper.querySelector('.message-content');
                const editedMarker = messageWrapper.querySelector('.message-edited-marker');
                if (contentElement) contentElement.textContent = data.updated_message.content;
                if (editedMarker) editedMarker.textContent = '(edited)';
                if (data.updated_message.edited_at) {
                    messageWrapper.dataset.editedAt = data.updated_message.edited_at;
                    if (!clientMaxKnownEditTimestamp || data.updated_message.edited_at > clientMaxKnownEditTimestamp) {
                        clientMaxKnownEditTimestamp = data.updated_message.edited_at;
                    }
                }
            }
            handleCancelEdit();
        } else {
            const errorMsg = data.message || 'Could not update message.';
            if (typeof showToast === 'function') showToast(`Error: ${errorMsg}`, 'danger');
        }
    } catch (error) {
        console.error('[Group Chat] Edit message network/fetch error:', error);
        if (typeof showToast === 'function') showToast('Network error updating message.', 'danger');
    } finally {
        editMessageInput.disabled = false;
        saveEditButton.disabled = false;
        cancelEditButton.disabled = false;
        if (document.activeElement !== editMessageInput && editMessageContainer.style.display !== 'none') {
            editMessageInput.focus();
        }
    }
}

/**
 * Handles cancelling the message edit operation.
 */
function handleCancelEdit() {
    editMessageContainer.style.display = 'none';
    editMessageInput.value = '';
    currentEditingMessageId = null;
    if (!isShiftHeld) {
        toggleMessageActions(false);
    }
}


// --- Delete Function ---

/**
 * Handles click on the 'Delete' button for a message.
 * This initiates the soft-delete process.
 */
async function handleDeleteMessageClick(messageId) {
    if (!confirm('Are you sure you want to delete this message? This cannot be undone.')) {
        return;
    }
    try {
        const response = await fetch(`${deleteApiUrlBaseGlobal}${messageId}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfTokenGlobal, 'Accept': 'application/json' }
        });
        const data = await response.json();
        if (response.ok && data.status === 'success') {
            if (typeof showToast === 'function') showToast('Message deleted!', 'success');
            // Immediate removal for the user initiating delete.
            // Polling will handle removal for other users.
            const messageWrapper = chatHistoryDiv.querySelector(`.chat-message-wrapper[data-message-id="${messageId}"]`);
            if (messageWrapper) {
                messageWrapper.remove();
            }
            if (currentEditingMessageId === messageId) {
                handleCancelEdit();
            }
            // Optional: Trigger a poll immediately to sync other clients faster,
            // though the regular polling interval will eventually catch it.
            // fetchNewMessages();
        } else {
            const errorMsg = data.message || 'Could not delete message.';
            if (typeof showToast === 'function') showToast(`Error: ${errorMsg}`, 'danger');
        }
    } catch (error) {
        console.error('[Group Chat] Delete message network/fetch error:', error);
        if (typeof showToast === 'function') showToast('Network error deleting message.', 'danger');
    }
}


// --- Polling Control ---

/**
 * Starts polling for new messages.
 */
function startPolling() {
    stopPolling();
    if (pollingInterval > 0 && historyApiUrlGlobal) {
        fetchNewMessages().then(() => { // Initial fetch
            if (!pollTimerId) {
                pollTimerId = setInterval(fetchNewMessages, pollingInterval);
                console.log(`[Group Chat] Polling started (Interval: ${pollingInterval}ms).`);
            }
        });
    } else {
        if (!historyApiUrlGlobal) console.warn("[Group Chat] History API URL missing, polling disabled.");
        else console.warn("[Group Chat] Polling interval invalid or 0, polling disabled.");
    }
}

/**
 * Stops polling for new messages.
 */
function stopPolling() {
    if (pollTimerId) {
        clearInterval(pollTimerId);
        pollTimerId = null;
        console.log("[Group Chat] Polling stopped.");
    }
}

// Initialization is triggered by the inline script in group_chat.html
// which calls initChat() after DOMContentLoaded.
