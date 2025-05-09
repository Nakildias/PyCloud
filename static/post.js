// static/posts.js

// --- Make togglePostMenu a global function ---
function togglePostMenu(buttonElement) {
    const dropdown = buttonElement.nextElementSibling;
    if (dropdown && dropdown.classList.contains('post-menu-dropdown')) {
        const isVisible = dropdown.style.display === 'block';
        // Close all other post menus first
        document.querySelectorAll('.post-menu-dropdown').forEach(menu => {
            if (menu !== dropdown) {
                menu.style.display = 'none';
            }
        });
        dropdown.style.display = isVisible ? 'none' : 'block';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');

    // --- Helper function to make API calls ---
    async function apiCall(url, method = 'POST', body = null) {
        try {
            const headers = {
                'X-CSRFToken': csrfToken,
                'Accept': 'application/json'
            };
            if (body && !(body instanceof FormData)) { // Don't set Content-Type for FormData
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
            const data = await response.json();

            if (!response.ok) {
                // Assuming showToast is globally available or defined elsewhere in this file if not global
                if (typeof showToast === 'function') {
                    showToast(data.message || `Error: ${response.status}`, 'danger');
                } else {
                    console.error("showToast function not available. API Error:", data.message || `Error: ${response.status}`);
                }
                return null;
            }
            return data;
        } catch (error) {
            console.error('API Call Error:', error);
            if (typeof showToast === 'function') {
                showToast('Network error or server is unreachable.', 'danger');
            } else {
                console.error("showToast function not available. Network error or server is unreachable.");
            }
            return null;
        }
    }

    // --- Like Button Handler ---
    document.querySelectorAll('.btn-like').forEach(button => {
        button.addEventListener('click', async function() {
            const postId = this.dataset.postId;
            const data = await apiCall(`/post/${postId}/like`);
            if (data) {
                if (typeof showToast === 'function') showToast(data.message || `Post ${data.action}!`, data.status === 'success' ? 'success' : 'info', 1500);
                const likeCountSpan = this.closest('.post-container').querySelector('.like-count');
                const dislikeCountSpan = this.closest('.post-container').querySelector('.dislike-count');
                if (likeCountSpan) likeCountSpan.textContent = data.likes;
                if (dislikeCountSpan) dislikeCountSpan.textContent = data.dislikes;

                this.classList.toggle('active', data.action === 'liked');
                const dislikeButton = this.closest('.post-actions').querySelector('.btn-dislike');
                if (dislikeButton) dislikeButton.classList.remove('active');
            }
        });
    });

    // --- Dislike Button Handler ---
    document.querySelectorAll('.btn-dislike').forEach(button => {
        button.addEventListener('click', async function() {
            const postId = this.dataset.postId;
            const data = await apiCall(`/post/${postId}/dislike`);
            if (data) {
                if (typeof showToast === 'function') showToast(data.message || `Post ${data.action}!`, data.status === 'success' ? 'success' : 'info', 1500);
                const likeCountSpan = this.closest('.post-container').querySelector('.like-count');
                const dislikeCountSpan = this.closest('.post-container').querySelector('.dislike-count');
                if (likeCountSpan) likeCountSpan.textContent = data.likes;
                if (dislikeCountSpan) dislikeCountSpan.textContent = data.dislikes;

                this.classList.toggle('active', data.action === 'disliked');
                const likeButton = this.closest('.post-actions').querySelector('.btn-like');
                if (likeButton) likeButton.classList.remove('active');
            }
        });
    });

    // --- Comment Toggle ---
    document.querySelectorAll('.btn-comment-toggle').forEach(button => {
        button.addEventListener('click', function() {
            const postId = this.dataset.postId;
            const commentsSection = document.getElementById(`comments-section-${postId}`);
            if (commentsSection) {
                commentsSection.style.display = commentsSection.style.display === 'none' ? 'block' : 'none';
                if (commentsSection.style.display === 'block') {
                    const commentInput = commentsSection.querySelector('.comment-input');
                    if (commentInput) commentInput.focus();
                }
            }
        });
    });

    // --- Comment Form Submission ---
    document.querySelectorAll('.comment-form').forEach(form => {
        form.addEventListener('submit', async function(event) {
            event.preventDefault();
            const postId = this.dataset.postId;
            const textArea = this.querySelector('textarea[name="text_content"]');
            const textContent = textArea.value.trim();

            if (!textContent) {
                if (typeof showToast === 'function') showToast('Comment cannot be empty.', 'warning');
                              return;
            }

            const data = await apiCall(`/post/${postId}/comment`, 'POST', { text_content: textContent });

            if (data && data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || 'Comment posted!', 'success', 2000);
                              textArea.value = ''; // Clear textarea

                              const commentsList = document.getElementById(`comments-list-${postId}`);
                const noCommentsMsg = commentsList.querySelector('.no-comments-yet');
                if (noCommentsMsg) noCommentsMsg.remove();

                              const newCommentDiv = document.createElement('div');
                newCommentDiv.classList.add('comment');
                newCommentDiv.dataset.commentId = data.comment.id;
                let pfpUrl = '/static/icons/default-pfp.png';
                if(data.comment.author_profile_pic) {
                    pfpUrl = `/static/uploads/profile_pics/${data.comment.author_profile_pic}`;
                }

                newCommentDiv.innerHTML = `
                <div class="comment-author-info">
                <img src="${pfpUrl}" alt="${data.comment.author_username}" class="comment-author-pfp">
                <a href="/user/${data.comment.author_username}" class="comment-author-username">${data.comment.author_username}</a>
                </div>
                <p class="comment-text">${escapeHTML(data.comment.text_content)}</p>
                <small class="comment-timestamp" title="${new Date(data.comment.timestamp).toLocaleString()} UTC">${new Date(data.comment.timestamp).toLocaleTimeString([], { month:'short', day:'numeric', year:'numeric', hour: '2-digit', minute:'2-digit'})}</small>
                `;
                commentsList.appendChild(newCommentDiv);

                const commentCountSpan = this.closest('.post-container').querySelector('.comment-count');
                if (commentCountSpan && data.comment_count !== undefined) {
                    commentCountSpan.textContent = data.comment_count;
                }
                newCommentDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });

            } else if (data) {
                if (typeof showToast === 'function') showToast(data.message || 'Could not post comment.', 'danger');
            }
        });
    });

    // --- Share Button Handler ---
    document.querySelectorAll('.btn-share').forEach(button => {
        button.addEventListener('click', async function() {
            const postIdToShare = this.dataset.postId;
            if (!confirm("Are you sure you want to share this post to your profile?")) {
                return;
            }
            const data = await apiCall(`/post/${postIdToShare}/share`);
            if (data) {
                if (typeof showToast === 'function') showToast(data.message || 'Post action completed.', data.status === 'success' ? 'success' : 'info');
                const shareCountSpan = this.closest('.post-container').querySelector('.share-count');
                if (shareCountSpan && data.share_count !== undefined) {
                    shareCountSpan.textContent = data.share_count;
                }
            }
        });
    });

    // --- Close menu if clicking outside (This listener should be inside DOMContentLoaded) ---
    document.addEventListener('click', function(event) {
        const openMenus = document.querySelectorAll('.post-menu-dropdown');
        let clickedInsideMenuOrToggle = false; // Changed variable name for clarity

        openMenus.forEach(menu => {
            if (menu.style.display === 'block') {
                const toggleButton = menu.previousElementSibling; // Assuming toggle is always previous sibling
                // Check if click is on the toggle button OR inside the open menu
                if ((toggleButton && toggleButton.contains(event.target)) || menu.contains(event.target)) {
                    clickedInsideMenuOrToggle = true;
                }
            }
        });

        // If the click was not inside an open menu or its toggle, close all open menus
        if (!clickedInsideMenuOrToggle) {
            openMenus.forEach(menu => {
                menu.style.display = 'none';
            });
        }
        // Removed 'true' for capture phase, as it might interfere with other click events
        // and standard bubbling phase should be fine here.
    });

    // Helper to escape HTML (basic version)
    function escapeHTML(str) {
        if (str === null || str === undefined) return '';
        return str.replace(/[&<>"']/g, function (match) {
            return {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#39;'
            }[match];
        });
    }
    // Note: showToast function is assumed to be globally available from toast.js
});
