// static/js/files.js

document.addEventListener('DOMContentLoaded', function() {

    // === CSRF Token Setup ===
    const csrfTokenMeta = document.querySelector('meta[name="csrf-token"]');
    const csrfToken = csrfTokenMeta ? csrfTokenMeta.getAttribute('content') : null;
    if (!csrfToken) {
        console.warn('Critical Error: CSRF token meta tag not found. Page actions may fail.');
        if (typeof showToast === 'function') {
            showToast('Critical Error: Missing security token. Page actions may fail.', 'danger', 10000);
        }
    }

    // === Element References ===
    const fileTable = document.getElementById('fl-file-list-table');
    const pasteButton = document.getElementById('fl-btn-paste');
    const dropZone = document.getElementById('fl-drop-zone'); // This is likely for new uploads, not for moving existing items
    const uploadForm = document.getElementById('fl-upload-form');
    const parentFolderInput = document.getElementById('fl-upload-parent-folder-id');
    const currentFolderId = parentFolderInput ? parentFolderInput.value : null;
    const fileUploadInput = document.getElementById('fl-file-upload-input');

    const btnShowCreateFolder = document.getElementById('fl-btn-show-create-folder');
    const formCreateFolder = document.getElementById('fl-form-create-folder');
    const btnCancelCreateFolder = document.getElementById('fl-btn-cancel-create-folder');
    const inputFolderName = formCreateFolder ? formCreateFolder.querySelector('.fl-input-foldername') : null;

    const selectAllCheckbox = document.getElementById('fl-select-all-checkbox');
    let itemRows = fileTable ? Array.from(fileTable.querySelectorAll('.fl-item-row')) : [];

    const multiSelectActionsContainer = document.getElementById('fl-multi-select-actions-toolbar');
    const btnDeleteSelected = document.getElementById('fl-btn-delete-selected');
    const btnCutSelected = document.getElementById('fl-btn-cut-selected');
    const btnCopySelected = document.getElementById('fl-btn-copy-selected');
    const btnArchiveSelected = document.getElementById('fl-btn-archive-selected');
    const btnUnarchiveSelected = document.getElementById('fl-btn-unarchive-selected');
    const btnEditSelected = document.getElementById('fl-btn-edit-selected');
    const btnDownloadSelected = document.getElementById('fl-btn-download-selected');
    const btnShareSelected = document.getElementById('fl-btn-share-selected');
    const downloadFileBaseUrl = window.PyCloud_DownloadFileEndpoint;

    let clipboardData = window.PyCloud_ClipboardData || null;

    const fileViewerModal = document.getElementById('fl-file-viewer-modal');
    const modalFilename = document.getElementById('fl-modal-filename');
    const modalBody = fileViewerModal ? fileViewerModal.querySelector('.fl-modal-body') : null;
    const fileViewerImage = document.getElementById('fl-file-viewer-image');
    const fileViewerVideo = document.getElementById('fl-file-viewer-video');
    const fileViewerAudio = document.getElementById('fl-file-viewer-audio');
    const fileViewerIframe = document.getElementById('fl-file-viewer-iframe');
    const fileViewerUnsupported = document.getElementById('fl-file-viewer-unsupported');
    const unsupportedFilename = document.getElementById('fl-unsupported-filename');
    const unsupportedDownloadLink = document.getElementById('fl-unsupported-download-link');
    const btnCloseModal = document.getElementById('fl-btn-close-modal');

    // NEW: Unselect everything on page refresh (modified for new selection model)
    if (selectAllCheckbox) {
        selectAllCheckbox.checked = false;
        selectAllCheckbox.indeterminate = false;
    }
    itemRows.forEach(row => {
        row.classList.remove('selected');
    });

    // --- Helper Functions ---
    function handleFetchErrors(response) {
        if (!response.ok) {
            return response.json()
            .then(errData => {
                throw new Error(errData.message || `Request failed with status ${response.status}`);
            })
            .catch(() => {
                // Fallback if response.json() fails or if errData.message is not present
                throw new Error(`Request failed: ${response.status} ${response.statusText}`);
            });
        }
        return response.json();
    }

    async function copyToClipboard(text) {
        try {
            await navigator.clipboard.writeText(text);
            if (typeof showToast === 'function') showToast('Link copied to clipboard!', 'success');
        } catch (err) {
            console.error('Failed to copy text: ', err);
            if (typeof showToast === 'function') showToast('Failed to copy link.', 'danger');
        }
    }

    function updatePasteButtonVisibility() {
        if (pasteButton) {
            pasteButton.style.display = (clipboardData && clipboardData.items && clipboardData.items.length > 0) ? 'inline-block' : 'none';
        }
    }

    function updateCutItemVisuals() {
        if (!fileTable) return;
        // Reset all items first
        fileTable.querySelectorAll('.fl-item-row').forEach(row => row.classList.remove('cut-item'));
        // Then apply 'cut-item' class to items in clipboard if operation is 'cut'
        if (clipboardData && clipboardData.operation === 'cut' && clipboardData.items) {
            clipboardData.items.forEach(item => {
                const row = fileTable.querySelector(`.fl-item-row[data-item-id="${item.id}"][data-item-type="${item.type}"]`);
                if (row) {
                    row.classList.add('cut-item');
                }
            });
        }
    }

    // MODIFIED: getSelectedItems to include isPublic
    function getSelectedItems() {
        // Ensure itemRows is up-to-date if called after DOM modifications not involving full reload
        // itemRows = fileTable ? Array.from(fileTable.querySelectorAll('.fl-item-row')) : [];
        return itemRows
        .filter(row => row.classList.contains('selected'))
        .map(row => {
            return {
                id: row.dataset.itemId,
                type: row.dataset.itemType,
                name: row.dataset.itemName,
                isEditable: row.dataset.isEditable === 'true',
                fileExt: row.dataset.fileExt || '',
                isPublic: row.dataset.isPublic === 'true'
            };
        });
    }

    // --- Helper Functions (modify updateMultiSelectActionsVisibility) ---
    function updateMultiSelectActionsVisibility() {
        if (multiSelectActionsContainer) {
            const selectedItems = getSelectedItems();
            multiSelectActionsContainer.style.display = selectedItems.length > 0 ? 'flex' : 'none';

            // Hide all conditional buttons initially
            if (btnArchiveSelected) btnArchiveSelected.style.display = 'none';
            if (btnUnarchiveSelected) btnUnarchiveSelected.style.display = 'none';
            if (btnEditSelected) btnEditSelected.style.display = 'none';
            if (btnDownloadSelected) btnDownloadSelected.style.display = 'none';
            if (btnShareSelected) btnShareSelected.style.display = 'none';


            if (selectedItems.length > 0) {
                const allFolders = selectedItems.every(item => item.type === 'folder');
                const allFiles = selectedItems.every(item => item.type === 'file');
                const allArchives = allFiles && selectedItems.every(item => ['zip', '7z', 'rar'].includes(item.fileExt));
                const singleEditableFile = selectedItems.length === 1 && selectedItems[0].type === 'file' && selectedItems[0].isEditable;
                const singleFileSelected = selectedItems.length === 1 && selectedItems[0].type === 'file';
                const unshareSVG = '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" class="icon icon-tabler icons-tabler-outline icon-tabler-share-off"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M6 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0" /><path d="M18 6m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0" /><path d="M15.861 15.896a3 3 0 0 0 4.265 4.22m.578 -3.417a3.012 3.012 0 0 0 -1.507 -1.45" /><path d="M8.7 10.7l1.336 -.688m2.624 -1.352l2.64 -1.36" /><path d="M8.7 13.3l6.6 3.4" /><path d="M3 3l18 18" /></svg>';
                const shareSVG = '<svg  xmlns="http://www.w3.org/2000/svg"  width="24"  height="24"  viewBox="0 0 24 24"  fill="none"  stroke="currentColor"  stroke-width="1.3"  stroke-linecap="round"  stroke-linejoin="round"  class="icon icon-tabler icons-tabler-outline icon-tabler-share"><path stroke="none" d="M0 0h24v24H0z" fill="none"/><path d="M6 12m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0" /><path d="M18 6m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0" /><path d="M18 18m-3 0a3 3 0 1 0 6 0a3 3 0 1 0 -6 0" /><path d="M8.7 10.7l6.6 -3.4" /><path d="M8.7 13.3l6.6 3.4" /></svg>';

                // Show Archive button if all selected are folders
                if (allFolders) {
                    if (btnArchiveSelected) btnArchiveSelected.style.display = 'inline-block';
                }
                // Show Unarchive button if all selected are archive files
                if (allArchives) {
                    if (btnUnarchiveSelected) btnUnarchiveSelected.style.display = 'inline-block';
                }
                // Show Edit button if exactly one editable file is selected
                if (singleEditableFile) {
                    if (btnEditSelected) btnEditSelected.style.display = 'inline-block';
                }

                // Show Download button if all selected are files (not folders)
                if (allFiles && selectedItems.length > 0) {
                    if (btnDownloadSelected) btnDownloadSelected.style.display = 'inline-block';
                }

                // NEW: Show Share/Unshare button if exactly one file is selected
                if (singleFileSelected) {
                    if (btnShareSelected) {
                        btnShareSelected.style.display = 'inline-block';
                        const fileData = selectedItems[0];
                        if (fileData.isPublic) {
                            btnShareSelected.innerHTML = unshareSVG;
                            btnShareSelected.classList.remove('btn-info');
                            btnShareSelected.classList.add('btn-warning');
                        } else {
                            btnShareSelected.innerHTML = shareSVG;
                            btnShareSelected.classList.remove('btn-warning');
                            btnShareSelected.classList.add('btn-info');
                        }
                    }
                }
            }
        }
    }

    // --- Event Listeners (add this) ---
    if (btnShareSelected) {
        btnShareSelected.addEventListener('click', function() {
            const selectedItems = getSelectedItems();
            if (selectedItems.length !== 1 || selectedItems[0].type !== 'file') {
                if (typeof showToast === 'function') showToast('Please select a single file to share or unshare.', 'warning');
                return;
            }
            const fileToShare = selectedItems[0];

            if (fileToShare.isPublic) {
                if (confirm(`Are you sure you want to unshare '${fileToShare.name}'? This will disable its public link.`)) {
                    handleUnshareFile(fileToShare.id, this);
                }
            } else {
                if (confirm(`Are you sure you want to share '${fileToShare.name}' publicly?`)) {
                    handleShareFile(fileToShare.id, this);
                }
            }
        });
    }

    function toggleShare(button, fileId, fileName) {
        const isCurrentlyPublic = button.textContent.trim().toLowerCase() === 'unshare';
        const action = isCurrentlyPublic ? 'unshare' : 'share';
        const confirmationMessage = isCurrentlyPublic ?
        `Are you sure you want to unshare '${fileName}'? This will disable its public link.` :
        `Are you sure you want to share '${fileName}' publicly?`;

        if (!confirm(confirmationMessage)) {
            return;
        }

        const url = isCurrentlyPublic ? `/unshare_file/${fileId}` : `/share_file/${fileId}`;

        fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken
            }
        })
        .then(response => handleFetchErrors(response))
        .then(data => {
            if (data.success) {
                button.textContent = isCurrentlyPublic ? 'Share' : 'Unshare';
                if (isCurrentlyPublic) {
                    button.classList.remove('btn-warning');
                    button.classList.add('btn-info');
                } else {
                    button.classList.remove('btn-info');
                    button.classList.add('btn-warning');
                }
            }
        })
        .catch(error => {
            console.error('Error:', error);
            if (typeof showToast === 'function') showToast(`Failed to ${action} file.`, 'danger');
        });
    }


    // MODIFIED: updateSelectAllCheckboxState to work with .selected class on item rows
    function updateSelectAllCheckboxState() {
        if (!selectAllCheckbox || itemRows.length === 0) return;
        const selectedCount = getSelectedItems().length;
        if (selectedCount === 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        } else if (selectedCount === itemRows.length) {
            selectAllCheckbox.checked = true;
            selectAllCheckbox.indeterminate = false;
        } else {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = true;
        }
    }

    // --- Create Folder Form Toggle Logic ---
    if (btnShowCreateFolder && formCreateFolder && btnCancelCreateFolder && inputFolderName) {
        btnShowCreateFolder.addEventListener('click', () => {
            formCreateFolder.style.display = 'block';
            btnShowCreateFolder.style.display = 'none';
            inputFolderName.value = '';
            inputFolderName.focus();
        });
        btnCancelCreateFolder.addEventListener('click', () => {
            formCreateFolder.style.display = 'none';
            btnShowCreateFolder.style.display = '';
        });
    }

    // --- Upload Handling (Drag & Drop / Browse) ---
    function handleFiles(files) {
        if (!csrfToken) {
            if (typeof showToast === 'function') showToast('Cannot upload: Missing security token.', 'danger');
            return;
        }
        const parentFolderIdToUse = parentFolderInput ? parentFolderInput.value : '';
        let uploadPromises = [];
        const totalFiles = files.length;

        if (typeof showToast === 'function') showToast(`Starting upload of ${totalFiles} file(s)...`, 'info', 3000);

        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            const formData = new FormData();
            formData.append('file', file);
            formData.append('parent_folder_id', parentFolderIdToUse);

            const uploadURL = window.PyCloud_UploadFileURL;
            if (!uploadURL) {
                console.error("Upload URL is not defined.");
                if (typeof showToast === 'function') showToast('Upload configuration error.', 'danger');
                return;
            }

            const uploadPromise = fetch(uploadURL, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json' },
                body: formData
            })
            .then(handleFetchErrors)
            .then(data => {
                if (data.status === 'success') {
                    return { success: true, file: file.name, message: data.message };
                } else {
                    throw new Error(data.message || `Upload failed for ${file.name}`);
                }
            })
            .catch(error => {
                console.error(`Error uploading ${file.name}:`, error);
                return { success: false, file: file.name, message: error.message };
            });
            uploadPromises.push(uploadPromise);
        }

        Promise.allSettled(uploadPromises)
        .then(results => {
            let successfulUploads = results.filter(r => r.status === 'fulfilled' && r.value.success).length;
            let failedUploads = totalFiles - successfulUploads;
            let toastMessage = '';
            let toastType = 'info';

            if (failedUploads > 0) {
                const firstErrorResult = results.find(r => r.status === 'rejected' || (r.status === 'fulfilled' && !r.value.success));
                const errorMsg = firstErrorResult ? (firstErrorResult.reason ? firstErrorResult.reason.message : (firstErrorResult.value ? firstErrorResult.value.message : 'Unknown error')) : 'Unknown error';
                toastMessage = `Upload finished: ${successfulUploads} succeeded, ${failedUploads} failed. Error: ${errorMsg}`;
                toastType = 'warning';
            } else if (successfulUploads > 0) {
                toastMessage = `All ${successfulUploads} files uploaded successfully! Reloading...`;
                toastType = 'success';
            } else {
                toastMessage = 'Upload process completed.';
            }
            if (typeof showToast === 'function') showToast(toastMessage, toastType, failedUploads > 0 || successfulUploads === 0 ? 7000 : 3000);
            if (successfulUploads > 0) {
                setTimeout(() => {
                    location.reload();
                }, failedUploads > 0 ? 5000 : 2500);
            }
        });
    }

    if (dropZone && parentFolderInput && csrfToken) {
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, (e) => { e.preventDefault(); e.stopPropagation(); }, false);
        });
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.add('drag-over'), false);
        });
        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, () => dropZone.classList.remove('drag-over'), false);
        });
        dropZone.addEventListener('drop', (e) => {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                handleFiles(files);
            }
        }, false);
    }

    if (fileUploadInput) {
        fileUploadInput.addEventListener('change', function(event) {
            const files = event.target.files;
            if (files && files.length > 0) {
                handleFiles(files);
                event.target.value = null; // Reset file input
            }
        });
    }

    // --- Clipboard & Item Actions ---
    function setClipboard(itemsArray, operation) {
        if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }
        if (!itemsArray || itemsArray.length === 0) {
            if (typeof showToast === 'function') showToast('No items selected for clipboard operation.', 'info');
            return;
        }
        fetch(`/files/api/clipboard/set`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ items: itemsArray, operation: operation })
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                clipboardData = { items: itemsArray, operation: operation }; // Store the selected items directly
                if (typeof showToast === 'function') showToast(data.message || `${itemsArray.length} item(s) ${operation === 'cut' ? 'cut' : 'copied'} to clipboard.`, 'success');
                updatePasteButtonVisibility();
                updateCutItemVisuals();
            } else {
                throw new Error(data.message || `Failed to ${operation} items.`);
            }
        })
        .catch(error => {
            console.error(`Error setting clipboard for ${operation}:`, error);
            if (typeof showToast === 'function') showToast(`Clipboard Error: ${error.message}`, 'danger');
        });
    }

    function handlePaste() {
        if (!clipboardData || !clipboardData.items || clipboardData.items.length === 0) {
            if (typeof showToast === 'function') showToast('Clipboard is empty or invalid.', 'info');
            return;
        }
        if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }

        if (typeof showToast === 'function') showToast(`Pasting ${clipboardData.items.length} item(s)...`, 'info', 3000);

        fetch(`/files/api/clipboard/paste`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ target_folder_id: currentFolderId }) // Server will use clipboard from session
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || 'Paste successful! Reloading...', 'success');
                const wasCut = clipboardData.operation === 'cut';
                clipboardData = null; // Clear client-side clipboard
                updatePasteButtonVisibility();
                updateCutItemVisuals();
                setTimeout(() => { location.reload(); }, 1500);
            } else {
                let errorMsg = data.message || 'Paste operation failed.';
                if (data.errors && Array.isArray(data.errors) && data.errors.length > 0) {
                    errorMsg = `Paste failed for some items: ${data.errors.join(', ')}`;
                }
                if (typeof showToast === 'function') showToast(errorMsg, 'warning');
                if (clipboardData && clipboardData.operation === 'cut') {
                    // Consider if cut items should remain visually "cut"
                }
            }
        })
        .catch(error => {
            console.error('Error during paste operation:', error);
            if (typeof showToast === 'function') showToast(`Paste Error: ${error.message}`, 'danger');
        });
    }

    // --- Rename Handling ---
    function handleRenameButtonClick(sourceElement) {
        const row = sourceElement.closest('.fl-item-row');
        if (!row) return;
        const id = row.dataset.itemId;
        const currentName = row.dataset.itemName;
        const displayElement = row.querySelector('.fl-itemname-display');
        const inputField = row.querySelector('.fl-itemname-input');

        if (displayElement && inputField) {
            // Hide other active rename inputs
            if (fileTable) {
                fileTable.querySelectorAll('.fl-itemname-input').forEach(inp => {
                    if (inp !== inputField && inp.style.display !== 'none') { resetRenameInput(inp); }
                });
            }
            inputField.value = currentName;
            displayElement.style.display = 'none';
            inputField.style.display = 'inline-block';
            inputField.focus();
            inputField.select();
        } else { console.error("Rename elements not found for ID:", id); }
    }

    function handleRenameInputBlurOrEnter(inputField) {
        if (inputField.style.display === 'none') return;
        const row = inputField.closest('.fl-item-row');
        if (!row) return;
        const itemType = row.dataset.itemType;
        const id = row.dataset.itemId;
        const originalName = row.dataset.itemName;
        const newName = inputField.value.trim();

        resetRenameInput(inputField);

        if (newName && newName !== originalName) {
            const displayElement = row.querySelector('.fl-itemname-display');
            const nameContainer = (itemType === 'folder' && displayElement) ? displayElement.querySelector('a') : displayElement;
            if (nameContainer) nameContainer.textContent = newName; // Optimistic update
            saveNewName(itemType, id, newName, displayElement, row);
        } else if (!newName) {
            if (typeof showToast === 'function') showToast('Name cannot be empty.', 'warning');
            const displayElement = row.querySelector('.fl-itemname-display');
            const nameContainer = (itemType === 'folder' && displayElement) ? displayElement.querySelector('a') : displayElement;
            if (nameContainer) nameContainer.textContent = originalName;
        }
    }

    function resetRenameInput(inputField) {
        const row = inputField.closest('.fl-item-row');
        if (!row) return;
        const displayElement = row.querySelector('.fl-itemname-display');
        if (displayElement) displayElement.style.display = '';
        inputField.style.display = 'none';
    }

    function saveNewName(itemType, id, newName, displayElement, rowElement) {
        if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }
        let url = itemType === 'folder' ? `/files/folder/rename/${id}` : `/files/rename/${id}`;
        fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ new_name: newName })
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success' && data.new_name) {
                if (typeof showToast === 'function') showToast(data.message || `Rename successful!`, 'success');
                const nameContainer = (itemType === 'folder' && displayElement) ? displayElement.querySelector('a') : displayElement;
                if (nameContainer) nameContainer.textContent = data.new_name;
                if (rowElement) rowElement.dataset.itemName = data.new_name;
            } else {
                throw new Error(data.message || 'Rename operation failed.');
            }
        })
        .catch(error => {
            console.error(`Error renaming ${itemType}:`, error);
            if (typeof showToast === 'function') showToast(`Rename Error: ${error.message}`, 'danger');
            const originalName = rowElement.dataset.itemName;
            const nameContainer = (itemType === 'folder' && displayElement) ? displayElement.querySelector('a') : displayElement;
            if (nameContainer) nameContainer.textContent = originalName;
        });
    }

    // --- Share/Unshare Handling ---
    function handleShareFile(fileId, sourceElement) {
        if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }
        const addPassword = confirm("Protect this share link with a password?");
        let password = null;
        if (addPassword) {
            password = prompt("Enter password (leave blank for none):");
            if (password === null) {
                if (typeof showToast === 'function') showToast('Share cancelled.', 'info');
                return;
            }
        }
        const payload = {};
        if (password !== null && password !== "") {
            payload.password = password;
        }
        fetch(`/files/share/${fileId}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken, 'Accept': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || 'File shared!', 'success');
                updateShareUI(fileId, true, data.share_url, data.password_protected);
            } else {
                throw new Error(data.message || 'Failed to share file.');
            }
        })
        .catch(error => {
            console.error('Error during share fetch:', error);
            if (typeof showToast === 'function') showToast(`Share Error: ${error.message}`, 'danger');
        });
    }

    function handleUnshareFile(fileId, sourceElement) {
        if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }
        fetch(`/files/unshare/${fileId}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json' }
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || 'Sharing disabled.', 'success');
                updateShareUI(fileId, false, null, false);
            } else {
                throw new Error(data.message || 'Failed to unshare file.');
            }
        })
        .catch(error => {
            console.error('Error during unshare fetch:', error);
            if (typeof showToast === 'function') showToast(`Unshare Error: ${error.message}`, 'danger');
        });
    }

    function updateShareUI(fileId, isShared, shareUrl, passwordProtected) {
        const row = document.querySelector(`.fl-item-row[data-item-id="${fileId}"][data-item-type="file"]`);
        if (!row) return;

        row.dataset.isPublic = isShared ? 'true' : 'false';
        row.dataset.isPasswordProtected = passwordProtected ? 'true' : 'false';
        row.dataset.shareUrl = shareUrl || '';

        const shareIconIndicator = row.querySelector(`#fl-share-icon-${fileId}`);
        const passwordIndicatorSpan = shareIconIndicator ? shareIconIndicator.querySelector('.fl-password-indicator') : null;

        if (shareIconIndicator) {
            if (isShared && shareUrl) {
                shareIconIndicator.style.display = 'inline-flex';
                shareIconIndicator.dataset.link = shareUrl;

                if (passwordIndicatorSpan) {
                    passwordIndicatorSpan.textContent = passwordProtected ? '🔐' : '🔓';
                    passwordIndicatorSpan.style.display = 'inline';
                }
                shareIconIndicator.title = passwordProtected ? "Copy password-protected share link" : "Copy share link (no password)";

            } else {
                shareIconIndicator.style.display = 'none';
                delete shareIconIndicator.dataset.link;
                shareIconIndicator.title = "Copy share link";
                if (passwordIndicatorSpan) {
                    passwordIndicatorSpan.style.display = 'none';
                    passwordIndicatorSpan.textContent = '';
                }
            }
        }
        updateMultiSelectActionsVisibility();
    }

    // --- Archive/Extract Handling ---
    function handleArchiveFolder(folderId, folderName) {
        if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }
        if (typeof showToast === 'function') showToast(`Archiving folder '${folderName}'... (this may take a moment)`, 'info', 10000);
        fetch(`/files/folder/archive/${folderId}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json' }
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || `Folder '${folderName}' archived! Reloading...`, 'success');
                setTimeout(() => { location.reload(); }, 1500);
            } else {
                throw new Error(data.message || 'Failed to archive folder.');
            }
        })
        .catch(error => {
            console.error('Error archiving folder:', error);
            if (typeof showToast === 'function') showToast(`Archive Error: ${error.message}`, 'danger');
        });
    }

    function handleExtractFile(fileId, fileName) {
        if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }
        if (typeof showToast === 'function') showToast(`Extracting archive '${fileName}'... (this may take a moment)`, 'info', 10000);
        fetch(`/files/extract/${fileId}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json' }
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || `Archive '${fileName}' extracted! Reloading...`, 'success');
                setTimeout(() => { location.reload(); }, 1500);
            } else {
                if (data.message && data.message.toLowerCase().includes('insufficient storage')) {
                    if (typeof showToast === 'function') showToast(data.message, 'warning', 7000);
                } else {
                    throw new Error(data.message || 'Failed to extract archive.');
                }
            }
        })
        .catch(error => {
            console.error('Error extracting archive:', error);
            if (typeof showToast === 'function') showToast(`Extract Error: ${error.message}`, 'danger');
        });
    }

    // --- Delete Handling ---
    function handleDeleteFile(fileId, fileName, sourceElement) {
        if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }
        fetch(`/files/delete/${fileId}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json' }
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || `File '${fileName}' deleted!`, 'success');
                const rowToRemove = document.querySelector(`.fl-item-row[data-item-id="${fileId}"][data-item-type="file"]`);
                if (rowToRemove) {
                    const index = itemRows.findIndex(r => r === rowToRemove);
                    if (index > -1) itemRows.splice(index, 1);
                    rowToRemove.remove();
                }
                const shareRow = document.getElementById(`fl-share-link-row-${fileId}`);
                if (shareRow) shareRow.remove();

                updateSelectAllCheckboxState();
                updateMultiSelectActionsVisibility();
            } else {
                throw new Error(data.message || 'Failed to delete file.');
            }
        })
        .catch(error => {
            console.error('Error deleting file:', error);
            if (typeof showToast === 'function') showToast(`Delete Error: ${error.message}`, 'danger');
        });
    }

    function handleDeleteFolder(folderId, folderName, sourceElement) {
        if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }
        fetch(`/files/folder/delete/${folderId}`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json' }
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || `Folder '${folderName}' deleted!`, 'success');
                const rowToRemove = document.querySelector(`.fl-item-row[data-item-id="${folderId}"][data-item-type="folder"]`);
                if (rowToRemove) {
                    const index = itemRows.findIndex(r => r === rowToRemove);
                    if (index > -1) itemRows.splice(index, 1);
                    rowToRemove.remove();
                }
                updateSelectAllCheckboxState();
                updateMultiSelectActionsVisibility();
            } else {
                throw new Error(data.message || 'Failed to delete folder.');
            }
        })
        .catch(error => {
            console.error('Error deleting folder:', error);
            if (typeof showToast === 'function') showToast(`Delete Error: ${error.message}`, 'danger');
        });
    }

    // === File Viewer Modal Logic ===
    function openFileViewerModal(fileUrl, filename, originalFileIdForDownload) {
        if (!fileViewerModal || !modalFilename || !modalBody ||
            !fileViewerImage || !fileViewerVideo || !fileViewerAudio ||
            !fileViewerIframe || !fileViewerUnsupported) {
            console.error('File viewer modal elements not found.');
        if (typeof showToast === 'function') showToast('Error: Could not open file viewer.', 'danger');
        return;
            }

            fileViewerImage.style.display = 'none';
            fileViewerImage.src = '';
            fileViewerVideo.style.display = 'none';
            fileViewerVideo.src = '';
            fileViewerVideo.removeAttribute('src');
            fileViewerAudio.style.display = 'none';
            fileViewerAudio.src = '';
            fileViewerAudio.removeAttribute('src');
            fileViewerIframe.style.display = 'none';
            fileViewerIframe.src = 'about:blank';
            fileViewerUnsupported.style.display = 'none';

            modalFilename.textContent = filename;
            const fileExtension = filename.split('.').pop().toLowerCase();
            let viewerElement = null;

            if (['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg', 'bmp', 'ico'].includes(fileExtension)) {
                viewerElement = fileViewerImage;
                fileViewerImage.src = fileUrl;
            } else if (['mp4', 'webm', 'ogg', 'mov'].includes(fileExtension)) {
                viewerElement = fileViewerVideo;
                fileViewerVideo.src = fileUrl;
            } else if (['mp3', 'wav', 'aac', 'flac', 'm4a'].includes(fileExtension)) {
                viewerElement = fileViewerAudio;
                fileViewerAudio.src = fileUrl;
            } else if (['pdf', 'txt'].includes(fileExtension) ||
                (window.PyCloud_Config && window.PyCloud_Config.VIEWABLE_MIMES_IFRAME && window.PyCloud_Config.VIEWABLE_MIMES_IFRAME.includes(fileExtension))) {
                viewerElement = fileViewerIframe;
            fileViewerIframe.src = fileUrl;
                } else {
                    viewerElement = fileViewerUnsupported;
                    if (unsupportedFilename) unsupportedFilename.textContent = `File: ${filename}`;
                    if (unsupportedDownloadLink && originalFileIdForDownload) {
                        unsupportedDownloadLink.href = `${downloadFileBaseUrl}${originalFileIdForDownload}`;
                        unsupportedDownloadLink.download = filename;
                        unsupportedDownloadLink.style.display = 'inline-block';
                    } else if (unsupportedDownloadLink) {
                        unsupportedDownloadLink.style.display = 'none';
                    }
                }

                if (viewerElement) {
                    viewerElement.style.display = (viewerElement === fileViewerIframe || viewerElement === fileViewerUnsupported) ? 'block' : 'block';
                    if (viewerElement === fileViewerVideo || viewerElement === fileViewerAudio) {
                        viewerElement.load();
                    }
                }

                fileViewerModal.style.display = 'flex';
                document.body.style.overflow = 'hidden';
    }

    function closeFileViewerModal() {
        if (!fileViewerModal) return;
        fileViewerModal.style.display = 'none';

        if (fileViewerImage) fileViewerImage.src = '';
        if (fileViewerVideo) { fileViewerVideo.pause(); fileViewerVideo.src = ''; fileViewerVideo.removeAttribute('src'); fileViewerVideo.load(); }
        if (fileViewerAudio) { fileViewerAudio.pause(); fileViewerAudio.src = ''; fileViewerAudio.removeAttribute('src'); fileViewerAudio.load(); }
        if (fileViewerIframe) fileViewerIframe.src = 'about:blank';

        if (fileViewerImage) fileViewerImage.style.display = 'none';
        if (fileViewerVideo) fileViewerVideo.style.display = 'none';
        if (fileViewerAudio) fileViewerAudio.style.display = 'none';
        if (fileViewerIframe) fileViewerIframe.style.display = 'none';
        if (fileViewerUnsupported) fileViewerUnsupported.style.display = 'none';

        document.body.style.overflow = '';
    }

    if (btnCloseModal) {
        btnCloseModal.addEventListener('click', closeFileViewerModal);
    }

    if (fileViewerModal) {
        fileViewerModal.addEventListener('click', function(event) {
            if (event.target === fileViewerModal) {
                closeFileViewerModal();
            }
        });
    }
    document.addEventListener('keydown', function(event) {
        if (event.key === 'Escape' && fileViewerModal && fileViewerModal.style.display === 'flex') {
            closeFileViewerModal();
        }
    });

    // === Event Listeners ===
    // MODIFIED: Select all checkbox logic
    if (selectAllCheckbox) {
        selectAllCheckbox.addEventListener('change', function() {
            itemRows.forEach(row => {
                // Prevent selecting the '..' folder
                if (row.classList.contains('fl-parent-folder-row')) {
                    row.classList.remove('selected'); // Ensure it's not selected
                } else if (selectAllCheckbox.checked) {
                    row.classList.add('selected');
                } else {
                    row.classList.remove('selected');
                }
            });
            updateSelectAllCheckboxState();
            updateMultiSelectActionsVisibility();
        });
    }

    if (fileTable && fileTable.querySelector('tbody')) {
        const tableBody = fileTable.querySelector('tbody');

        tableBody.addEventListener('click', function(event) {
            const target = event.target;
            const clickedRow = target.closest('.fl-item-row');

            if (clickedRow) {
                // ADD THIS CONDITION: Prevent selection if it's the '..' row
                if (clickedRow.classList.contains('fl-parent-folder-row')) {
                    event.stopPropagation(); // Stop the event from propagating further
                    clickedRow.classList.remove('selected'); // Ensure it's not selected
                    updateSelectAllCheckboxState();
                    updateMultiSelectActionsVisibility();
                    return; // Exit the function to prevent further selection logic
                }

                const shareIconElement = target.closest('.fl-share-icon-indicator');
                if (shareIconElement) {
                    event.stopPropagation();
                    const linkToCopy = shareIconElement.dataset.link;
                    if (linkToCopy) {
                        copyToClipboard(linkToCopy);
                    }
                    return;
                }

                const isInteractive = target.tagName === 'A' ||
                target.tagName === 'INPUT' ||
                target.closest('a') ||
                target.closest('input');

                if (isInteractive) {
                    const viewableLink = target.classList.contains('fl-viewable-file-link') ? target : target.closest('.fl-viewable-file-link');
                    if (viewableLink) {
                        event.preventDefault();
                        const fileUrl = viewableLink.href;
                        const filename = viewableLink.dataset.filename || viewableLink.textContent || 'File';
                        const fileId = clickedRow.dataset.itemId;
                        openFileViewerModal(fileUrl, filename, fileId);
                        return;
                    }
                    return;
                }

                clickedRow.classList.toggle('selected');
                updateSelectAllCheckboxState();
                updateMultiSelectActionsVisibility();
            }
        });


        tableBody.addEventListener('focusout', function(event) {
            if (event.target.classList.contains('fl-itemname-input')) {
                setTimeout(() => {
                    if (document.activeElement !== event.target) {
                        handleRenameInputBlurOrEnter(event.target);
                    }
                }, 150);
            }
        });
        tableBody.addEventListener('keydown', function(event) {
            if (event.target.classList.contains('fl-itemname-input')) {
                if (event.key === 'Enter') {
                    event.preventDefault();
                    handleRenameInputBlurOrEnter(event.target);
                } else if (event.key === 'Escape') {
                    resetRenameInput(event.target);
                }
            }
        });

        let draggedItem = null; // Stores the item being dragged

        // Add draggable attribute to all item rows EXCEPT the '..' folder
        fileTable.querySelectorAll('.fl-item-row').forEach(row => {
            // Ensure the '..' folder is not draggable
            if (!row.classList.contains('fl-parent-folder-row')) {
                row.setAttribute('draggable', 'true');
            } else {
                row.setAttribute('draggable', 'false'); // Explicitly non-draggable
            }
        });

        tableBody.addEventListener('dragstart', (e) => {
            const row = e.target.closest('.fl-item-row');
            if (row && !row.classList.contains('fl-parent-folder-row')) { // Ensure it's not the '..' folder
                // If multiple items are selected, allow dragging all selected items
                const selectedItems = getSelectedItems();
                if (selectedItems.length > 0 && selectedItems.some(item => item.id === row.dataset.itemId && item.type === row.dataset.itemType)) {
                    // If the dragged item is among the selected ones, we drag all selected
                    draggedItem = selectedItems;
                } else {
                    // Otherwise, only drag the single item
                    draggedItem = [{
                        id: row.dataset.itemId,
                        type: row.dataset.itemType,
                        name: row.dataset.itemName
                    }];
                }

                e.dataTransfer.setData('text/plain', JSON.stringify(draggedItem));
                e.dataTransfer.effectAllowed = 'move';
                row.classList.add('is-dragging'); // Add a class for visual feedback
            } else {
                e.preventDefault(); // Prevent dragging the '..' folder
            }
        });

        tableBody.addEventListener('dragend', (e) => {
            e.target.closest('.fl-item-row')?.classList.remove('is-dragging');
            // Remove 'drag-over' from all folders in case drag ends outside a dropzone
            fileTable.querySelectorAll('.fl-item-row[data-item-type="folder"]').forEach(folderRow => {
                folderRow.classList.remove('drag-over-folder');
            });
            draggedItem = null; // Clear dragged item
        });

        tableBody.addEventListener('dragenter', (e) => {
            e.preventDefault(); // Necessary to allow drop
            const targetRow = e.target.closest('.fl-item-row');
            // Check if the target is a folder (including the '..' folder) and an item is being dragged
            if (targetRow && targetRow.dataset.itemType === 'folder' && draggedItem) {
                const targetFolderId = targetRow.dataset.itemId;
                // Prevent dropping a folder into itself (important for regular folders)
                const isDroppingIntoSelf = draggedItem.some(item => item.id === targetFolderId && item.type === 'folder');

                // Allow drag-over effect if not dropping into self
                // Also, allow drag-over if it's the '..' folder (since its ID is the parent's ID, it won't be 'self')
                if (!isDroppingIntoSelf || targetRow.classList.contains('fl-parent-folder-row')) {
                    targetRow.classList.add('drag-over-folder');
                }
            }
        });

        tableBody.addEventListener('dragover', (e) => {
            e.preventDefault(); // Necessary to allow drop
            // Only allow 'move' effect if the target is a droppable folder (including '..')
            const targetRow = e.target.closest('.fl-item-row');
            if (targetRow && targetRow.dataset.itemType === 'folder' && draggedItem) {
                const targetFolderId = targetRow.dataset.itemId;
                const isDroppingIntoSelf = draggedItem.some(item => item.id === targetFolderId && item.type === 'folder');

                if (!isDroppingIntoSelf || targetRow.classList.contains('fl-parent-folder-row')) {
                    e.dataTransfer.dropEffect = 'move'; // Visual feedback for move operation
                } else {
                    e.dataTransfer.dropEffect = 'none'; // Not a valid drop target
                }
            } else {
                e.dataTransfer.dropEffect = 'none'; // Not a valid drop target
            }
        });

        tableBody.addEventListener('dragleave', (e) => {
            const targetRow = e.target.closest('.fl-item-row');
            if (targetRow && targetRow.dataset.itemType === 'folder') {
                targetRow.classList.remove('drag-over-folder');
            }
        });

        tableBody.addEventListener('drop', (e) => {
            e.preventDefault();
            const targetRow = e.target.closest('.fl-item-row');

            // Remove drag-over visual feedback from all folders
            fileTable.querySelectorAll('.fl-item-row[data-item-type="folder"]').forEach(folderRow => {
                folderRow.classList.remove('drag-over-folder');
            });

            if (targetRow && targetRow.dataset.itemType === 'folder' && draggedItem) {
                const targetFolderId = targetRow.dataset.itemId === 'null' ? null : targetRow.dataset.itemId; // Handle 'null' for root
                const targetFolderName = targetRow.dataset.itemName;

                const itemsToMove = draggedItem;
                const isDroppingIntoSelf = itemsToMove.some(item => item.id === targetFolderId && item.type === 'folder');

                // Prevent dropping a folder into itself (applies to regular folders)
                if (isDroppingIntoSelf && !targetRow.classList.contains('fl-parent-folder-row')) {
                    if (typeof showToast === 'function') showToast('Cannot move a folder into itself.', 'warning');
                    draggedItem = null; // Clear dragged item
                    return;
                }

                // Also prevent dropping a parent folder into one of its direct children (more complex check, usually done on server)
                // For now, assume server will handle deeper invalid moves.

                // Filter out items that are already in the target folder
                const itemsAlreadyInTarget = itemsToMove.filter(item => {
                    const currentRow = document.querySelector(`.fl-item-row[data-item-id="${item.id}"][data-item-type="${item.type}"]`);
                    // This checks the current parent of the dragged item against the target folder.
                    // Assuming your item rows have a way to identify their current parent, e.g., a data attribute on the row itself
                    // You would need to add something like data-current-parent-id="{{ item.parent_folder_id }}" to your file/folder rows.
                    // For simplicity, we'll let the server handle this check more definitively.
                    return false; // Skip client-side check for now, let server handle it.
                });

                if (itemsAlreadyInTarget.length === itemsToMove.length && itemsAlreadyInTarget.length > 0) {
                    if (typeof showToast === 'function') showToast('All selected items are already in this folder.', 'info');
                    draggedItem = null;
                    return;
                }

                // Confirm move operation
                const confirmMessage = `Move ${itemsToMove.length} item(s) to folder '${targetFolderName}'?`;
                if (confirm(confirmMessage)) {
                    handleMoveItems(itemsToMove, targetFolderId);
                }
            } else {
                if (typeof showToast === 'function') showToast('Drop target must be a folder.', 'warning');
            }
            draggedItem = null; // Clear dragged item after drop attempt
        });
    }

    // New function to handle the actual move operation
    function handleMoveItems(items, targetFolderId) {
        if (!csrfToken) {
            if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger');
            return;
        }

        if (typeof showToast === 'function') showToast(`Moving ${items.length} item(s)...`, 'info', 3000);

        fetch(`/files/api/move`, { // New API endpoint for moving items
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ items: items, target_folder_id: targetFolderId })
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || 'Items moved successfully! Reloading...', 'success');
                // Reload the page to reflect changes
                setTimeout(() => { location.reload(); }, 1500);
            } else {
                let errorMsg = data.message || 'Failed to move items.';
                if (data.errors && Array.isArray(data.errors) && data.errors.length > 0) {
                    errorMsg = `Move failed for some items: ${data.errors.join(', ')}`;
                }
                if (typeof showToast === 'function') showToast(errorMsg, 'warning');
            }
        })
        .catch(error => {
            console.error('Error during move operation:', error);
            if (typeof showToast === 'function') showToast(`Move Error: ${error.message}`, 'danger');
        });
    }


    if (pasteButton) {
        pasteButton.addEventListener('click', handlePaste);
    }

    if (btnDeleteSelected) {
        btnDeleteSelected.addEventListener('click', function() {
            const selectedItems = getSelectedItems();
            if (selectedItems.length === 0) {
                if (typeof showToast === 'function') showToast('No items selected for deletion.', 'info');
                return;
            }
            const confirmMessage = `Are you sure you want to delete ${selectedItems.length} selected item(s)? This action cannot be undone.`;
            if (confirm(confirmMessage)) {
                if (!csrfToken) { if (typeof showToast === 'function') showToast('Error: Missing security token.', 'danger'); return; }

                const deletePromises = selectedItems.map(item =>
                fetch(`/${item.type === 'folder' ? 'files/folder/delete' : 'files/delete'}/${item.id}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken }
                })
                .then(handleFetchErrors)
                .then(data => {
                    if (data.status === 'success') {
                        const rowToRemove = fileTable.querySelector(`.fl-item-row[data-item-id="${item.id}"][data-item-type="${item.type}"]`);
                        if (rowToRemove) {
                            const index = itemRows.findIndex(r => r === rowToRemove);
                            if (index > -1) itemRows.splice(index, 1);
                            rowToRemove.remove();
                        }
                        if (item.type === 'file') {
                            const shareRow = document.getElementById(`fl-share-link-row-${item.id}`);
                            if (shareRow) shareRow.remove();
                        }
                        return { success: true, item: item.name };
                    } else {
                        throw new Error(data.message || `Failed to delete ${item.name}`);
                    }
                })
                .catch(error => {
                    console.error(`Error deleting ${item.name}:`, error);
                    return { success: false, item: item.name, error: error.message };
                })
                );

                Promise.allSettled(deletePromises).then(results => {
                    const successfulDeletes = results.filter(r => r.status === 'fulfilled' && r.value.success).length;
                    const failedDeletes = results.length - successfulDeletes;
                    let toastMessage = '';
                    let toastType = 'success';

                    if (successfulDeletes > 0 && failedDeletes === 0) {
                        toastMessage = `${successfulDeletes} item(s) deleted successfully!`;
                    } else if (successfulDeletes > 0 && failedDeletes > 0) {
                        toastMessage = `${successfulDeletes} item(s) deleted, but ${failedDeletes} failed. Check console for details.`;
                        toastType = 'warning';
                    } else if (failedDeletes > 0) {
                        toastMessage = `Failed to delete ${failedDeletes > 1 ? 'items' : 'item'}. Check console for details.`;
                        toastType = 'danger';
                    } else {
                        toastMessage = `Delete operation completed. No items were deleted.`;
                        toastType = 'info';
                    }

                    if (typeof showToast === 'function') showToast(toastMessage, toastType);
                    updateSelectAllCheckboxState();
                    updateMultiSelectActionsVisibility();
                });
            }
        });
    }

    if (btnCutSelected) {
        btnCutSelected.addEventListener('click', function() {
            const selectedItems = getSelectedItems();
            if (selectedItems.length > 0) {
                setClipboard(selectedItems, 'cut');
            } else {
                if (typeof showToast === 'function') showToast('No items selected to cut.', 'info');
            }
        });
    }

    if (btnCopySelected) {
        btnCopySelected.addEventListener('click', function() {
            const selectedItems = getSelectedItems();
            if (selectedItems.length > 0) {
                setClipboard(selectedItems, 'copy');
            } else {
                if (typeof showToast === 'function') showToast('No items selected to copy.', 'info');
            }
        });
    }

    // Event Listeners for new action buttons
    if (btnArchiveSelected) {
        btnArchiveSelected.addEventListener('click', function() {
            const selectedItems = getSelectedItems();
            const foldersToArchive = selectedItems.filter(item => item.type === 'folder');

            if (foldersToArchive.length === 0) {
                if (typeof showToast === 'function') showToast('Please select one or more folders to archive.', 'warning');
                return;
            }

            if (confirm(`Archive ${foldersToArchive.length} selected folder(s)? This might take a while.`)) {
                if (typeof showToast === 'function') showToast(`Archiving ${foldersToArchive.length} folder(s)...`, 'info', 5000);
                const archivePromises = foldersToArchive.map(folder =>
                fetch(`/files/folder/archive/${folder.id}`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json' }
                })
                .then(handleFetchErrors)
                .then(data => {
                    if (data.status === 'success') {
                        return { success: true, item: folder.name };
                    } else {
                        throw new Error(data.message || `Failed to archive folder '${folder.name}'.`);
                    }
                })
                .catch(error => {
                    console.error(`Error archiving folder '${folder.name}':`, error);
                    return { success: false, item: folder.name, error: error.message };
                })
                );

                Promise.allSettled(archivePromises).then(results => {
                    const successfulArchives = results.filter(r => r.status === 'fulfilled' && r.value.success).length;
                    const failedArchives = results.length - successfulArchives;
                    let toastMessage = '';
                    let toastType = 'success';
                    let shouldReload = false;

                    if (successfulArchives > 0 && failedArchives === 0) {
                        toastMessage = `${successfulArchives} folder(s) archived successfully! Reloading...`;
                        shouldReload = true;
                    } else if (successfulArchives > 0 && failedArchives > 0) {
                        toastMessage = `${successfulArchives} folder(s) archived, but ${failedArchives} failed. Check console for details. Reloading...`;
                        toastType = 'warning';
                        shouldReload = true;
                    } else {
                        toastMessage = `Failed to archive any folders.`;
                        toastType = 'danger';
                    }
                    if (typeof showToast === 'function') showToast(toastMessage, toastType);
                    if (shouldReload) {
                        setTimeout(() => { location.reload(); }, 2000);
                    }
                });
            }
        });
    }

    if (btnUnarchiveSelected) {
        btnUnarchiveSelected.addEventListener('click', function() {
            const selectedItems = getSelectedItems();
            const archivesToUnarchive = selectedItems.filter(item => item.type === 'file' && ['zip', '7z', 'rar'].includes(item.fileExt));

            if (archivesToUnarchive.length === 0) {
                if (typeof showToast === 'function') showToast('Please select one or more archive files (.zip, .7z, .rar) to unarchive.', 'warning');
                return;
            }

            if (confirm(`Unarchive ${archivesToUnarchive.length} selected archive(s)? Existing files might be overwritten.`)) {
                if (typeof showToast === 'function') showToast(`Unarchiving ${archivesToUnarchive.length} archive(s)...`, 'info', 5000);
                const unarchivePromises = archivesToUnarchive.map(file =>
                fetch(`/files/extract/${file.id}`, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken, 'Accept': 'application/json' }
                })
                .then(handleFetchErrors)
                .then(data => {
                    if (data.status === 'success') {
                        return { success: true, item: file.name };
                    } else {
                        throw new Error(data.message || `Failed to unarchive '${file.name}'.`);
                    }
                })
                .catch(error => {
                    console.error(`Error unarchiving '${file.name}':`, error);
                    return { success: false, item: file.name, error: error.message };
                })
                );

                Promise.allSettled(unarchivePromises).then(results => {
                    const successfulUnarchives = results.filter(r => r.status === 'fulfilled' && r.value.success).length;
                    const failedUnarchives = results.length - successfulUnarchives;
                    let toastMessage = '';
                    let toastType = 'success';
                    let shouldReload = false;

                    if (successfulUnarchives > 0 && failedUnarchives === 0) {
                        toastMessage = `${successfulUnarchives} archive(s) unarchived successfully! Reloading...`;
                        shouldReload = true;
                    } else if (successfulUnarchives > 0 && failedUnarchives > 0) {
                        toastMessage = `${successfulUnarchives} archive(s) unarchived, but ${failedUnarchives} failed. Check console for details. Reloading...`;
                        toastType = 'warning';
                        shouldReload = true;
                    } else {
                        toastMessage = `Failed to unarchive any items.`;
                        toastType = 'danger';
                    }
                    if (typeof showToast === 'function') showToast(toastMessage, toastType);
                    if (shouldReload) {
                        setTimeout(() => { location.reload(); }, 2000);
                    }
                });
            }
        });
    }

    if (btnEditSelected) {
        btnEditSelected.addEventListener('click', function() {
            const selectedItems = getSelectedItems();
            if (selectedItems.length !== 1 || selectedItems[0].type !== 'file' || !selectedItems[0].isEditable) {
                if (typeof showToast === 'function') showToast('Please select a single editable text file to edit.', 'warning');
                return;
            }
            window.location.href = `/files/edit/${selectedItems[0].id}`;
        });
    }

    if (btnDownloadSelected) {
        btnDownloadSelected.addEventListener('click', function() {
            const filesToDownload = getSelectedItems().filter(item => item.type === 'file');

            if (filesToDownload.length > 0) {
                if (confirm(`Download ${filesToDownload.length} selected file(s)?`)) {
                    filesToDownload.forEach(file => {
                        const downloadUrl = `${downloadFileBaseUrl}${file.id}`;
                        const a = document.createElement('a');
                        a.href = downloadUrl;
                        a.download = file.name;
                        a.style.display = 'none';
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    });
                    if (typeof showToast === 'function') showToast(`${filesToDownload.length} file(s) are downloading.`, 'info');
                }
            } else {
                if (typeof showToast === 'function') showToast('No files selected for download.', 'warning');
            }
        });
    }

    // Initial UI updates on page load
    updatePasteButtonVisibility();
    updateCutItemVisuals();
    updateSelectAllCheckboxState();
    updateMultiSelectActionsVisibility();

    itemRows.forEach(row => {
        if (row.dataset.itemType === 'file') {
            const fileId = row.dataset.itemId;
            const isPublic = row.dataset.isPublic === 'true';
            const shareUrl = row.dataset.shareUrl;
            const isPasswordProtected = row.dataset.isPasswordProtected === 'true';
            if (isPublic && shareUrl) {
                updateShareUI(fileId, true, shareUrl, isPasswordProtected);
            }
        }
    });

}); // End DOMContentLoaded
