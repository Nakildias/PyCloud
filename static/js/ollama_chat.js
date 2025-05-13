// static/js/ollama_chat.js
document.addEventListener('DOMContentLoaded', function() {
    // --- Element References (Updated with oc- prefixes) ---
    const ocChatHistoryDiv = document.getElementById('oc-chat-history');         // Updated ID
    const ocMessageTextarea = document.getElementById('oc-message-textarea');    // Updated ID
    const ocChatForm = document.getElementById('oc-chat-form');                  // Updated ID
    const ocSendButton = document.getElementById('oc-send-button');              // Updated ID
    const ocClearHistoryButton = document.getElementById('oc-clear-history-button'); // Updated ID

    const csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute('content') : null;

    // Get URLs from the global config object set in the HTML template
    const API_OLLAMA_CHAT_SEND_URL = window.ollamaChatConfig ? window.ollamaChatConfig.apiSendUrl : null;
    const CLEAR_OLLAMA_CHAT_HISTORY_URL = window.ollamaChatConfig ? window.ollamaChatConfig.clearHistoryUrl : null;

    if (!ocChatHistoryDiv || !ocMessageTextarea || !ocChatForm || !ocSendButton || !ocClearHistoryButton) { // Added ocClearHistoryButton check
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
            if (ocChatHistoryDiv) { // Updated variable
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

    function addMessageToHistory(role, content, timestampStr, elementId = null) {
        if (!ocChatHistoryDiv) { // Updated variable
            console.error("addMessageToHistory: ocChatHistoryDiv not found!");
            return null;
        }
        const emptyHistoryMsg = document.getElementById('oc-empty-history-msg'); // Updated ID
        if (emptyHistoryMsg && emptyHistoryMsg.parentNode === ocChatHistoryDiv) { // Updated variable
            ocChatHistoryDiv.removeChild(emptyHistoryMsg); // Updated variable
        }

        const messageDiv = document.createElement('div');
        // Use new base class and dynamic role class
        messageDiv.classList.add('oc-message', `oc-message-role-${role}`);
        if (elementId) {
            messageDiv.id = elementId;
        }

        const headerDiv = document.createElement('div');
        headerDiv.classList.add('oc-message-header'); // Updated class

        const roleStrong = document.createElement('strong');
        roleStrong.classList.add('oc-message-sender'); // Updated class
        roleStrong.textContent = (role === 'thinking') ? 'System' : (role.charAt(0).toUpperCase() + role.slice(1));
        headerDiv.appendChild(roleStrong);

        if (timestampStr) {
            const timestampSpan = document.createElement('span');
            timestampSpan.classList.add('oc-message-timestamp'); // Updated class
            timestampSpan.textContent = formatTimestamp(timestampStr);
            headerDiv.appendChild(timestampSpan);
        }
        messageDiv.appendChild(headerDiv);

        const contentDiv = document.createElement('div');
        contentDiv.classList.add('oc-message-content'); // Updated class
        contentDiv.textContent = content;
        messageDiv.appendChild(contentDiv);

        ocChatHistoryDiv.appendChild(messageDiv); // Updated variable
        scrollOllamaChatToBottom();
        return messageDiv;
    }

    async function handleFormSubmit(event) {
        event.preventDefault();
        if (!csrfToken) {
            addMessageToHistory('error', 'Security token missing.', new Date().toISOString()); return;
        }
        const userMessage = ocMessageTextarea.value.trim(); // Updated variable
        if (!userMessage) { return; }

        ocMessageTextarea.disabled = true; // Updated variable
        ocSendButton.disabled = true;      // Updated variable
        ocMessageTextarea.value = '';      // Updated variable
        resizeTextarea(ocMessageTextarea); // Updated variable

        addMessageToHistory('user', userMessage, new Date().toISOString());
        const thinkingIndicatorId = `oc-thinking-${Date.now()}`; // Prefixed ID
        addMessageToHistory('thinking', 'Ollama is thinking...', new Date().toISOString(), thinkingIndicatorId);

        try {
            const response = await fetch(API_OLLAMA_CHAT_SEND_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken },
                body: JSON.stringify({ message: userMessage })
            });
            const data = await response.json();

            const indicatorToRemove = document.getElementById(thinkingIndicatorId);
            if (indicatorToRemove) {
                indicatorToRemove.remove();
            }

            if (response.ok && data.status === 'success') {
                addMessageToHistory('assistant', data.ai_message, new Date().toISOString());
            } else {
                addMessageToHistory('error', data.message || 'Unknown error occurred.', new Date().toISOString());
            }
            scrollOllamaChatToBottom();

        } catch (error) {
            console.error("Fetch error:", error);
            const indicatorToRemove = document.getElementById(thinkingIndicatorId);
            if (indicatorToRemove) indicatorToRemove.remove();
            const errorMsg = `Network or connection error: ${error.message}`;
            addMessageToHistory('error', errorMsg, new Date().toISOString());
            scrollOllamaChatToBottom();
        } finally {
            ocMessageTextarea.disabled = false; // Updated variable
            ocSendButton.disabled = false;      // Updated variable
            ocMessageTextarea.focus();          // Updated variable
        }
    }

    // --- Initialize Textarea & Attach Listeners ---
    resizeTextarea(ocMessageTextarea); // Updated variable
    ocMessageTextarea.addEventListener('input', function() { resizeTextarea(this); }); // Updated variable
    ocMessageTextarea.addEventListener('keydown', function(event) { // Updated variable
        if (event.key === 'Enter' && !event.shiftKey) {
            event.preventDefault();
            if (!ocSendButton.disabled) ocChatForm.requestSubmit(ocSendButton); // Updated variables
        }
        resizeTextarea(this);
    });
    ocChatForm.addEventListener('submit', handleFormSubmit); // Updated variable

    ocClearHistoryButton.addEventListener('click', function() { // Updated variable
        if (confirm('Are you sure you want to clear the entire Ollama chat history? This cannot be undone.')) {
            window.location.href = CLEAR_OLLAMA_CHAT_HISTORY_URL;
        }
    });

    // --- Format initial timestamps ---
    document.querySelectorAll('#oc-chat-history .oc-message-timestamp').forEach(span => { // Updated ID and class
        const isoString = span.dataset.timestamp;
        if (isoString) {
            span.textContent = formatTimestamp(isoString);
        }
    });

    scrollOllamaChatToBottom();
});
