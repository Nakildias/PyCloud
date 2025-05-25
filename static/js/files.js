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
    const dropZone = document.getElementById('fl-drop-zone');
    const uploadForm = document.getElementById('fl-upload-form');
    const parentFolderInput = document.getElementById('fl-upload-parent-folder-id');
    const currentFolderId = parentFolderInput ? parentFolderInput.value : null;
    const fileUploadInput = document.getElementById('fl-file-upload-input');

    const btnShowCreateFolder = document.getElementById('fl-btn-show-create-folder');
    const formCreateFolder = document.getElementById('fl-form-create-folder');
    const btnCancelCreateFolder = document.getElementById('fl-btn-cancel-create-folder');
    const inputFolderName = formCreateFolder ? formCreateFolder.querySelector('.fl-input-foldername') : null;

    const selectAllCheckbox = document.getElementById('fl-select-all-checkbox');
    // MODIFIED: itemRows now refers to all selectable item rows (folders and files)
    const itemRows = fileTable ? Array.from(fileTable.querySelectorAll('.fl-item-row')) : [];
    const multiSelectActionsContainer = document.getElementById('fl-multi-select-actions-toolbar');
    const btnDeleteSelected = document.getElementById('fl-btn-delete-selected');
    const btnCutSelected = document.getElementById('fl-btn-cut-selected');
    const btnCopySelected = document.getElementById('fl-btn-copy-selected');
    const btnArchiveSelected = document.getElementById('fl-btn-archive-selected');
    const btnUnarchiveSelected = document.getElementById('fl-btn-unarchive-selected');
    const btnEditSelected = document.getElementById('fl-btn-edit-selected');
    const btnDownloadSelected = document.getElementById('fl-btn-download-selected'); // Renamed variable for consistency
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
        fileTable.querySelectorAll('.fl-item-row').forEach(row => row.classList.remove('cut-item'));
        if (clipboardData && clipboardData.operation === 'cut' && clipboardData.items) {
            clipboardData.items.forEach(item => {
                const row = fileTable.querySelector(`.fl-item-row[data-item-id="${item.id}"][data-item-type="${item.type}"]`);
                if (row) {
                    row.classList.add('cut-item');
                }
            });
        }
    }

    // MODIFIED: getSelectedItems to work with .selected class on item rows
    function getSelectedItems() {
        return itemRows
        .filter(row => row.classList.contains('selected'))
        .map(row => {
            // IMPORTANT: Ensure data-is-editable and data-file-ext are present in your HTML <tr> elements
            // For example: <tr ... data-is-editable="{{ 'true' if file.is_editable else 'false' }}" data-file-ext="{{ file_ext }}">
            return {
                id: row.dataset.itemId,
                type: row.dataset.itemType,
                name: row.dataset.itemName,
                isEditable: row.dataset.isEditable === 'true',
                fileExt: row.dataset.fileExt || '' // Ensure fileExt is retrieved
            };
        });
    }

    function updateMultiSelectActionsVisibility() {
        if (multiSelectActionsContainer) {
            const selectedItems = getSelectedItems();
            multiSelectActionsContainer.style.display = selectedItems.length > 0 ? 'flex' : 'none';

            // Hide all conditional buttons initially
            if (btnArchiveSelected) btnArchiveSelected.style.display = 'none';
            if (btnUnarchiveSelected) btnUnarchiveSelected.style.display = 'none';
            if (btnEditSelected) btnEditSelected.style.display = 'none';
            if (btnDownloadSelected) btnDownloadSelected.style.display = 'none'; // Updated variable name

            if (selectedItems.length > 0) {
                const allFolders = selectedItems.every(item => item.type === 'folder');
                const allFiles = selectedItems.every(item => item.type === 'file');
                const allArchives = allFiles && selectedItems.every(item => ['zip', '7z', 'rar'].includes(item.fileExt));
                const singleEditableFile = selectedItems.length === 1 && selectedItems[0].type === 'file' && selectedItems[0].isEditable;

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

                // NEW: Show Download button if all selected are files (not folders)
                if (allFiles && selectedItems.length > 0) {
                    if (btnDownloadSelected) btnDownloadSelected.style.display = 'inline-block';
                }

            }
        }
    }

    // MODIFIED: updateSelectAllCheckboxState to work with .selected class on item rows
    function updateSelectAllCheckboxState() {
        if (!selectAllCheckbox || itemRows.length === 0) return; // Use itemRows instead of itemCheckboxes
        const selectedCount = getSelectedItems().length;
        if (selectedCount === 0) {
            selectAllCheckbox.checked = false;
            selectAllCheckbox.indeterminate = false;
        } else if (selectedCount === itemRows.length) { // Use itemRows instead of itemCheckboxes
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
                const errorMsg = firstErrorResult ? (firstErrorResult.reason ? firstErrorResult.reason.message : firstErrorResult.value.message) : 'Unknown error';
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
                setTimeout(() => { location.reload(); }, failedUploads > 0 ? 5000 : 2500);
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
                event.target.value = null;
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
        fetch(`/api/files/clipboard/set`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ items: itemsArray, operation: operation })
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                clipboardData = { items: itemsArray, operation: operation };
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

        fetch(`/api/files/clipboard/paste`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify({ target_folder_id: currentFolderId })
        })
        .then(handleFetchErrors)
        .then(data => {
            if (data.status === 'success') {
                if (typeof showToast === 'function') showToast(data.message || 'Paste successful! Reloading...', 'success');
                clipboardData = null;
                updatePasteButtonVisibility();
                updateCutItemVisuals();
                setTimeout(() => { location.reload(); }, 1500);
            } else {
                let errorMsg = data.message || 'Paste operation failed.';
                if (data.errors && Array.isArray(data.errors) && data.errors.length > 0) {
                    errorMsg = `Paste failed for some items: ${data.errors.join(', ')}`;
                }
                if (typeof showToast === 'function') showToast(errorMsg, 'warning');
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
            if(fileTable){
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
            saveNewName(itemType, id, newName, displayElement, row);
        } else if (!newName) {
            if (typeof showToast === 'function') showToast('Name cannot be empty.', 'warning');
            const displayElement = row.querySelector('.fl-itemname-display');
            const nameContainer = (itemType === 'folder' && displayElement) ? displayElement.querySelector('a') : displayElement;
            if(nameContainer) nameContainer.textContent = originalName;
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
            if (password === null) { if (typeof showToast === 'function') showToast('Share cancelled.', 'info'); return; }
        }
        const payload = {};
        if (password !== null && password !== "") { payload.password = password; }
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
        const linkRow = document.getElementById(`fl-share-link-row-${fileId}`);
        const linkDisplayDiv = linkRow ? linkRow.querySelector('.fl-share-link-display-area') : null;
        const row = document.querySelector(`.fl-item-row[data-item-id="${fileId}"][data-item-type="file"]`);

        if(row){ row.dataset.isPublic = isShared ? 'true' : 'false'; row.dataset.isPasswordProtected = passwordProtected ? 'true' : 'false'; row.dataset.shareUrl = shareUrl || ''; }

        if (linkDisplayDiv) linkDisplayDiv.innerHTML = '';
        if (linkRow) linkRow.style.display = 'none';

        if (isShared && linkRow && linkDisplayDiv && shareUrl) {
            const label = document.createElement('label');
            label.htmlFor = `fl-share-url-${fileId}`;
            label.classList.add('fl-share-link-label');
            label.innerHTML = 'Link ' + (passwordProtected ? '&#128274;' : '') + ':';

            const input = document.createElement('input');
            input.type = 'text'; input.readOnly = true; input.value = shareUrl;
            input.id = `fl-share-url-${fileId}`;
            input.className = 'form-control-sm fl-share-link-input';
            input.title = 'Public share link';
            input.setAttribute('aria-label', 'Share Link');

            const copyBtn = document.createElement('button');
            copyBtn.className = 'btn btn-sm fl-btn-copy-share-link';
            copyBtn.dataset.link = shareUrl;
            copyBtn.textContent = 'Copy';

            linkDisplayDiv.appendChild(label);
            linkDisplayDiv.appendChild(input);
            linkDisplayDiv.appendChild(copyBtn);
            linkRow.style.display = '';
        }
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
                if (rowToRemove) rowToRemove.remove();
                const shareRow = document.getElementById(`fl-share-link-row-${fileId}`);
                if(shareRow) shareRow.remove();
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
                if (rowToRemove) rowToRemove.remove();
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

            fileViewerImage.style.display = 'none'; fileViewerImage.src = '';
            fileViewerVideo.style.display = 'none'; fileViewerVideo.src = '';
            fileViewerAudio.style.display = 'none'; fileViewerAudio.src = '';
            fileViewerIframe.style.display = 'none'; fileViewerIframe.src = 'about:blank';
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
                    if(unsupportedFilename) unsupportedFilename.textContent = `File: ${filename}`;
                    if(unsupportedDownloadLink && originalFileIdForDownload) {
                        unsupportedDownloadLink.href = `/files/download/${originalFileIdForDownload}`;
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
            itemRows.forEach(row => { // Iterate through itemRows
                if (selectAllCheckbox.checked) {
                    row.classList.add('selected');
                } else {
                    row.classList.remove('selected');
                }
            });
            updateSelectAllCheckboxState();
            updateMultiSelectActionsVisibility();
        });
    }

    // NEW: Click listener for selecting/deselecting individual file boxes
    if (fileTable && fileTable.querySelector('tbody')) {
        const tableBody = fileTable.querySelector('tbody');

        tableBody.addEventListener('click', function(event) {
            const target = event.target;
            const clickedRow = target.closest('.fl-item-row');

            if (clickedRow) {
                // Prevent selection toggle if clicking directly on a link or input within the row
                if (target.tagName === 'A' || target.tagName === 'INPUT' || target.closest('a') || target.closest('input')) {
                    // If it's a viewable link, let its default behavior happen (opening modal/new page)
                    const viewableLink = target.classList.contains('fl-viewable-file-link') ? target : target.closest('.fl-viewable-file-link');
                    if (viewableLink) {
                        event.preventDefault(); // Prevent default link behavior to handle modal
                        const fileUrl = viewableLink.href;
                        const filename = viewableLink.dataset.filename || viewableLink.textContent || 'File';
                        const fileId = clickedRow.dataset.itemId;
                        openFileViewerModal(fileUrl, filename, fileId);
                        return; // Exit after handling viewable link click
                    }
                    // For other links/inputs (like rename input, copy link button), don't toggle selection
                    return;
                }

                // Toggle 'selected' class on the clicked row
                clickedRow.classList.toggle('selected');
                updateSelectAllCheckboxState();
                updateMultiSelectActionsVisibility();
            }

            const isCopyLinkButton = target.classList.contains('fl-btn-copy-share-link');
            if (isCopyLinkButton) {
                copyToClipboard(target.dataset.link);
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

                // Track promises for all deletions
                const deletePromises = selectedItems.map(item =>
                fetch(`/${item.type === 'folder' ? 'files/folder/delete' : 'files/delete'}/${item.id}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json', 'X-CSRFToken': csrfToken }
                })
                .then(handleFetchErrors)
                .then(data => {
                    if (data.status === 'success') {
                        const rowToRemove = fileTable.querySelector(`.fl-item-row[data-item-id="${item.id}"][data-item-type="${item.type}"]`);
                        if (rowToRemove) rowToRemove.remove();
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
                    } else {
                        toastMessage = `Failed to delete any items.`;
                        toastType = 'danger';
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

                    if (successfulArchives > 0 && failedArchives === 0) {
                        toastMessage = `${successfulArchives} folder(s) archived successfully! Reloading...`;
                    } else if (successfulArchives > 0 && failedArchives > 0) {
                        toastMessage = `${successfulArchives} folder(s) archived, but ${failedArchives} failed. Check console for details. Reloading...`;
                        toastType = 'warning';
                    } else {
                        toastMessage = `Failed to archive any folders.`;
                        toastType = 'danger';
                    }
                    if (typeof showToast === 'function') showToast(toastMessage, toastType);
                    setTimeout(() => { location.reload(); }, 1500); // Reload after all attempts
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

                    if (successfulUnarchives > 0 && failedUnarchives === 0) {
                        toastMessage = `${successfulUnarchives} archive(s) unarchived successfully! Reloading...`;
                    } else if (successfulUnarchives > 0 && failedUnarchives > 0) {
                        toastMessage = `${successfulUnarchives} archive(s) unarchived, but ${failedUnarchives} failed. Check console for details. Reloading...`;
                        toastType = 'warning';
                    } else {
                        toastMessage = `Failed to unarchive any items.`;
                        toastType = 'danger';
                    }
                    if (typeof showToast === 'function') showToast(toastMessage, toastType);
                    setTimeout(() => { location.reload(); }, 1500); // Reload after all attempts
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

    // NEW: Event listener for "Download Selected" button
    if (btnDownloadSelected) {
        btnDownloadSelected.addEventListener('click', function() {
            const filesToDownload = getSelectedItems().filter(item => item.type === 'file');

            if (filesToDownload.length > 0) {
                if (confirm(`Download ${filesToDownload.length} selected file(s)?`)) {
                    filesToDownload.forEach(file => {
                        // Use the base URL passed from Jinja and append the file ID
                        const downloadUrl = `${downloadFileBaseUrl}${file.id}`; // Correctly concatenates ID

                        // Create a temporary anchor tag to trigger download
                        const a = document.createElement('a');
                        a.href = downloadUrl;
                        a.download = file.name; // Use the original filename
                        a.style.display = 'none';
                        document.body.appendChild(a);
                        a.click();
                        document.body.removeChild(a);
                    });
                    showToast(`${filesToDownload.length} file(s) are downloading.`, 'info');
                }
            } else {
                showToast('No files selected for download.', 'warning');
            }
        });
    }

    updatePasteButtonVisibility();
    updateCutItemVisuals();
    updateSelectAllCheckboxState();
    updateMultiSelectActionsVisibility();

}); // End DOMContentLoaded
