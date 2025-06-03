// static/posts.js

// --- Helper function to make API calls (assuming it's still relevant and correctly defined) ---
async function apiCall(url, method = 'POST', body = null, csrfToken) {
    try {
        const headers = {
            'X-CSRFToken': csrfToken,
            'Accept': 'application/json'
        };
        if (body && !(body instanceof FormData)) {
            headers['Content-Type'] = 'application/json';
        }

        const config = {
            method: method,
            headers: headers,
        };
        if (body) {
            config.body = (body instanceof FormData) ? body : JSON.stringify(body);
        }

        const response = await fetch(url, config);
        const data = await response.json(); // Attempt to parse JSON regardless of response.ok

        if (!response.ok) {
            const errorMessage = data.message || `Error: ${response.status} ${response.statusText}`;
            if (typeof showToast === 'function') {
                showToast(errorMessage, 'danger');
            } else {
                console.error("showToast function not available. API Error:", errorMessage);
            }
            return null; // Return null or a specific error object
        }
        return data;
    } catch (error) {
        console.error('API Call Error:', error);
        const networkErrorMsg = 'Network error or server is unreachable.';
        if (typeof showToast === 'function') {
            showToast(networkErrorMsg, 'danger');
        } else {
            console.error("showToast function not available. ", networkErrorMsg);
        }
        return null; // Return null or a specific error object
    }
}

// Helper to escape HTML (basic version, ensure it's robust enough for your needs)
function escapeHTML(str) {
    if (str === null || str === undefined) return '';
    return String(str).replace(/[&<>"']/g, function (match) {
        return {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        }[match];
    });
}

// Helper to format timestamp (similar to group_chat.js)
function formatCommentTimestamp(isoString) {
    try {
        const date = new Date(isoString);
        if (isNaN(date.getTime())) return 'Invalid Date';
        return date.toLocaleTimeString([], { month:'short', day:'numeric', year:'numeric', hour: '2-digit', minute:'2-digit'});
    } catch (e) {
        return 'Invalid Date';
    }
}


document.addEventListener('DOMContentLoaded', function() {
    const csrfTokenEl = document.querySelector('meta[name="csrf-token"]');
    if (!csrfTokenEl) {
        console.error("CSRF token meta tag not found! Site interactions may fail.");
        if (typeof showToast === 'function') showToast('Critical security error. Please refresh.', 'danger', 10000);
        return; // Stop further execution if CSRF token is missing
    }
    const csrfToken = csrfTokenEl.getAttribute('content');

    // --- Event Delegation for dynamically added content ---
    document.body.addEventListener('click', async function(event) {
        const target = event.target;

        // --- Post Like/Dislike ---
        if (target.matches('.pm-post-action-like, .pm-post-action-like *')) {
            const button = target.closest('.pm-post-action-like');
            if (!button) return;
            const postId = button.dataset.postId;
            if (!postId) return;

            const data = await apiCall(`/social/post/${postId}/like`, 'POST', null, csrfToken);
            if (data) {
                if (typeof showToast === 'function') showToast(data.message || `Post ${data.action}!`, data.status === 'success' ? 'success' : 'info', 1500);
                const postContainer = button.closest('.pm-post-item-container');
                if (postContainer) {
                    const likeCountSpan = postContainer.querySelector('.pm-post-like-count');
                    const dislikeCountSpan = postContainer.querySelector('.pm-post-dislike-count');
                    if (likeCountSpan) likeCountSpan.textContent = data.likes;
                    if (dislikeCountSpan) dislikeCountSpan.textContent = data.dislikes;

                    button.classList.toggle('active', data.action === 'liked');
                    const dislikeButton = postContainer.querySelector('.pm-post-action-dislike');
                    if (dislikeButton) dislikeButton.classList.remove('active');
                }
            }
        } else if (target.matches('.pm-post-action-dislike, .pm-post-action-dislike *')) {
            const button = target.closest('.pm-post-action-dislike');
            if (!button) return;
            const postId = button.dataset.postId;
            if (!postId) return;
            const data = await apiCall(`/social/post/${postId}/dislike`, 'POST', null, csrfToken);
            if (data) {
                if (typeof showToast === 'function') showToast(data.message || `Post ${data.action}!`, data.status === 'success' ? 'success' : 'info', 1500);
                const postContainer = button.closest('.pm-post-item-container');
                if (postContainer) {
                    const likeCountSpan = postContainer.querySelector('.pm-post-like-count');
                    const dislikeCountSpan = postContainer.querySelector('.pm-post-dislike-count');
                    if (likeCountSpan) likeCountSpan.textContent = data.likes;
                    if (dislikeCountSpan) dislikeCountSpan.textContent = data.dislikes;

                    button.classList.toggle('active', data.action === 'disliked');
                    const likeButton = postContainer.querySelector('.pm-post-action-like');
                    if (likeButton) likeButton.classList.remove('active');
                }
            }
        }
        // --- Share Post Button Handler ---
        else if (target.matches('.pm-post-action-share, .pm-post-action-share *')) {
            const button = target.closest('.pm-post-action-share');
            if (!button) return;
            const postIdToShare = button.dataset.postId;
            if (!postIdToShare) return;

            if (!confirm("Are you sure you want to share this post to your profile?")) return;

            const data = await apiCall(`/social/post/${postIdToShare}/share`, 'POST', null, csrfToken);
            if (data) {
                if (typeof showToast === 'function') showToast(data.message || 'Post action completed.', data.status === 'success' ? 'success' : 'info');
                const postContainer = button.closest('.pm-post-item-container');
                if (postContainer) {
                    const shareCountSpan = postContainer.querySelector('.pm-post-share-count');
                    if (shareCountSpan && data.share_count !== undefined) {
                        shareCountSpan.textContent = data.share_count;
                    }
                }
            }
        }
        // --- Toggle Comment Section for Post ---
        else if (target.matches('.pm-post-action-comment-toggle, .pm-post-action-comment-toggle *')) {
            const button = target.closest('.pm-post-action-comment-toggle');
            if (!button) return;
            const postId = button.dataset.postId;
            if (!postId) return;
            const commentsSection = document.getElementById(`comments-section-${postId}`); // ID remains same for now
            if (commentsSection) {
                const isHidden = commentsSection.style.display === 'none' || !commentsSection.style.display;
                commentsSection.style.display = isHidden ? 'block' : 'none';
                if (isHidden) {
                    const commentInput = commentsSection.querySelector('.pm-post-main-comment-form textarea.pm-post-main-comment-input');
                    if (commentInput) commentInput.focus();
                }
            }
        }
        // --- Comment Like Button ---
        else if (target.matches('.pm-comment-action-like, .pm-comment-action-like *')) {
            const button = target.closest('.pm-comment-action-like');
            if (!button) return;
            const commentId = button.dataset.commentId;
            if (!commentId) return;

            const data = await apiCall(`/api/comment/${commentId}/like`, 'POST', null, csrfToken);
            if (data && data.status === 'success') {
                const commentContainer = button.closest('.pm-comment-item');
                if (commentContainer) {
                    const likeCountSpan = commentContainer.querySelector('.pm-comment-like-count');
                    const dislikeCountSpan = commentContainer.querySelector('.pm-comment-dislike-count');
                    if (likeCountSpan) likeCountSpan.textContent = data.likes;
                    if (dislikeCountSpan) dislikeCountSpan.textContent = data.dislikes;

                    button.classList.toggle('active', data.is_liked_by_user);
                    const dislikeButton = commentContainer.querySelector('.pm-comment-action-dislike');
                    if (dislikeButton) dislikeButton.classList.remove('active');
                }
            }
        }
        // --- Comment Dislike Button ---
        else if (target.matches('.pm-comment-action-dislike, .pm-comment-action-dislike *')) {
            const button = target.closest('.pm-comment-action-dislike');
            if (!button) return;
            const commentId = button.dataset.commentId;
            if (!commentId) return;

            const data = await apiCall(`/api/comment/${commentId}/dislike`, 'POST', null, csrfToken);
            if (data && data.status === 'success') {
                const commentContainer = button.closest('.pm-comment-item');
                if (commentContainer) {
                    const likeCountSpan = commentContainer.querySelector('.pm-comment-like-count');
                    const dislikeCountSpan = commentContainer.querySelector('.pm-comment-dislike-count');
                    if (likeCountSpan) likeCountSpan.textContent = data.likes;
                    if (dislikeCountSpan) dislikeCountSpan.textContent = data.dislikes;

                    button.classList.toggle('active', data.is_disliked_by_user);
                    const likeButton = commentContainer.querySelector('.pm-comment-action-like');
                    if (likeButton) likeButton.classList.remove('active');
                }
            }
        }
        // --- Toggle Reply Form for a Comment ---
        else if (target.matches('.pm-comment-action-reply-toggle, .pm-comment-action-reply-toggle *')) {
            const button = target.closest('.pm-comment-action-reply-toggle');
            if (!button) return;
            const commentId = button.dataset.commentId;
            if (!commentId) return;
            const replyFormContainer = document.getElementById(`reply-form-for-comment-${commentId}`); // ID remains same
            if (replyFormContainer) {
                const isHidden = replyFormContainer.style.display === 'none' || !replyFormContainer.style.display;
                replyFormContainer.style.display = isHidden ? 'block' : 'none';
                if (isHidden) {
                    const textarea = replyFormContainer.querySelector('textarea.pm-comment-reply-input');
                    if (textarea) textarea.focus();
                }
            }
        }
        // --- Cancel Reply Button ---
        else if (target.matches('.pm-comment-action-cancel-reply, .pm-comment-action-cancel-reply *')) {
            const button = target.closest('.pm-comment-action-cancel-reply');
            if (!button) return;
            const commentId = button.dataset.commentId;
            if (!commentId) return;
            const replyFormContainer = document.getElementById(`reply-form-for-comment-${commentId}`); // ID remains same
            if (replyFormContainer) {
                replyFormContainer.style.display = 'none';
                const textarea = replyFormContainer.querySelector('textarea.pm-comment-reply-input');
                if (textarea) textarea.value = '';
            }
        }
        // --- Share Comment as Post Button ---
        else if (target.matches('.pm-comment-action-share, .pm-comment-action-share *')) {
            const button = target.closest('.pm-comment-action-share');
            if (!button) return;
            const commentId = button.dataset.commentId;
            if (!commentId) return;

            const modal = document.getElementById('shareCommentAsPostModal'); // Modal ID is specific
            const originalCommentIdInput = document.getElementById('originalCommentIdToShare');
            const commentPreviewArea = document.getElementById('originalCommentPreviewArea');
            const commentText = button.closest('.pm-comment-item')?.querySelector('.pm-comment-text-content')?.textContent || 'Comment text not found.';
            const commentAuthor = button.closest('.pm-comment-item')?.querySelector('.pm-comment-author-username')?.textContent || 'Unknown author';

            if (modal && originalCommentIdInput && commentPreviewArea) {
                originalCommentIdInput.value = commentId;
                commentPreviewArea.innerHTML = `
                <p><strong>${escapeHTML(commentAuthor)}:</strong></p>
                <p>${escapeHTML(commentText)}</p>
                `;
                modal.style.display = 'block'; // Or 'flex' depending on your modal's CSS
                modal.querySelector('textarea[name="text_content"]').focus();
            }
        }
        // --- Close Modal Button (for shareCommentAsPostModal specifically) ---
        else if (target.matches('.close-modal-button, .close-modal-button *') && target.closest('#shareCommentAsPostModal')) {
            const button = target.closest('.close-modal-button');
            if (!button) return;
            const modalId = button.dataset.modalId;
            if (modalId) {
                const modal = document.getElementById(modalId);
                if (modal) modal.style.display = 'none';
            }
        }
        // --- Delete Comment Button ---
        else if (target.matches('.pm-comment-action-delete, .pm-comment-action-delete *')) {
            const button = target.closest('.pm-comment-action-delete');
            if (!button) return;
            const commentId = button.dataset.commentId;
            if (!commentId) return;

            if (confirm('Are you sure you want to delete this comment? This cannot be undone.')) {
                const data = await apiCall(`/api/comment/${commentId}/delete`, 'POST', null, csrfToken);
                if (data && data.status === 'success') {
                    if (typeof showToast === 'function') showToast(data.message || 'Comment deleted.', 'success');
                    const commentElement = document.querySelector(`.pm-comment-item[data-comment-id="${commentId}"]`);
                    if (commentElement) {
                        commentElement.remove();
                    }
                }
            }
        }

    }); // End of body click listener

    // --- Form Submission Handling (Posts and Replies) ---
    document.body.addEventListener('submit', async function(event) {
        const form = event.target;

        // --- Handle New Top-Level Comment on a Post ---
        if (form.matches('.pm-post-main-comment-form')) { // Updated selector
            event.preventDefault();
            const postId = form.dataset.postId;
            const textArea = form.querySelector('textarea.pm-post-main-comment-input'); // Updated selector
            const textContent = textArea.value.trim();

            if (!textContent) {
                if (typeof showToast === 'function') showToast('Comment cannot be empty.', 'warning');
                return;
            }

            const data = await apiCall(`/social/post/${postId}/comment/add`, 'POST', { text_content: textContent }, csrfToken);

            if (data && data.status === 'success' && data.comment) {
                if (typeof showToast === 'function') showToast(data.message || 'Comment posted!', 'success', 2000);
                textArea.value = '';

                const commentsList = document.getElementById(`comments-list-${postId}`); // ID remains same
                const noCommentsMsg = commentsList ? commentsList.querySelector('.pm-post-no-comments-message') : null; // Updated selector
                if (noCommentsMsg) noCommentsMsg.remove();

                if (commentsList) {
                    const newCommentHtml = createCommentHtml(data.comment, postId, false, data.current_user_id, data.current_user_is_admin);
                    commentsList.insertAdjacentHTML('beforeend', newCommentHtml);
                    document.querySelector(`.pm-comment-item[data-comment-id="${data.comment.id}"]`).scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }

                const postContainer = form.closest('.pm-post-item-container'); // Updated selector
                if (postContainer) {
                    const commentCountSpan = postContainer.querySelector('.pm-post-comment-count'); // Updated selector
                    if (commentCountSpan && data.post_comment_count !== undefined) {
                        commentCountSpan.textContent = data.post_comment_count;
                    }
                }
            }
        }
        // --- Handle New Reply to a Comment ---
        else if (form.matches('.pm-comment-reply-form')) { // Updated selector
            event.preventDefault();
            const postId = form.dataset.postId;
            const parentCommentId = form.dataset.parentCommentId;
            const textArea = form.querySelector('textarea.pm-comment-reply-input'); // Updated selector
            const textContent = textArea.value.trim();

            if (!textContent) {
                if (typeof showToast === 'function') showToast('Reply cannot be empty.', 'warning');
                return;
            }

            const payload = {
                text_content: textContent,
                parent_comment_id: parentCommentId
            };
            const data = await apiCall(`/post/${postId}/comment`, 'POST', payload, csrfToken);

            if (data && data.status === 'success' && data.comment) {
                if (typeof showToast === 'function') showToast(data.message || 'Reply posted!', 'success', 2000);
                textArea.value = '';
                form.closest('.pm-comment-reply-form-container').style.display = 'none'; // Updated selector

                const repliesContainer = document.getElementById(`replies-to-comment-${parentCommentId}`); // ID remains same
                if (repliesContainer) {
                    const newReplyHtml = createCommentHtml(data.comment, postId, true, data.current_user_id, data.current_user_is_admin);
                    repliesContainer.insertAdjacentHTML('beforeend', newReplyHtml);
                    document.querySelector(`.pm-comment-item[data-comment-id="${data.comment.id}"]`).scrollIntoView({ behavior: 'smooth', block: 'nearest' });
                }
                const postContainer = form.closest('.pm-post-item-container'); // Updated selector
                if (postContainer) {
                    const commentCountSpan = postContainer.querySelector('.pm-post-comment-count'); // Updated selector
                    if (commentCountSpan && data.post_comment_count !== undefined) {
                        commentCountSpan.textContent = data.post_comment_count;
                    }
                }
            }
        }
        // --- Handle Share Comment as Post Modal Form ---
        else if (form.matches('#shareCommentAsPostForm')) { // ID remains same
            event.preventDefault();
            const originalCommentId = form.querySelector('#originalCommentIdToShare').value;
            const sharerTextContent = form.querySelector('#sharerTextContent').value.trim();

            if (!originalCommentId) {
                if (typeof showToast === 'function') showToast('Error: Original comment ID missing.', 'danger');
                return;
            }

            const payload = { text_content: sharerTextContent };
            const data = await apiCall(`/api/comment/${originalCommentId}/share`, 'POST', payload, csrfToken);

            if (data && data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || 'Comment shared as a new post!', 'success');
                document.getElementById('shareCommentAsPostModal').style.display = 'none';
                form.reset();
            }
        }
    }); // End of body submit listener


    // --- Function to create HTML for a comment or reply ---
    function createCommentHtml(commentData, postId, isReply = false, currentUserId, currentUserIsAdmin) {
        let pfpUrl = '/static/icons/default-pfp.svg';
        if (commentData.author_profile_pic) {
            pfpUrl = `/static/uploads/profile_pics/${escapeHTML(commentData.author_profile_pic)}`;
        }

        // Determine if the menu should be shown for this comment
        const showMenu = (commentData.user_id === currentUserId || currentUserIsAdmin) && !commentData.is_embedded_in_shared_post; // Added !is_embedded_in_shared_post

        let menuHtml = '';
        if (showMenu) {
            menuHtml = `
            <div class="pm-comment-actions-menu">
                <button class="unified-icon-button small pm-comment-menu-toggle-button" aria-label="Comment actions" onclick="toggleCommentMenu(this)">
                    <img src="/static/icons/hamburger-menu.svg" alt="Menu">
                </button>
                <div class="pm-comment-menu-dropdown" style="display:none;">
                    <button class="unified-action-button small danger pm-comment-action-delete pm-comment-menu-item" data-comment-id="${commentData.id}" title="Delete Comment">
                        <img src="/static/icons/trash.svg" alt="Delete"> Delete
                    </button>
                    </div>
            </div>
            `;
        }

        const isLikedByCurrentUser = commentData.likers && commentData.likers.some(u => u.id === currentUserId);
        const isDislikedByCurrentUser = commentData.dislikers && commentData.dislikers.some(u => u.id === currentUserId);
        const likeCount = commentData.like_count !== undefined ? commentData.like_count : (commentData.likers ? commentData.likers.length : 0);
        const dislikeCount = commentData.dislike_count !== undefined ? commentData.dislike_count : (commentData.dislikers ? commentData.dislikers.length : 0);


        return `
        <div class="pm-comment-item ${isReply ? 'pm-comment-item--reply' : ''}" data-comment-id="${commentData.id}" data-post-id="${postId}">
            <div class="pm-comment-author-info">
                <img src="${pfpUrl}" alt="${escapeHTML(commentData.author_username)}" class="pm-comment-author-pfp">
                <div class="pm-comment-author-details">
                    <a href="/user/${escapeHTML(commentData.author_username)}" class="pm-comment-author-username">${escapeHTML(commentData.author_username)}</a>
                    <small class="pm-comment-timestamp" title="${escapeHTML(commentData.timestamp)}">${formatCommentTimestamp(commentData.timestamp)}</small>
                </div>
                ${menuHtml}
            </div>
            <p class="pm-comment-text-content">${escapeHTML(commentData.text_content)}</p>
            <div class="pm-comment-actions-bar">
                <button class="unified-action-button small pm-comment-action-like ${isLikedByCurrentUser ? 'active' : ''}" data-comment-id="${commentData.id}" title="Like">
                    <img src="/static/icons/thumbs-up.svg" alt="Like">
                    <span class="pm-comment-like-count">${likeCount}</span>
                </button>
                <button class="unified-action-button small pm-comment-action-dislike ${isDislikedByCurrentUser ? 'active' : ''}" data-comment-id="${commentData.id}" title="Dislike">
                    <img src="/static/icons/thumbs-down.svg" alt="Dislike">
                    <span class="pm-comment-dislike-count">${dislikeCount}</span>
                </button>
                <button class="unified-action-button small pm-comment-action-reply-toggle" data-comment-id="${commentData.id}" title="Reply">
                    <img src="/static/icons/message-circle.svg" alt="Reply">
                </button>
                <button class="unified-action-button small pm-comment-action-share" data-comment-id="${commentData.id}" title="Share Comment as Post">
                    <img src="/static/icons/share.svg" alt="Share">
                </button>
            </div>
            <div class="pm-comment-reply-form-container" id="reply-form-for-comment-${commentData.id}" style="display:none; margin-top: 8px;">
                <form class="pm-comment-reply-form" data-post-id="${postId}" data-parent-comment-id="${commentData.id}">
                    <textarea name="text_content" class="form-control pm-comment-reply-input" placeholder="Write a reply..." rows="2"></textarea>
                    <div style="text-align: right; margin-top: 5px;">
                        <button type="button" class="unified-action-button small pm-comment-action-cancel-reply" data-comment-id="${commentData.id}">Cancel</button>
                        <button type="submit" class="unified-action-button small primary">Post Reply</button>
                    </div>
                </form>
            </div>
            <div class="pm-comment-replies-list-container" id="replies-to-comment-${commentData.id}">
                ${(commentData.replies && commentData.replies.length > 0) ?
                    commentData.replies.map(reply => createCommentHtml(reply, postId, true, currentUserId, currentUserIsAdmin)).join('') :
                    ''
                }
            </div>
        </div>
        `;
    }


    // --- Close menus if clicking outside ---
    document.addEventListener('click', function(event) {
        // Post menus
        const openPostMenus = document.querySelectorAll('.pm-post-menu-dropdown');
        let clickedInsidePostMenuOrToggle = false;
        openPostMenus.forEach(menu => {
            if (menu.style.display === 'block') {
                const toggleButton = menu.previousElementSibling;
                if ((toggleButton && toggleButton.contains(event.target)) || menu.contains(event.target)) {
                    clickedInsidePostMenuOrToggle = true;
                }
            }
        });
        if (!clickedInsidePostMenuOrToggle) {
            openPostMenus.forEach(menu => menu.style.display = 'none');
        }

        // Comment menus
        const openCommentMenus = document.querySelectorAll('.pm-comment-menu-dropdown');
        let clickedInsideCommentMenuOrToggle = false;
        openCommentMenus.forEach(menu => {
            if (menu.style.display === 'block') {
                const toggleButton = menu.previousElementSibling; // Assuming toggle button is directly before dropdown
                if ((toggleButton && toggleButton.contains(event.target)) || menu.contains(event.target)) {
                    clickedInsideCommentMenuOrToggle = true;
                }
            }
        });
        if (!clickedInsideCommentMenuOrToggle && !event.target.closest('.pm-comment-menu-toggle-button')) { //Also check if the click was on a toggle itself
            openCommentMenus.forEach(menu => menu.style.display = 'none');
        }


        // Share modal (remains the same)
        const shareModal = document.getElementById('shareCommentAsPostModal');
        if (shareModal && shareModal.style.display === 'block' && shareModal.contains(event.target) && !event.target.closest('.modal-content')) {
            // Clicked on backdrop of share modal
        } else if (shareModal && shareModal.style.display === 'block' && !shareModal.contains(event.target) && !event.target.closest('.pm-comment-action-share')) {
            // Clicked outside share modal and not on a share button
        }
        // More precise closing for share modal is handled by its own close buttons/logic if needed
    });

}); // End DOMContentLoaded


// Make togglePostMenu global
function togglePostMenu(buttonElement) {
    const dropdown = buttonElement.nextElementSibling;
    if (dropdown && dropdown.classList.contains('pm-post-menu-dropdown')) { // Updated selector
        const isVisible = dropdown.style.display === 'block';
        document.querySelectorAll('.pm-post-menu-dropdown').forEach(menu => { // Updated selector
            if (menu !== dropdown) {
                menu.style.display = 'none';
            }
        });
        dropdown.style.display = isVisible ? 'none' : 'block';
    }
}

function toggleCommentMenu(buttonElement) {
    const dropdown = buttonElement.nextElementSibling; // Assumes dropdown is the next sibling
    if (dropdown && dropdown.classList.contains('pm-comment-menu-dropdown')) {
        const isVisible = dropdown.style.display === 'block';
        // Close all OTHER comment menus
        document.querySelectorAll('.pm-comment-menu-dropdown').forEach(menu => {
            if (menu !== dropdown) menu.style.display = 'none';
        });
            // Close all post menus
            document.querySelectorAll('.pm-post-menu-dropdown').forEach(menu => menu.style.display = 'none');
            dropdown.style.display = isVisible ? 'none' : 'block';
    }
}
