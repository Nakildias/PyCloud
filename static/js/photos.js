/* static/js/photos.js */
document.addEventListener('DOMContentLoaded', function() {
    const modal = document.getElementById('ph-preview-modal');
    if (!modal) {
        return;
    }

    const modalImage = document.getElementById('ph-modal-image-preview');
    const modalFilenameDisplay = document.getElementById('ph-modal-filename-display');
    const closeModalButton = document.getElementById('ph-btn-close-modal');
    const modalBackdrop = modal.querySelector('.ph-modal-backdrop');
    const modalDownloadLink = document.getElementById('ph-modal-download-link');

    /* Get references to the new buttons */
    const modalDeleteButton = document.getElementById('ph-btn-modal-delete');
    const modalRenameButton = document.getElementById('ph-btn-modal-rename');

    /* Variable to store the current file's ID and original name when modal is open */
    let currentFileId = null;
    let currentOriginalFilename = null;

    if (!modalImage || !modalFilenameDisplay || !closeModalButton || !modalBackdrop || !modalDownloadLink || !modalDeleteButton || !modalRenameButton) {
        console.error('One or more critical photo modal elements are missing.');
        return;
    }

    const imageTriggers = document.querySelectorAll('.ph-image-thumbnail-container');

    imageTriggers.forEach(trigger => {
        trigger.addEventListener('click', function() {
            const imageUrl = this.dataset.previewSrc;
            currentOriginalFilename = this.dataset.filename; /* Store original filename */
            currentFileId = this.dataset.fileId; /* Store file ID */

            if (imageUrl && currentFileId) {
                modalImage.src = imageUrl;
                modalImage.alt = `Preview of ${currentOriginalFilename}`;

                if (modalFilenameDisplay) {
                    modalFilenameDisplay.textContent = currentOriginalFilename;
                }

                if (modalDownloadLink) {
                    modalDownloadLink.href = `${DOWNLOAD_FILE_URL_BASE}${currentFileId}`;
                    modalDownloadLink.download = currentOriginalFilename;
                }

                /* Pass fileId to buttons, e.g., via data attributes if needed, or use currentFileId */
                modalDeleteButton.dataset.fileId = currentFileId;
                modalRenameButton.dataset.fileId = currentFileId;
                modalRenameButton.dataset.originalFilename = currentOriginalFilename;


                modal.style.display = 'flex';
                document.body.style.overflow = 'hidden';
            } else {
                console.warn('Preview trigger clicked, but no image URL or file ID found.', this);
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
        if (modalImage) {
            modalImage.src = '';
        }
        document.body.style.overflow = '';
        currentFileId = null; /* Reset current file ID */
        currentOriginalFilename = null; /* Reset current filename */
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

    /* --- Delete Image Functionality --- */
    modalDeleteButton.addEventListener('click', async function() {
        if (!currentFileId) return;

        if (confirm(`Are you sure you want to delete "${currentOriginalFilename}"? This action cannot be undone.`)) {
            try {
                const response = await fetch(`${DELETE_FILE_URL_BASE}${currentFileId}`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': CSRF_TOKEN, /* Assuming CSRF_TOKEN is globally available from base.html */
                        'Content-Type': 'application/json'
                    }
                });
                const data = await response.json();

                if (response.ok && data.status === 'success') {
                    showToast(data.message || 'File deleted successfully.', 'success');
                    /* Remove the image card from the gallery */
                    const cardToRemove = document.getElementById(`ph-card-${currentFileId}`);
                    if (cardToRemove) {
                        cardToRemove.remove();
                    }
                    closeModal();
                    /* Check if gallery is empty and show message */
                    const galleryGrid = document.querySelector('.ph-gallery-grid');
                    if (galleryGrid && galleryGrid.children.length === 0) {
                        const emptyMessageHTML = `
                        <div class="ph-empty-message">
                        <p>You haven't uploaded any photos yet.</p>
                        <p><a href="${document.querySelector('.ph-empty-message a') ? document.querySelector('.ph-empty-message a').href : '#'}" class="btn btn-primary">Upload Photos</a></p>
                        </div>`;
                        /* Check if ph-page-container exists before trying to insert */
                        const pageContainer = document.querySelector('.ph-page-container');
                        if(pageContainer && !pageContainer.querySelector('.ph-empty-message')) {
                            if(galleryGrid) galleryGrid.insertAdjacentHTML('afterend', emptyMessageHTML);
                        }
                    }
                } else {
                    showToast(data.message || 'Failed to delete file.', 'error');
                }
            } catch (error) {
                console.error('Error deleting file:', error);
                showToast('An error occurred while deleting the file.', 'error');
            }
        }
    });

    /* --- Rename Image Functionality --- */
    modalRenameButton.addEventListener('click', async function() {
        if (!currentFileId) return;

        const newName = prompt("Enter the new filename (including extension, e.g., new_image.jpg):", currentOriginalFilename);

        if (newName && newName.trim() !== "" && newName !== currentOriginalFilename) {
            try {
                const response = await fetch(`${RENAME_FILE_URL_BASE}${currentFileId}`, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': CSRF_TOKEN,
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({ new_name: newName.trim() })
                });
                const data = await response.json();

                if (response.ok && data.status === 'success') {
                    showToast(data.message || 'File renamed successfully.', 'success');

                    /* Update modal title */
                    if (modalFilenameDisplay) {
                        modalFilenameDisplay.textContent = data.new_name;
                    }
                    /* Update filename on the card in the gallery */
                    const cardFilenameElement = document.getElementById(`ph-filename-${currentFileId}`);
                    if (cardFilenameElement) {
                        cardFilenameElement.textContent = data.new_name;
                    }
                    /* Update download link */
                    if (modalDownloadLink) {
                        modalDownloadLink.download = data.new_name;
                    }
                    /* Update the trigger's data-filename for next opening */
                    const triggerElement = document.querySelector(`.ph-image-thumbnail-container[data-file-id="${currentFileId}"]`);
                    if (triggerElement) {
                        triggerElement.dataset.filename = data.new_name;
                        triggerElement.setAttribute('aria-label', `Preview ${data.new_name}`);
                    }

                    currentOriginalFilename = data.new_name; /* Update the stored current name */

                } else {
                    showToast(data.message || 'Failed to rename file.', 'error');
                }
            } catch (error) {
                console.error('Error renaming file:', error);
                showToast('An error occurred while renaming the file.', 'error');
            }
        } else if (newName === currentOriginalFilename) {
            showToast('Filename is the same, no changes made.', 'info');
        }
    });

    /* Ensure showToast function is available (it's in toast.js, linked in base.html) */
    /* If not, you'd need to define a simple version here or ensure toast.js loads first. */
    /* Example:
     * function showToast(message, type = 'info') {
     *     console.log(`Toast [${type}]: ${message}`);
     *     // A proper toast implementation would create and append a styled div.
}
*/
});
