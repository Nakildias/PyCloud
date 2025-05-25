// static/js/ollama_chat.js
document.addEventListener('DOMContentLoaded', function() {
    // --- Element References ---
    const ocChatHistoryDiv = document.getElementById('oc-chat-history');
    const ocMessageTextarea = document.getElementById('oc-message-textarea');
    const ocChatForm = document.getElementById('oc-chat-form');
    const ocSendButton = document.getElementById('oc-send-button');
    const ocClearHistoryButton = document.getElementById('oc-clear-history-button');

    const csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute('content') : null;

    // Get URLs and user info from the global config object set in the HTML template
    const API_OLLAMA_CHAT_SEND_URL = window.ollamaChatConfig ? window.ollamaChatConfig.apiSendUrl : null;
    const CLEAR_OLLAMA_CHAT_HISTORY_URL = window.ollamaChatConfig ? window.ollamaChatConfig.clearHistoryUrl : null;
    const CURRENT_USER_ID = window.ollamaChatConfig ? window.ollamaChatConfig.currentUserId : null;
    const CURRENT_USERNAME = window.ollamaChatConfig ? window.ollamaChatConfig.currentUsername : 'User';
    const CURRENT_USER_PFP_FILENAME = window.ollamaChatConfig ? window.ollamaChatConfig.currentUserPfpFilename : '';
    const OLLAMA_PFP_URL = '/static/icons/ollama_pfp.png'; // Path to Ollama PFP
    const DEFAULT_USER_PFP_URL = '/static/icons/default-pfp.svg'; // Path to default user PFP

    // --- Basic UI Checks ---
    if (!ocChatHistoryDiv || !ocMessageTextarea || !ocChatForm || !ocSendButton || !ocClearHistoryButton) {
        console.error("Ollama Chat Error: Could not find essential chat elements. Check IDs.");
        if (typeof showToast === 'function') {
            showToast("Error initializing Ollama chat UI.", "danger", 10000);
        }
        return;
    }
    if (!API_OLLAMA_CHAT_SEND_URL || !CLEAR_OLLAMA_CHAT_HISTORY_URL) {
        console.error("Ollama Chat Error: API URLs not configured in window.ollamaChatConfig.");
        if (typeof showToast === 'function') {
            showToast("Ollama chat configuration error.", "danger", 10000);
        }
        return;
    }

    // --- Helper Functions ---
    function scrollOllamaChatToBottom() {
        setTimeout(() => {
            if (ocChatHistoryDiv) {
                ocChatHistoryDiv.scrollTop = ocChatHistoryDiv.scrollHeight;
            }
        }, 1);
    }

    function resizeTextarea(textarea) {
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
                console.warn("[Ollama Chat] Invalid timestamp received:", isoString);
                return 'Invalid Date';
            }
            return date.toLocaleString([], { year: 'numeric', month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true });
        } catch (e) {
            console.error("[Ollama Chat] Error formatting timestamp:", isoString, e);
            return 'Invalid Date';
        }
    }

    /**
     * Renders a single message into the chat history.
     * This function mirrors group_chat.js's renderMessage for consistency.
     * @param {object} message - The message object to render. Expected properties:
     * - id: Unique message ID (can be temporary for client-side)
     * - role: 'user', 'assistant', 'thinking'
     * - content: The message text (for 'thinking' role, this will be handled by HTML directly)
     * - timestamp: ISO string of when the message was sent
     * - user_id (for 'user' role): ID of the sending user
     * - sender_username (for 'user' role): Username of the sender
     * - sender_profile_picture_filename (for 'user' role): Filename of the sender's PFP
     */
    function renderOllamaMessage(message) {
        if (!ocChatHistoryDiv) {
            console.error("renderOllamaMessage: ocChatHistoryDiv not found!");
            return null;
        }

        const emptyHistoryMsg = document.getElementById('oc-empty-chat-msg');
        if (emptyHistoryMsg && ocChatHistoryDiv.contains(emptyHistoryMsg)) {
            ocChatHistoryDiv.removeChild(emptyHistoryMsg);
        }

        const messageWrapper = document.createElement('div');
        messageWrapper.classList.add('gc-chat-message-wrapper');
        messageWrapper.dataset.messageId = message.id || `temp-${Date.now()}`; // Use a temp ID for new messages

        // Determine if it's the current user's message or a thinking message
        if (message.role === 'user') {
            messageWrapper.classList.add('current-user');
        } else if (message.role === 'thinking') {
            messageWrapper.classList.add('thinking'); // Add a class for specific thinking message styling
        }

        const pfpDiv = document.createElement('div');
        pfpDiv.classList.add('gc-chat-message-pfp-container');

        const pfpImg = document.createElement('img');
        pfpImg.classList.add('gc-chat-message-pfp');

        // Set PFP source and alt text based on message role
        if (message.role === 'user') {
            // For user messages, construct path from filename or use default
            pfpImg.src = message.sender_profile_picture_filename ? `/static/uploads/profile_pics/${message.sender_profile_picture_filename}` : DEFAULT_USER_PFP_URL;
            pfpImg.alt = `${message.sender_username || 'User'}'s profile picture`;
        } else { // For 'assistant', 'thinking', or 'error' roles (Ollama AI / System)
            pfpImg.src = OLLAMA_PFP_URL;
            pfpImg.alt = 'Ollama AI';
        }
        pfpDiv.appendChild(pfpImg);

        const messageDiv = document.createElement('div');
        messageDiv.classList.add('gc-chat-message');
        messageDiv.style.position = 'relative'; // Essential for proper action button positioning

        const headerDiv = document.createElement('div');
        headerDiv.classList.add('gc-message-header');

        // Set sender name and potentially create a link, matching group_chat.js exactly
        if (message.role === 'user') {
            const senderLink = document.createElement('a');
            senderLink.href = `/user/${message.sender_username || 'unknown'}`; // Link to user profile
            senderLink.classList.add('gc-message-sender');
            senderLink.textContent = message.sender_username || `User`;
            headerDiv.appendChild(senderLink); // Directly append <a> to headerDiv
        } else if (message.role === 'assistant' || message.role === 'thinking' || message.role === 'error') {
            const senderStrong = document.createElement('strong');
            senderStrong.classList.add('gc-message-sender');
            senderStrong.textContent = 'Ollama'; // Always "Ollama" for AI/system messages in Ollama chat
            headerDiv.appendChild(senderStrong);
        } else { // Fallback for any other unexpected roles
            const senderStrong = document.createElement('strong');
            senderStrong.classList.add('gc-message-sender');
            senderStrong.textContent = 'System:';
            headerDiv.appendChild(senderStrong);
        }

        if (message.timestamp) {
            const timestampSpan = document.createElement('span');
            timestampSpan.classList.add('gc-message-timestamp');
            timestampSpan.textContent = formatTimestamp(message.timestamp);
            headerDiv.appendChild(timestampSpan);
        }
        messageDiv.appendChild(headerDiv);

        const contentDiv = document.createElement('div'); // Use a div for content
        contentDiv.classList.add('gc-message-content');

        if (message.role === 'thinking') {
            // For thinking messages, insert the animated dots HTML
            contentDiv.innerHTML = `<span> </span><span class="dot-pulse"></span>`;
        } else {
            // For all other messages, use the plain text content
            contentDiv.textContent = message.content;
        }
        messageDiv.appendChild(contentDiv);

        // Append PFP and message div based on sender role (determines left/right alignment)
        // This mirrors group_chat.js's conditional appending of pfpDiv
        if (message.role !== 'user') { // PFP on left for AI/System
            messageWrapper.appendChild(pfpDiv);
        }
        messageWrapper.appendChild(messageDiv);
        if (message.role === 'user') { // PFP on right for current user
            messageWrapper.appendChild(pfpDiv);
        }

        ocChatHistoryDiv.appendChild(messageWrapper);
        scrollOllamaChatToBottom(); // Always scroll to bottom for new messages
        return messageWrapper;
    }


    async function handleFormSubmit(event) {
        event.preventDefault();
        if (!csrfToken) {
            renderOllamaMessage({ role: 'error', content: 'Security token missing.', timestamp: new Date().toISOString(), sender_username: 'System' });
            return;
        }
        const userMessageContent = ocMessageTextarea.value.trim();
        if (!userMessageContent) { return; }

        ocMessageTextarea.disabled = true;
        ocSendButton.disabled = true;
        ocMessageTextarea.value = '';
        resizeTextarea(ocMessageTextarea);

        // Prepare message object for immediate display of user's message
        const userMessage = {
            id: `temp-user-${Date.now()}`, // Temporary ID for client-side rendering
                          role: 'user',
                          content: userMessageContent,
                          timestamp: new Date().toISOString(),
                          user_id: CURRENT_USER_ID, // Use current user's ID
                          sender_username: CURRENT_USERNAME, // Use current user's username
                          sender_profile_picture_filename: CURRENT_USER_PFP_FILENAME // Use current user's PFP filename
        };
        renderOllamaMessage(userMessage);

        // Prepare message object for thinking indicator
        // The content will be ignored by renderOllamaMessage when role is 'thinking'
        const thinkingMessage = {
            id: `temp-thinking-${Date.now()}`,
                          role: 'thinking',
                          content: 'Ollama is thinking...', // This content is now ignored by renderOllamaMessage for 'thinking' role
                          timestamp: new Date().toISOString(),
                          // For thinking, use Ollama's sender info for consistency
                          sender_username: 'System',
                          sender_profile_picture_filename: 'ollama_pfp.png'
        };
        renderOllamaMessage(thinkingMessage);


        try {
            const response = await fetch(API_OLLAMA_CHAT_SEND_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken },
                body: JSON.stringify({ message: userMessageContent })
            });
            const data = await response.json();

            // Remove thinking indicator
            const thinkingIndicator = document.querySelector(`[data-message-id="${thinkingMessage.id}"]`);
            if (thinkingIndicator) thinkingIndicator.remove();

            if (response.ok && data.status === 'success') {
                // Render AI response. 'data.ai_message' is already the full message object from the backend
                // so we pass it directly to renderOllamaMessage.
                renderOllamaMessage(data.ai_message); // Corrected: pass the entire message object
            } else {
                renderOllamaMessage({
                    id: `error-${Date.now()}`,
                                    role: 'error',
                                    content: data.message || 'Unknown error occurred.',
                                    timestamp: new Date().toISOString(),
                                    sender_username: 'System',
                                    sender_profile_picture_filename: 'ollama_pfp.png' // Use Ollama PFP for errors too
                });
            }
            scrollOllamaChatToBottom();

        } catch (error) {
            console.error("Fetch error:", error);
            const thinkingIndicator = document.querySelector(`[data-message-id="${thinkingMessage.id}"]`);
            if (thinkingIndicator) thinkingIndicator.remove();
            const errorMsg = `Network or connection error: ${error.message}`;
            renderOllamaMessage({
                id: `error-${Date.now()}`,
                                role: 'error',
                                content: errorMsg,
                                timestamp: new Date().toISOString(),
                                sender_username: 'System',
                                sender_profile_picture_filename: 'ollama_pfp.png' // Use Ollama PFP for errors too
            });
            scrollOllamaChatToBottom();
        } finally {
            ocMessageTextarea.disabled = false;
            ocSendButton.disabled = false;
            ocMessageTextarea.focus();
        }
    }

    // --- Initialize Textarea & Attach Listeners ---
    resizeTextarea(ocMessageTextarea);
    ocMessageTextarea.addEventListener('input', function() { resizeTextarea(this); });
    ocMessageTextarea.addEventListener('keydown', function(event) {
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            if (!ocSendButton.disabled) ocChatForm.requestSubmit(ocSendButton);
        }
    });
    ocChatForm.addEventListener('submit', handleFormSubmit);

    ocClearHistoryButton.addEventListener('click', function() {
        if (confirm('Are you sure you want to clear the entire Ollama chat history? This cannot be undone.')) {
            window.location.href = CLEAR_OLLAMA_CHAT_HISTORY_URL;
        }
    });

    // --- Format initial timestamps for existing messages ---
    document.querySelectorAll('#oc-chat-history .gc-message-timestamp').forEach(span => {
        const isoString = span.dataset.timestamp;
        if (isoString) {
            span.textContent = formatTimestamp(isoString);
        }
    });

    scrollOllamaChatToBottom();
});
