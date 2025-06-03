// app/static/js/monitor.js
document.addEventListener('DOMContentLoaded', function () {
    const serverCards = document.querySelectorAll('.monitor-server-card');
    const serverGrid = document.getElementById('monitorServerGrid');
    let draggedItem = null;

    // Modal elements
    const addServerModal = document.getElementById('addServerModal');
    const openModalBtn = document.getElementById('openAddServerModalBtn');
    const closeModalBtn = document.getElementById('closeAddServerModalBtn');
    const cancelModalBtn = document.getElementById('cancelAddServerModalBtn');

    // URLs are expected to be defined globally in the HTML template
    // e.g., const MONITOR_FETCH_URL_BASE = "...";
    // e.g., const MONITOR_REORDER_URL = "...";
    // e.g., const MONITOR_REBOOT_URL_BASE = "...";
    // e.g., const MONITOR_UPDATE_URL_BASE = "...";
    // CSRF_TOKEN should be available globally if your Flask-WTF setup provides it, or handle as needed.


    // Modal event listeners
    if (openModalBtn && addServerModal) {
        openModalBtn.onclick = function() {
            addServerModal.style.display = "block";
        }
    }
    if (closeModalBtn && addServerModal) {
        closeModalBtn.onclick = function() {
            addServerModal.style.display = "none";
        }
    }
    if (cancelModalBtn && addServerModal) {
        cancelModalBtn.onclick = function() {
            addServerModal.style.display = "none";
        }
    }
    if (addServerModal) {
        window.onclick = function(event) {
            if (event.target == addServerModal) {
                addServerModal.style.display = "none";
            }
        }
    }


    function getProgressBarClass(percentage) {
        const numericPercent = parseFloat(percentage);
        if (isNaN(numericPercent)) return 'low';
        if (numericPercent < 60) return 'low';
        if (numericPercent < 85) return 'medium';
        return 'high';
    }

    function updateText(elementId, text) {
        const el = document.getElementById(elementId);
        if (el && el.textContent !== text) {
            el.textContent = text;
        }
    }

    function updateProgressBar(barId, valueId, percentageText, numericPercentage) {
        const bar = document.getElementById(barId);
        const valueEl = document.getElementById(valueId);
        const numPercent = parseFloat(numericPercentage) || 0;

        if (valueEl && valueEl.textContent !== percentageText) {
            valueEl.textContent = percentageText;
        }
        if (bar) {
            const currentWidth = parseFloat(bar.style.width) || 0;
            if (Math.abs(currentWidth - numPercent) > 0.1) {
                bar.style.width = numPercent + '%';
            }
            const newClass = getProgressBarClass(numPercent);
            let classes = ['progress-bar'];
            if (newClass) classes.push(newClass);

            let needsUpdate = bar.classList.length !== classes.length;
            if (!needsUpdate) {
                for(let cls of classes) {
                    if (!bar.classList.contains(cls)) {
                        needsUpdate = true;
                        break;
                    }
                }
            }
            if(needsUpdate) {
                bar.className = classes.join(' ');
            }
        }
    }

    function formatServerData(serverId, serverData) {
        const get = (p, o) => p.reduce((xs, x) => (xs && xs[x] != null) ? xs[x] : 'N/A', o);

        updateText(`distro-${serverId}`, get(['distro_name'], serverData));
        updateText(`kernel-${serverId}`, get(['kernel_version'], serverData));
        updateText(`uptime-${serverId}`, get(['uptime_string'], serverData));
        const uptime7d = get(['uptime_percentage_last_7_days'], serverData); // Already a string with '%'
        updateText(`uptime7d-${serverId}`, uptime7d !== 'N/A' ? uptime7d : 'N/A');

        const cpuUsagePercent = get(['cpu_usage_percent'], serverData); // Already a string with '%'
        updateProgressBar(`cpu-bar-${serverId}`, `cpu-value-${serverId}`, cpuUsagePercent !== 'N/A' ? cpuUsagePercent : 'N/A', parseFloat(cpuUsagePercent));

        const ramTotalGb = parseFloat(get(['ram_usage', 'total_gb'], serverData));
        const ramAvailableGb = parseFloat(get(['ram_usage', 'available_gb'], serverData));
        let ramUsedGbStr = 'N/A';
        if (!isNaN(ramTotalGb) && !isNaN(ramAvailableGb)) {
            ramUsedGbStr = (ramTotalGb - ramAvailableGb).toFixed(2);
        }
        const ramPercentUsed = get(['ram_usage', 'percent_used'], serverData); // Already a string with '%'
        const ramText = `${ramUsedGbStr} GB / ${!isNaN(ramTotalGb) ? ramTotalGb.toFixed(2) : 'N/A'} GB (${ramPercentUsed !== 'N/A' ? ramPercentUsed : 'N/A'})`;
        updateProgressBar(`ram-bar-${serverId}`, `ram-value-${serverId}`, ramText, parseFloat(ramPercentUsed));

        const diskData = get(['disk_usage_root'], serverData);
        const diskTotalGb = parseFloat(get(['total_gb'], diskData));
        const diskUsedGb = parseFloat(get(['used_gb'], diskData));
        const diskPercentUsed = get(['percent_used'], diskData); // Already a string with '%'
        const diskText = `${!isNaN(diskUsedGb) ? diskUsedGb.toFixed(2) : 'N/A'} GB / ${!isNaN(diskTotalGb) ? diskTotalGb.toFixed(2) : 'N/A'} GB (${diskPercentUsed !== 'N/A' ? diskPercentUsed : 'N/A'})`;
        updateProgressBar(`disk-bar-${serverId}`, `disk-value-${serverId}`, diskText, parseFloat(diskPercentUsed));
    }

    function fetchDataForServer(serverId) {
        const statusEl = document.getElementById(`status-${serverId}`);
        const cardBodyEl = document.getElementById(`data-${serverId}`);
        const actionOutputEl = document.getElementById(`action-output-${serverId}`);

        if (cardBodyEl) {
            cardBodyEl.classList.add('loading');
        }
        if(actionOutputEl) actionOutputEl.style.display = 'none'; // Hide previous action output


        const fetchUrl = `${MONITOR_FETCH_URL_BASE}${serverId}`;

        fetch(fetchUrl)
        .then(response => response.json())
        .then(result => {
            if (cardBodyEl) cardBodyEl.classList.remove('loading');

            if (result.error) {
                if (statusEl) {
                    statusEl.textContent = 'Error';
                    statusEl.className = 'monitor-server-status status-error';
                }
                const errorDisplayId = `error-display-${serverId}`;
                let errorDisplayEl = document.getElementById(errorDisplayId);
                if (!errorDisplayEl && cardBodyEl) {
                    // Preserve host info if possible, or just clear and show error
                    cardBodyEl.innerHTML = `<pre id="${errorDisplayId}" style="color: var(--danger-color-text, red); margin-top: 10px;"></pre>`;
                    document.getElementById(errorDisplayId).textContent = `Error: ${result.error}`;
                } else if (errorDisplayEl) {
                    errorDisplayEl.textContent = `Error: ${result.error}`;
                }
            } else {
                if (statusEl) {
                    statusEl.textContent = 'Online';
                    statusEl.className = 'monitor-server-status status-ok';
                }
                const errorDisplayEl = document.getElementById(`error-display-${serverId}`);
                if (errorDisplayEl) errorDisplayEl.remove();

                if (!cardBodyEl.querySelector('.server-info-grid')) {
                    cardBodyEl.innerHTML = `
                    <div class="server-info-grid">
                    <div class="info-item"><span class="info-label">Distro:</span> <span class="info-value" id="distro-${serverId}">N/A</span></div>
                    <div class="info-item"><span class="info-label">Kernel:</span> <span class="info-value" id="kernel-${serverId}">N/A</span></div>
                    <div class="info-item"><span class="info-label">Uptime:</span> <span class="info-value" id="uptime-${serverId}">N/A</span></div>
                    <div class="info-item"><span class="info-label">Uptime (7d):</span> <span class="info-value" id="uptime7d-${serverId}">N/A</span></div>
                    <div class="info-item progress-section">
                    <span class="info-label">CPU:</span> <span class="info-value" id="cpu-value-${serverId}">N/A</span>
                    <div class="progress-bar-container"><div class="progress-bar" id="cpu-bar-${serverId}" style="width: 0%;"></div></div>
                    </div>
                    <div class="info-item progress-section">
                    <span class="info-label">RAM:</span> <span class="info-value" id="ram-value-${serverId}">N/A</span>
                    <div class="progress-bar-container"><div class="progress-bar" id="ram-bar-${serverId}" style="width: 0%;"></div></div>
                    </div>
                    <div class="info-item progress-section">
                    <span class="info-label">Disk (/):</span> <span class="info-value" id="disk-value-${serverId}">N/A</span>
                    <div class="progress-bar-container"><div class="progress-bar" id="disk-bar-${serverId}" style="width: 0%;"></div></div>
                    </div>
                    </div>
                    <div class="monitor-action-output" id="action-output-${serverId}" style="display:none; margin-top: 10px; white-space: pre-wrap; background-color: #282c34; color: #abb2bf; padding: 10px; border-radius: 4px; max-height: 200px; overflow-y: auto;"></div>`;
                }
                formatServerData(serverId, result.data);
            }
        })
        .catch(error => {
            if (cardBodyEl) cardBodyEl.classList.remove('loading');
            console.error('Fetch error for server ' + serverId + ':', error);
            if (statusEl) {
                statusEl.textContent = 'Fetch Err';
                statusEl.className = 'monitor-server-status status-error';
            }
            const errorDisplayId = `error-display-${serverId}`;
            let errorDisplayEl = document.getElementById(errorDisplayId);
            if (!errorDisplayEl && cardBodyEl) {
                cardBodyEl.innerHTML = `<pre id="${errorDisplayId}" style="color: var(--danger-color-text, red); margin-top: 10px;"></pre>`;
                document.getElementById(errorDisplayId).textContent = 'Network error or backend unavailable.';
            } else if(errorDisplayEl) {
                errorDisplayEl.textContent = 'Network error or backend unavailable.';
            }
        });
    }

    serverCards.forEach(card => {
        const serverId = card.dataset.serverId;
        fetchDataForServer(serverId);
        const intervalId = setInterval(() => fetchDataForServer(serverId), 500); // Fetch every 30 seconds
        card.dataset.intervalId = intervalId;
    });

    function handleServerAction(action, serverId, serverName) {
        let url;
        let confirmMessage = `Are you sure you want to ${action} server '${serverName}'?`;
        if (action === 'reboot') {
            url = `${MONITOR_REBOOT_URL_BASE}${serverId}`;
        } else if (action === 'update') {
            url = `${MONITOR_UPDATE_URL_BASE}${serverId}`;
            confirmMessage = `Are you sure you want to ${action} server '${serverName}'? This may take a while.`;
        } else {
            console.error("Unknown action:", action);
            return;
        }

        if (!confirm(confirmMessage)) {
            return;
        }

        const actionButton = document.querySelector(`.monitor-action-btn[data-action="${action}"][data-server-id="${serverId}"]`);
        const originalButtonText = actionButton.innerHTML;
        actionButton.disabled = true;

        let loadingActionText = action.charAt(0).toUpperCase() + action.slice(1);
        if (action === 'update') {
            loadingActionText = loadingActionText.slice(0, -1); // Removes 'e' from "Update" to make "Updat"
        }
        actionButton.innerHTML = `<i class="fas fa-spinner fa-spin"></i> ${loadingActionText}ing...`;

        const actionOutputEl = document.getElementById(`action-output-${serverId}`);
        if (actionOutputEl) {
            actionOutputEl.textContent = `Performing ${action}...`;
            actionOutputEl.style.display = 'block';
            actionOutputEl.style.color = 'var(--text-color)'; // Neutral color while processing
        }


        fetch(url, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': typeof CSRF_TOKEN !== 'undefined' ? CSRF_TOKEN : document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || ''
            },
        })
        .then(response => response.json())
        .then(data => {
            actionButton.disabled = false;
            actionButton.innerHTML = originalButtonText;
            if (typeof showToast === 'function') {
                showToast(data.message || `${action} request processed.`, data.success ? 'success' : 'error');
            } else {
                alert(data.message || `${action} request processed.`);
            }

            if (actionOutputEl) {
                let outputContent = `Action: ${action}\nStatus: ${data.success ? 'Success' : 'Failed'}\nMessage: ${data.message || 'N/A'}\n`;
                if (data.output) {
                    outputContent += `\n--- Output ---\n${data.output}`;
                }
                if (data.error_output) {
                    outputContent += `\n--- Errors ---\n${data.error_output}`;
                }
                actionOutputEl.textContent = outputContent;
                actionOutputEl.style.color = data.success ? 'var(--success-color-text, green)' : 'var(--danger-color-text, red)';
            }

            if (action === 'reboot' && data.success) {
                const statusEl = document.getElementById(`status-${serverId}`);
                if (statusEl) {
                    statusEl.textContent = 'Rebooting...';
                    statusEl.className = 'monitor-server-status status-warning';
                }
            }
        })
        .catch(error => {
            actionButton.disabled = false;
            actionButton.innerHTML = originalButtonText;
            console.error(`Error during ${action}:`, error);
            const errorMessage = `Network error or failed to send ${action} command.`;
            if (typeof showToast === 'function') {
                showToast(errorMessage, 'error');
            } else {
                alert(errorMessage);
            }
            if (actionOutputEl) {
                actionOutputEl.textContent = `Error during ${action}: ${error.message || 'Unknown network error'}`;
                actionOutputEl.style.color = 'var(--danger-color-text, red)';
            }
        });
    }

    document.querySelectorAll('.monitor-action-btn').forEach(button => {
        button.addEventListener('click', function() {
            const action = this.dataset.action;
            const serverId = this.dataset.serverId;
            const serverNameEl = document.getElementById(`name-${serverId}`);
            const serverName = serverNameEl ? serverNameEl.textContent : 'this server';
            handleServerAction(action, serverId, serverName);
        });
    });


    if (serverGrid) {
        serverGrid.addEventListener('dragstart', e => {
            if (e.target.classList.contains('monitor-server-card')) {
                draggedItem = e.target;
                setTimeout(() => {
                    // e.target.style.display = 'none'; // Hides the original item
                    e.target.style.opacity = '0.5'; // Or make it semi-transparent
                }, 0);
            }
        });

        serverGrid.addEventListener('dragend', e => {
            if (draggedItem && e.target.classList.contains('monitor-server-card')) {
                setTimeout(() => {
                    // e.target.style.display = ''; // Make it visible again
                    e.target.style.opacity = '1';
                    draggedItem = null;
                    saveOrder(); // Save order after drag ends
                }, 0);
            }
        });


        serverGrid.addEventListener('dragover', e => {
            e.preventDefault();
            const afterElement = getDragAfterElement(serverGrid, e.clientY);
            if (draggedItem) { // Ensure draggedItem is not null
                if (afterElement == null) {
                    serverGrid.appendChild(draggedItem);
                } else {
                    serverGrid.insertBefore(draggedItem, afterElement);
                }
            }
        });
    }

    function getDragAfterElement(container, y) {
        const draggableElements = [...container.querySelectorAll('.monitor-server-card:not([style*="opacity: 0.5"])')];
        return draggableElements.reduce((closest, child) => {
            const box = child.getBoundingClientRect();
            const offset = y - box.top - box.height / 2;
            if (offset < 0 && offset > closest.offset) {
                return { offset: offset, element: child };
            } else {
                return closest;
            }
        }, { offset: Number.NEGATIVE_INFINITY }).element;
    }

    function saveOrder() {
        if (!serverGrid) return;
        const orderedServerIds = [...serverGrid.querySelectorAll('.monitor-server-card')].map(card => card.dataset.serverId);

        fetch(MONITOR_REORDER_URL, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                // Use globally available CSRF_TOKEN or get from meta tag
                'X-CSRFToken': typeof CSRF_TOKEN !== 'undefined' ? CSRF_TOKEN : document.querySelector('meta[name="csrf-token"]')?.getAttribute('content') || ''
            },
            body: JSON.stringify({ order: orderedServerIds })
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                if (typeof showToast === 'function') {
                    showToast(data.message || 'Server order updated!', 'success');
                }
            } else {
                console.error('Failed to save order:', data.error);
                if (typeof showToast === 'function') {
                    showToast('Failed to save server order: ' + (data.error || 'Unknown error'), 'error');
                }
            }
        })
        .catch(error => {
            console.error('Error saving order:', error);
            if (typeof showToast === 'function') {
                showToast('Network error while saving server order.', 'error');
            }
        });
    }
});
