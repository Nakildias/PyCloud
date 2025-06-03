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
    // e.g., const CSRF_TOKEN = "...";


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
        if (isNaN(numericPercent)) return 'low'; // Default if parsing fails
        if (numericPercent < 60) return 'low';
        if (numericPercent < 85) return 'medium';
        return 'high';
    }

    function updateText(elementId, text) {
        const el = document.getElementById(elementId);
        if (el && el.textContent !== text) { // Only update if text is different
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
            if (Math.abs(currentWidth - numPercent) > 0.1) { // Update if significantly different
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
        const uptime7d = get(['uptime_percentage_last_7_days'], serverData);
        updateText(`uptime7d-${serverId}`, uptime7d !== 'N/A' ? uptime7d : 'N/A');

        const cpuUsagePercent = get(['cpu_usage_percent'], serverData);
        updateProgressBar(`cpu-bar-${serverId}`, `cpu-value-${serverId}`, cpuUsagePercent !== 'N/A' ? cpuUsagePercent : 'N/A', cpuUsagePercent);

        const ramTotalGb = parseFloat(get(['ram_usage', 'total_gb'], serverData));
        const ramAvailableGb = parseFloat(get(['ram_usage', 'available_gb'], serverData));
        let ramUsedGbStr = 'N/A';
        if (!isNaN(ramTotalGb) && !isNaN(ramAvailableGb)) {
            ramUsedGbStr = (ramTotalGb - ramAvailableGb).toFixed(2);
        }
        const ramPercentUsed = get(['ram_usage', 'percent_used'], serverData);
        const ramText = `${ramUsedGbStr} GB / ${!isNaN(ramTotalGb) ? ramTotalGb.toFixed(2) : 'N/A'} GB (${ramPercentUsed !== 'N/A' ? ramPercentUsed : 'N/A'})`;
        updateProgressBar(`ram-bar-${serverId}`, `ram-value-${serverId}`, ramText, ramPercentUsed);

        const diskData = get(['disk_usage_root'], serverData);
        const diskTotalGb = parseFloat(get(['total_gb'], diskData));
        const diskUsedGb = parseFloat(get(['used_gb'], diskData));
        const diskPercentUsed = get(['percent_used'], diskData);
        const diskText = `${!isNaN(diskUsedGb) ? diskUsedGb.toFixed(2) : 'N/A'} GB / ${!isNaN(diskTotalGb) ? diskTotalGb.toFixed(2) : 'N/A'} GB (${diskPercentUsed !== 'N/A' ? diskPercentUsed : 'N/A'})`;
        updateProgressBar(`disk-bar-${serverId}`, `disk-value-${serverId}`, diskText, diskPercentUsed);
    }

    function fetchDataForServer(serverId) {
        const statusEl = document.getElementById(`status-${serverId}`);
        const cardBodyEl = document.getElementById(`data-${serverId}`);

        // Only apply visual loading cue to the card body
        if (cardBodyEl) {
            cardBodyEl.classList.add('loading');
        }
        // Do NOT change statusEl text or class during the fetch initiation

        const fetchUrl = `${MONITOR_FETCH_URL_BASE}${serverId}`;

        fetch(fetchUrl)
        .then(response => response.json())
        .then(result => {
            if (cardBodyEl) cardBodyEl.classList.remove('loading'); // Remove loading cue from body

            if (result.error) {
                if (statusEl) {
                    statusEl.textContent = 'Error'; // Set text to Error
                    statusEl.className = 'monitor-server-status status-error'; // Set class for error color
                }
                // Handle error display in card body
                const errorDisplayId = `error-display-${serverId}`;
                let errorDisplayEl = document.getElementById(errorDisplayId);
                if (!errorDisplayEl && cardBodyEl) {
                    const pHost = cardBodyEl.querySelector('p');
                    let tempErrorContainer = document.createElement('div');
                    if(pHost) tempErrorContainer.appendChild(pHost.cloneNode(true));
                    errorDisplayEl = document.createElement('pre');
                    errorDisplayEl.id = errorDisplayId;
                    errorDisplayEl.style.color = 'var(--danger-color-text, red)';
                    errorDisplayEl.style.marginTop = '10px';
                    tempErrorContainer.appendChild(errorDisplayEl);
                    cardBodyEl.innerHTML = tempErrorContainer.innerHTML; // Replace body with host + error
                    // Ensure the error text is set on the newly created element
                    document.getElementById(errorDisplayId).textContent = `Error: ${result.error}`;
                } else if (errorDisplayEl) {
                    errorDisplayEl.textContent = `Error: ${result.error}`;
                }
            } else {
                if (statusEl) {
                    statusEl.textContent = 'Online'; // Set text to Online
                    statusEl.className = 'monitor-server-status status-ok'; // Set class for online color
                }
                // Remove any previous error message display
                const errorDisplayEl = document.getElementById(`error-display-${serverId}`);
                if (errorDisplayEl) errorDisplayEl.remove();

                // Ensure the grid structure is present if it was wiped by a previous error
                if (!cardBodyEl.querySelector('.server-info-grid')) {
                    const pHost = cardBodyEl.querySelector('p'); // Try to preserve host info if it exists
                    cardBodyEl.innerHTML = ''; // Clear potentially error-filled content
                    if(pHost) cardBodyEl.appendChild(pHost.cloneNode(true)); // Re-add host info
                    // Re-add the grid structure for data display
                    cardBodyEl.insertAdjacentHTML('beforeend', `
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
                    `);
                }
                formatServerData(serverId, result.data); // Populate with new data
            }
        })
        .catch(error => {
            if (cardBodyEl) cardBodyEl.classList.remove('loading'); // Remove loading cue
            console.error('Fetch error for server ' + serverId + ':', error);
            if (statusEl) {
                statusEl.textContent = 'Fetch Error'; // Set text to Fetch Error
                statusEl.className = 'monitor-server-status status-error'; // Set class for error color
            }
            // Handle error display in card body for catch block
            const errorDisplayId = `error-display-${serverId}`;
            let errorDisplayEl = document.getElementById(errorDisplayId);
            if (!errorDisplayEl && cardBodyEl) {
                const pHost = cardBodyEl.querySelector('p');
                cardBodyEl.innerHTML = '';
                if(pHost) cardBodyEl.appendChild(pHost.cloneNode(true));
                errorDisplayEl = document.createElement('pre');
                errorDisplayEl.id = errorDisplayId;
                errorDisplayEl.style.color = 'var(--danger-color-text, red)';
                errorDisplayEl.style.marginTop = '10px';
                cardBodyEl.appendChild(errorDisplayEl);
            }
            if(errorDisplayEl) errorDisplayEl.textContent = 'Network error or backend unavailable.';
        });
    }

    serverCards.forEach(card => {
        const serverId = card.dataset.serverId;
        fetchDataForServer(serverId); // Initial fetch
        const intervalId = setInterval(() => fetchDataForServer(serverId), 1000);
        // card.dataset.intervalId = intervalId; // If you need to clear intervals later
    });

    if (serverGrid) {
        serverGrid.addEventListener('dragover', e => {
            e.preventDefault();
            const afterElement = getDragAfterElement(serverGrid, e.clientY);
            if (draggedItem) {
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
                'X-CSRFToken': typeof CSRF_TOKEN !== 'undefined' ? CSRF_TOKEN : ''
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
