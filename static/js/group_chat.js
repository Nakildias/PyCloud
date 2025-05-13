// static/js/group_chat.js

// --- Global variable declarations ---
let gcChatHistoryDiv; // Was chatHistoryDiv
let gcChatForm;       // Was chatForm
let gcMessageInput;   // Was messageInput
let gcFileInput;      // Was fileInput
let gcSendButton;     // Was sendButton

// For editing
let gcEditMessageContainer; // Was editMessageContainer
let gcEditMessageInput;     // Was editMessageInput
let gcSaveEditButton;       // Was saveEditButton
let gcCancelEditButton;     // Was cancelEditButton
let currentEditingMessageId = null;

let currentUserIdGlobal;
let csrfTokenGlobal;
let historyApiUrlGlobal;
let sendApiUrlGlobal;
let editApiUrlBaseGlobal;
let deleteApiUrlBaseGlobal;
let isAdminGlobal = false;

let lastMessageId = 0;
let focusedPollingInterval = 1000;
let blurredPollingInterval = 5000;
let currentPollingInterval = focusedPollingInterval;
let pollTimerId = null;
let isShiftHeld = false;
let clientMaxKnownEditTimestamp = null;

// --- Helper Functions ---
function scrollToBottom() {
    setTimeout(() => {
        if (gcChatHistoryDiv) { // Updated variable name
            const scrollHeight = gcChatHistoryDiv.scrollHeight;
            const clientHeight = gcChatHistoryDiv.clientHeight;
            if (scrollHeight > clientHeight) {
                gcChatHistoryDiv.scrollTop = scrollHeight;
            }
        } else {
            console.error("[Group Chat] scrollToBottom: gcChatHistoryDiv not found!");
        }
    }, 1);
}

function resizeTextarea(textarea) {
    if (!textarea) return;
    requestAnimationFrame(() => {
        textarea.style.height = 'auto';
        const newScrollHeight = textarea.scrollHeight;
        textarea.style.height = (newScrollHeight + 2) + 'px';
    });
}

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

function renderMessage(msg, isInitialLoad = false) {
    const emptyChatMsg = document.getElementById('gc-empty-chat-msg'); // Updated ID
    if (emptyChatMsg && emptyChatMsg.parentNode === gcChatHistoryDiv) {
        gcChatHistoryDiv.removeChild(emptyChatMsg);
    }

    const messageWrapper = document.createElement('div');
    messageWrapper.classList.add('gc-chat-message-wrapper'); // Updated class
    messageWrapper.dataset.messageId = msg.id;
    if (msg.edited_at) {
        messageWrapper.dataset.editedAt = msg.edited_at;
    }
    if (msg.user_id === currentUserIdGlobal) {
        messageWrapper.classList.add('current-user'); // Modifier class
    }

    const pfpDiv = document.createElement('div');
    pfpDiv.classList.add('gc-chat-message-pfp-container'); // Updated class

    const pfpImg = document.createElement('img');
    pfpImg.classList.add('gc-chat-message-pfp'); // Updated class
    if (msg.sender_profile_picture_filename) {
        pfpImg.src = `/static/uploads/profile_pics/${msg.sender_profile_picture_filename}`;
        pfpImg.alt = `${msg.sender_username}'s profile picture`;
    } else {
        pfpImg.src = '/static/icons/default-pfp.svg';
        pfpImg.alt = 'Default profile picture';
    }
    pfpDiv.appendChild(pfpImg);

    const messageDiv = document.createElement('div');
    messageDiv.classList.add('gc-chat-message'); // Updated class
    messageDiv.style.position = 'relative';

    const headerDiv = document.createElement('div');
    headerDiv.classList.add('gc-message-header'); // Updated class
    const senderLink = document.createElement('a');
    senderLink.href = `/user/${msg.sender_username}`;
    senderLink.classList.add('gc-message-sender'); // Updated class
    senderLink.textContent = msg.sender_username || `User ${msg.user_id}`;
    headerDiv.appendChild(senderLink);

    const timestampSpan = document.createElement('span');
    timestampSpan.classList.add('gc-message-timestamp'); // Updated class
    timestampSpan.textContent = formatTimestamp(msg.timestamp);
    headerDiv.appendChild(timestampSpan);

    const editedSpan = document.createElement('span');
    editedSpan.classList.add('gc-message-edited-marker'); // Updated class
    if (msg.is_edited) {
        editedSpan.textContent = '(edited)';
    }
    headerDiv.appendChild(editedSpan);
    messageDiv.appendChild(headerDiv);

    const contentP = document.createElement('p');
    contentP.classList.add('gc-message-content'); // Updated class
    if (msg.content) {
        contentP.textContent = msg.content;
    } else if (msg.shared_file && !msg.content) {
        contentP.innerHTML = '&nbsp;';
    }
    messageDiv.appendChild(contentP);

    if (msg.shared_file) {
        const fileDiv = document.createElement('div');
        fileDiv.classList.add('gc-message-file-attachment'); // Updated class
        const fileNameP = document.createElement('p');
        fileNameP.classList.add('gc-file-name'); // Updated class
        fileNameP.textContent = `Attachment: `;
        const fileLink = document.createElement('a');
        fileLink.href = msg.shared_file.download_url || '#';
        fileLink.textContent = msg.shared_file.original_filename || 'file';
        if (msg.shared_file.original_filename) fileLink.setAttribute('download', msg.shared_file.original_filename);
        fileLink.target = "_blank";
        fileNameP.appendChild(fileLink);
        fileDiv.appendChild(fileNameP);

        const previewContainer = document.createElement('div');
        previewContainer.classList.add('gc-file-preview'); // Updated class
        const mimeType = msg.shared_file.mime_type;
        const viewUrl = msg.shared_file.view_url;
        if (mimeType && viewUrl) {
            if (mimeType.startsWith('image/')) {
                const img = document.createElement('img'); img.src = viewUrl; img.alt = `Preview`; img.style.cursor = 'pointer';
                img.onclick = () => window.open(viewUrl, '_blank'); previewContainer.appendChild(img);
            } else if (mimeType.startsWith('video/')) {
                const video = document.createElement('video'); video.src = viewUrl; video.controls = true; previewContainer.appendChild(video);
            } else if (mimeType.startsWith('audio/')) {
                const audio = document.createElement('audio'); audio.src = viewUrl; audio.controls = true; previewContainer.appendChild(audio);
            } else if (mimeType === 'text/plain' && msg.shared_file.preview_content) {
                const textPreviewDiv = document.createElement('div');
                textPreviewDiv.classList.add('gc-text-file-preview'); // Updated class
                const pre = document.createElement('pre'); pre.textContent = msg.shared_file.preview_content || '[No preview]';
                textPreviewDiv.appendChild(pre); previewContainer.appendChild(textPreviewDiv);
            }
        } else if (mimeType) {
            const p = document.createElement('p'); p.textContent = `(${mimeType})`; previewContainer.appendChild(p);
        }
        if (previewContainer.hasChildNodes()) fileDiv.appendChild(previewContainer);
        messageDiv.appendChild(fileDiv);
    }

    if (msg.user_id === currentUserIdGlobal || isAdminGlobal) {
        const actionsDiv = document.createElement('div');
        actionsDiv.classList.add('gc-message-actions'); // Updated class
        actionsDiv.style.position = 'absolute'; actionsDiv.style.top = '5px'; actionsDiv.style.right = '5px';
        actionsDiv.style.display = 'none'; actionsDiv.style.gap = '5px';
        actionsDiv.style.background = 'rgba(50, 50, 50, 0.7)'; actionsDiv.style.padding = '2px 4px';
        actionsDiv.style.borderRadius = '4px'; actionsDiv.style.zIndex = '5';

        if (msg.user_id === currentUserIdGlobal && !msg.shared_file) {
            const editButton = document.createElement('button');
            editButton.classList.add('btn', 'btn-sm', 'gc-btn-edit-message'); // Added specific class
            editButton.innerHTML = `<img src="/static/icons/edit.svg" alt="Edit" style="width:0.9em; height:0.9em; vertical-align: middle;">`;
            editButton.title = "Edit message";
            editButton.onclick = () => handleEditMessageClick(msg.id, contentP.textContent);
            actionsDiv.appendChild(editButton);
        }
        if (msg.user_id === currentUserIdGlobal || isAdminGlobal) {
            const deleteButton = document.createElement('button');
            deleteButton.classList.add('btn', 'btn-sm', 'gc-btn-delete-message'); // Added specific class
            deleteButton.innerHTML = `<img src="/static/icons/trash.svg" alt="Delete" style="width:0.9em; height:0.9em; vertical-align: middle;">`;
            deleteButton.title = "Delete message";
            deleteButton.onclick = () => handleDeleteMessageClick(msg.id);
            actionsDiv.appendChild(deleteButton);
        }
        if (actionsDiv.hasChildNodes()) messageDiv.appendChild(actionsDiv);
    }

    if (msg.user_id !== currentUserIdGlobal) messageWrapper.appendChild(pfpDiv);
    messageWrapper.appendChild(messageDiv);
    if (msg.user_id === currentUserIdGlobal) messageWrapper.appendChild(pfpDiv);

    gcChatHistoryDiv.appendChild(messageWrapper); // Updated variable

    if (msg.edited_at && (!clientMaxKnownEditTimestamp || msg.edited_at > clientMaxKnownEditTimestamp)) {
        clientMaxKnownEditTimestamp = msg.edited_at;
    }
    if (msg.id > lastMessageId) lastMessageId = msg.id;
}

function initChat(initialHistory, userId, csrf, historyUrl, sendUrl, editUrlBase, deleteUrlBase, isAdminUser = false) {
    gcChatHistoryDiv = document.getElementById('gc-chat-history'); // Updated ID
    gcChatForm = document.getElementById('gc-chat-form');           // Updated ID
    gcMessageInput = document.getElementById('gc-message-input');   // Updated ID
    gcFileInput = document.getElementById('gc-file-input');         // Updated ID
    gcSendButton = document.getElementById('gc-send-button');       // Updated ID

    gcEditMessageContainer = document.getElementById('gc-edit-message-container'); // Updated ID
    gcEditMessageInput = document.getElementById('gc-edit-message-input');         // Updated ID
    gcSaveEditButton = document.getElementById('gc-save-edit-button');             // Updated ID
    gcCancelEditButton = document.getElementById('gc-cancel-edit-button');         // Updated ID

    if (!gcChatHistoryDiv || !gcChatForm || !gcMessageInput || !gcFileInput || !gcSendButton || !gcEditMessageContainer || !gcEditMessageInput || !gcSaveEditButton || !gcCancelEditButton) {
        console.error("[Group Chat] Initialization failed: Essential elements missing. Check IDs.");
        if (typeof showToast === 'function') showToast("Chat UI Error.", "danger", 10000);
        return;
    }

    currentUserIdGlobal = userId;
    csrfTokenGlobal = csrf;
    historyApiUrlGlobal = historyUrl;
    sendApiUrlGlobal = sendUrl;
    editApiUrlBaseGlobal = editUrlBase;
    deleteApiUrlBaseGlobal = deleteUrlBase;
    isAdminGlobal = isAdminUser; // Use the passed admin status

    if (initialHistory && initialHistory.length > 0) {
        const emptyChatMsg = document.getElementById('gc-empty-chat-msg'); // Updated ID
        if (emptyChatMsg) emptyChatMsg.remove();
        initialHistory.forEach(msg => {
            if (!msg.is_deleted) renderMessage(msg, true);
            if (msg.edited_at && (!clientMaxKnownEditTimestamp || msg.edited_at > clientMaxKnownEditTimestamp)) {
                clientMaxKnownEditTimestamp = msg.edited_at;
            }
            if (msg.id > lastMessageId) lastMessageId = msg.id;
        });
    }

    if (gcMessageInput) {
        resizeTextarea(gcMessageInput);
        gcMessageInput.addEventListener('input', function() { resizeTextarea(this); });
        gcMessageInput.addEventListener('keydown', handleMessageInputKeydown);
    }

    gcChatForm.addEventListener('submit', handleFormSubmit);
    gcSaveEditButton.addEventListener('click', handleSaveEdit);
    gcCancelEditButton.addEventListener('click', handleCancelEdit);
    gcEditMessageInput.addEventListener('keydown', (event) => {
        if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); handleSaveEdit(); } // Allow Shift+Enter for newline in edit
        else if (event.key === 'Escape') { handleCancelEdit(); }
    });

    document.addEventListener('keydown', (event) => {
        if (event.key === 'Shift' && !isShiftHeld) { isShiftHeld = true; toggleMessageActions(true); }
    });
    document.addEventListener('keyup', (event) => {
        if (event.key === 'Shift') { isShiftHeld = false; if (gcEditMessageContainer.style.display === 'none') toggleMessageActions(false); }
    });
    window.addEventListener('blur', () => {
        if (isShiftHeld) { isShiftHeld = false; if (gcEditMessageContainer.style.display === 'none') toggleMessageActions(false); }
    });

    currentPollingInterval = document.hasFocus() ? focusedPollingInterval : blurredPollingInterval;
    window.addEventListener('blur', () => { currentPollingInterval = blurredPollingInterval; startPolling(); });
    window.addEventListener('focus', () => { currentPollingInterval = focusedPollingInterval; startPolling(); fetchNewMessages(); });

    startPolling();
    scrollToBottom();
}

function toggleMessageActions(show) {
    const actionButtons = document.querySelectorAll('.gc-chat-message .gc-message-actions'); // Updated class
    actionButtons.forEach(actions => {
        actions.style.display = show ? 'flex' : 'none';
    });
}

function handleMessageInputKeydown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        if (!gcSendButton.disabled) gcChatForm.requestSubmit(gcSendButton);
    }
    resizeTextarea(event.target);
}

async function handleFormSubmit(event) {
    event.preventDefault();
    if (gcSendButton.disabled) return;

    const content = gcMessageInput.value.trim();
    const file = gcFileInput.files[0];

    if (!content && !file) {
        if (typeof showToast === 'function') showToast('Please type a message or attach a file.', 'warning');
        return;
    }

    gcSendButton.disabled = true;
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
            gcMessageInput.value = '';
            gcFileInput.value = null;
            resizeTextarea(gcMessageInput);
            await fetchNewMessages();
            scrollToBottom();
        } else {
            const errorMsg = data.message || 'Could not send message.';
            if (typeof showToast === 'function') showToast(`Error: ${errorMsg}`, 'danger');
        }
    } catch (error) {
        if (typeof showToast === 'function') showToast('Network error sending message.', 'danger');
    } finally {
        gcSendButton.disabled = false;
    }
}

async function fetchNewMessages() {
    if (!historyApiUrlGlobal) { stopPolling(); return; }
    try {
        let shouldScroll = false;
        if (gcChatHistoryDiv) {
            shouldScroll = gcChatHistoryDiv.scrollTop + gcChatHistoryDiv.clientHeight >= gcChatHistoryDiv.scrollHeight - 50;
        }

        let fetchUrl = `${historyApiUrlGlobal}?last_message_id=${lastMessageId}`;
        if (clientMaxKnownEditTimestamp) {
            fetchUrl += `&last_edit_ts=${encodeURIComponent(clientMaxKnownEditTimestamp)}`;
        }

        const response = await fetch(fetchUrl);
        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                if (typeof showToast === 'function') showToast("Session invalid. Please reload.", "danger", 10000);
                stopPolling();
            }
            return;
        }
        const data = await response.json();

        if (data.status === 'success' && data.messages && data.messages.length > 0) {
            let messageAddedOrUpdatedOrDeleted = false;
            data.messages.forEach(msg => {
                const existingMessageWrapper = gcChatHistoryDiv.querySelector(`.gc-chat-message-wrapper[data-message-id="${msg.id}"]`); // Updated class

                if (existingMessageWrapper) {
                    if (msg.is_deleted) {
                        existingMessageWrapper.remove();
                        messageAddedOrUpdatedOrDeleted = true;
                        if (currentEditingMessageId === msg.id && gcEditMessageContainer.style.display !== 'none') {
                            handleCancelEdit();
                            if (typeof showToast === 'function') showToast('Message was deleted.', 'info');
                        }
                    } else {
                        const existingContentEl = existingMessageWrapper.querySelector('.gc-message-content'); // Updated class
                        const existingEditedMarkerEl = existingMessageWrapper.querySelector('.gc-message-edited-marker'); // Updated class
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
                        }
                        if (updated) {
                            messageAddedOrUpdatedOrDeleted = true;
                            if (currentEditingMessageId === msg.id && gcEditMessageContainer.style.display !== 'none') {
                                handleCancelEdit();
                                if (typeof showToast === 'function') showToast('Message was updated by another source.', 'info');
                            }
                        }
                    }
                } else {
                    if (!msg.is_deleted) {
                        renderMessage(msg);
                        messageAddedOrUpdatedOrDeleted = true;
                    }
                }
                if (msg.id > lastMessageId) lastMessageId = msg.id;
                if (msg.edited_at && (!clientMaxKnownEditTimestamp || msg.edited_at > clientMaxKnownEditTimestamp)) {
                    clientMaxKnownEditTimestamp = msg.edited_at;
                }
            });
            if (messageAddedOrUpdatedOrDeleted && shouldScroll) scrollToBottom();
        }
    } catch (error) {
        console.error('[Group Chat] Error polling or processing messages:', error);
    }
}

function handleEditMessageClick(messageId, currentContent) {
    currentEditingMessageId = messageId;
    gcEditMessageInput.value = currentContent;
    gcEditMessageContainer.style.display = 'flex';
    gcEditMessageInput.focus();
    gcEditMessageInput.select();
    toggleMessageActions(true);
}

async function handleSaveEdit() {
    if (currentEditingMessageId === null) return;
    const newContent = gcEditMessageInput.value.trim();
    if (!newContent) {
        if (typeof showToast === 'function') showToast('Message cannot be empty.', 'warning');
        return;
    }

    gcEditMessageInput.disabled = true;
    gcSaveEditButton.disabled = true;
    gcCancelEditButton.disabled = true;

    try {
        const response = await fetch(`${editApiUrlBaseGlobal}${currentEditingMessageId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfTokenGlobal, 'Accept': 'application/json' },
            body: JSON.stringify({ content: newContent })
        });
        const data = await response.json();

        if (response.ok && data.status === 'success' && data.updated_message) {
            if (typeof showToast === 'function') showToast('Message updated!', 'success', 1500);
            const messageWrapper = gcChatHistoryDiv.querySelector(`.gc-chat-message-wrapper[data-message-id="${currentEditingMessageId}"]`); // Updated class
            if (messageWrapper) {
                const contentElement = messageWrapper.querySelector('.gc-message-content'); // Updated class
                const editedMarker = messageWrapper.querySelector('.gc-message-edited-marker'); // Updated class
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
        if (typeof showToast === 'function') showToast('Network error updating message.', 'danger');
    } finally {
        gcEditMessageInput.disabled = false;
        gcSaveEditButton.disabled = false;
        gcCancelEditButton.disabled = false;
        if (document.activeElement !== gcEditMessageInput && gcEditMessageContainer.style.display !== 'none') {
            gcEditMessageInput.focus();
        }
    }
}

function handleCancelEdit() {
    gcEditMessageContainer.style.display = 'none';
    gcEditMessageInput.value = '';
    currentEditingMessageId = null;
    if (!isShiftHeld) toggleMessageActions(false);
}

async function handleDeleteMessageClick(messageId) {
    if (!confirm('Are you sure you want to delete this message? This cannot be undone.')) return;
    try {
        const response = await fetch(`${deleteApiUrlBaseGlobal}${messageId}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfTokenGlobal, 'Accept': 'application/json' }
        });
        const data = await response.json();
        if (response.ok && data.status === 'success') {
            if (typeof showToast === 'function') showToast('Message deleted!', 'success');
            const messageWrapper = gcChatHistoryDiv.querySelector(`.gc-chat-message-wrapper[data-message-id="${messageId}"]`); // Updated class
            if (messageWrapper) messageWrapper.remove();
            if (currentEditingMessageId === messageId) handleCancelEdit();
        } else {
            const errorMsg = data.message || 'Could not delete message.';
            if (typeof showToast === 'function') showToast(`Error: ${errorMsg}`, 'danger');
        }
    } catch (error) {
        if (typeof showToast === 'function') showToast('Network error deleting message.', 'danger');
    }
}

function startPolling() {
    stopPolling();
    if (currentPollingInterval > 0 && historyApiUrlGlobal) {
        fetchNewMessages().then(() => {
            pollTimerId = setInterval(fetchNewMessages, currentPollingInterval);
        });
    }
}

function stopPolling() {
    if (pollTimerId) {
        clearInterval(pollTimerId);
        pollTimerId = null;
    }
}
