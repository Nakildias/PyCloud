/* static/js/videos.js */
document.addEventListener('DOMContentLoaded', function() {
    const modal = document.getElementById('vd-preview-modal');
    if (!modal) {
        /* console.warn('Videos modal (vd-preview-modal) not found on this page.'); */
        return;
    }

    const modalVideoPlayer = document.getElementById('vd-modal-video-preview');
    const modalFilenameDisplay = document.getElementById('vd-modal-filename-display');
    const closeModalButton = document.getElementById('vd-btn-close-modal');
    const modalBackdrop = modal.querySelector('.vd-modal-backdrop');
    const modalDownloadLink = document.getElementById('vd-modal-download-link');
    const modalDeleteButton = document.getElementById('vd-btn-modal-delete');
    const modalRenameButton = document.getElementById('vd-btn-modal-rename');

    let currentFileId = null;
    let currentOriginalFilename = null;
    let currentVideoSrc = null;
    let currentVideoType = null;

    if (!modalVideoPlayer || !modalFilenameDisplay || !closeModalButton || !modalBackdrop || !modalDownloadLink || !modalDeleteButton || !modalRenameButton) {
        console.error('One or more critical video modal elements are missing.');
        return;
    }

    const videoTriggers = document.querySelectorAll('.vd-video-thumbnail-container');

    videoTriggers.forEach(trigger => {
        trigger.addEventListener('click', function() {
            currentVideoSrc = this.dataset.videoSrc;
            currentVideoType = this.dataset.videoType;
            currentOriginalFilename = this.dataset.filename;
            currentFileId = this.dataset.fileId;

            if (currentVideoSrc && currentFileId) {
                /* Clear previous sources from video player */
                while (modalVideoPlayer.firstChild) {
                    modalVideoPlayer.removeChild(modalVideoPlayer.firstChild);
                }

                const sourceElement = document.createElement('source');
                sourceElement.setAttribute('src', currentVideoSrc);
                sourceElement.setAttribute('type', currentVideoType || 'video/mp4'); /* Default type if not specified */
                modalVideoPlayer.appendChild(sourceElement);
                modalVideoPlayer.load(); /* Important to load the new source */
                /* modalVideoPlayer.play(); */ /* Optional: autoplay */

                modalVideoPlayer.setAttribute('alt', `Preview of ${currentOriginalFilename}`); /* Though alt is less common for video tag itself */

                if (modalFilenameDisplay) {
                    modalFilenameDisplay.textContent = currentOriginalFilename;
                }
                if (modalDownloadLink) {
                    modalDownloadLink.href = `${DOWNLOAD_VIDEO_URL_BASE}${currentFileId}`;
                    modalDownloadLink.download = currentOriginalFilename;
                }

                modalDeleteButton.dataset.fileId = currentFileId;
                modalRenameButton.dataset.fileId = currentFileId;
                modalRenameButton.dataset.originalFilename = currentOriginalFilename;

                modal.style.display = 'flex';
                document.body.style.overflow = 'hidden';
            } else {
                console.warn('Video trigger clicked, but no video URL or file ID found.', this);
            }
        });

        trigger.addEventListener('keydown', function(event) {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                this.click();
            }
        });
    });

    function closeModal() {
        modal.style.display = 'none';
        if (modalVideoPlayer) {
            modalVideoPlayer.pause();
            /* Remove sources to stop download/streaming and free resources */
            while (modalVideoPlayer.firstChild) {
                modalVideoPlayer.removeChild(modalVideoPlayer.firstChild);
            }
            modalVideoPlayer.removeAttribute('src'); /* Also remove src attribute if directly set */
            modalVideoPlayer.load(); /* Resets the media element */
        }
        document.body.style.overflow = '';
        currentFileId = null;
        currentOriginalFilename = null;
        currentVideoSrc = null;
        currentVideoType = null;
    }

    if (closeModalButton) {
        closeModalButton.addEventListener('click', closeModal);
    }
    if (modalBackdrop) {
        modalBackdrop.addEventListener('click', closeModal);
    }
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape' && modal.style.display === 'flex') {
            closeModal();
        }
    });

    /* --- Delete Video Functionality --- */
    modalDeleteButton.addEventListener('click', async function() {
        if (!currentFileId) return;

        if (confirm(`Are you sure you want to delete "${currentOriginalFilename}"? This action cannot be undone.`)) {
            try {
                const response = await fetch(`${DELETE_VIDEO_URL_BASE}${currentFileId}`, { /* Uses global DELETE_VIDEO_URL_BASE */
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': CSRF_TOKEN,
                        'Content-Type': 'application/json'
                    }
                });
                const data = await response.json();

                if (response.ok && data.status === 'success') {
                    if (typeof showToast === 'function') showToast(data.message || 'Video deleted successfully.', 'success');
                    const cardToRemove = document.getElementById(`vd-card-${currentFileId}`);
                    if (cardToRemove) {
                        cardToRemove.remove();
                    }
                    closeModal();
                    const galleryGrid = document.querySelector('.vd-gallery-grid');
                    if (galleryGrid && galleryGrid.children.length === 0) {
                        const emptyMessageHTML = `
                        <div class="vd-empty-message">
                        <p>You haven't uploaded any videos yet.</p>
                        <p><a href="${document.querySelector('.vd-empty-message a') ? document.querySelector('.vd-empty-message a').href : '#'}" class="btn btn-primary">Upload Videos</a></p>
                        </div>`;
                        const pageContainer = document.querySelector('.vd-page-container');
                        if(pageContainer && !pageContainer.querySelector('.vd-empty-message')) {
                            if(galleryGrid) galleryGrid.insertAdjacentHTML('afterend', emptyMessageHTML);
                        }
                    }
                } else {
                    if (typeof showToast === 'function') showToast(data.message || 'Failed to delete video.', 'error');
                }
            } catch (error) {
                console.error('Error deleting video:', error);
                if (typeof showToast === 'function') showToast('An error occurred while deleting the video.', 'error');
            }
        }
    });

    /* --- Rename Video Functionality --- */
    modalRenameButton.addEventListener('click', async function() {
        if (!currentFileId) return;

        const newName = prompt("Enter the new filename (including extension, e.g., new_video.mp4):", currentOriginalFilename);

        if (newName && newName.trim() !== "" && newName !== currentOriginalFilename) {
            try {
                const response = await fetch(`${RENAME_VIDEO_URL_BASE}${currentFileId}`, { /* Uses global RENAME_VIDEO_URL_BASE */
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': CSRF_TOKEN,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ new_name: newName.trim() })
                });
                const data = await response.json();

                if (response.ok && data.status === 'success') {
                    if (typeof showToast === 'function') showToast(data.message || 'Video renamed successfully.', 'success');

                    if (modalFilenameDisplay) {
                        modalFilenameDisplay.textContent = data.new_name;
                    }
                    const cardFilenameElement = document.getElementById(`vd-filename-${currentFileId}`);
                    if (cardFilenameElement) {
                        cardFilenameElement.textContent = data.new_name;
                    }
                    if (modalDownloadLink) {
                        modalDownloadLink.download = data.new_name;
                    }
                    const triggerElement = document.querySelector(`.vd-video-thumbnail-container[data-file-id="${currentFileId}"]`);
                    if (triggerElement) {
                        triggerElement.dataset.filename = data.new_name;
                        triggerElement.setAttribute('aria-label', `Preview ${data.new_name}`);
                    }
                    currentOriginalFilename = data.new_name;
                } else {
                    if (typeof showToast === 'function') showToast(data.message || 'Failed to rename video.', 'error');
                }
            } catch (error) {
                console.error('Error renaming video:', error);
                if (typeof showToast === 'function') showToast('An error occurred while renaming the video.', 'error');
            }
        } else if (newName === currentOriginalFilename) {
            if (typeof showToast === 'function') showToast('Filename is the same, no changes made.', 'info');
        }
    });
});
