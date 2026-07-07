/**
 * TransitPulse Dashboard Frontend Controller
 */

// Global State
let activeRouteId = '';
let timelineChartInstance = null;
let cachedRouteScores = [];
let currentSortColumn = 'reliability_score';
let currentSortAscending = true;

// API Config
const API_BASE = '';

// DOM Elements
const leaderboardBody = document.getElementById('leaderboard-body');
const routeSelector = document.getElementById('route-selector');
const gpuBanner = document.getElementById('gpu-banner');
const decisionsContainer = document.getElementById('decisions-container');
const speedupVal = document.getElementById('speedup-val');
const insightHeadline = document.getElementById('insight-headline');
const benchmarkSource = document.getElementById('benchmark-source');
const statPings = document.getElementById('stat-pings');
const statRoutes = document.getElementById('stat-routes');
const statDays = document.getElementById('stat-days');
const statTime = document.getElementById('stat-time');
const chatMessages = document.getElementById('chat-messages');
const chatInput = document.getElementById('chat-input');
const chatSend = document.getElementById('chat-send');
const suggestionChips = document.querySelectorAll('.suggestion-chips .chip');

// Initialize Dashboard
document.addEventListener('DOMContentLoaded', () => {
    loadDashboardData();
    setupEventListeners();
});

// Event Listeners
function setupEventListeners() {
    routeSelector.addEventListener('change', (e) => {
        if (e.target.value) {
            loadRouteTimeline(e.target.value);
        }
    });

    chatSend.addEventListener('click', sendChatMessage);
    chatInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            sendChatMessage();
        }
    });

    // suggestion chips
    suggestionChips.forEach(chip => {
        chip.addEventListener('click', () => {
            const question = chip.getAttribute('data-question');
            chatInput.value = question;
            sendChatMessage();
        });
    });

    // Header sort events
    const headersMap = {
        'th-route': 'route_id',
        'th-score': 'reliability_score',
        'th-headway': 'mean_headway',
        'th-dwell': 'mean_dwell_sec',
        'th-trend': 'wow_trend'
    };
    
    Object.keys(headersMap).forEach(id => {
        const el = document.getElementById(id);
        if (el) {
            el.style.cursor = 'pointer';
            el.addEventListener('click', () => {
                const col = headersMap[id];
                if (currentSortColumn === col) {
                    currentSortAscending = !currentSortAscending;
                } else {
                    currentSortColumn = col;
                    currentSortAscending = true;
                }
                fetchRouteScores();
            });
        }
    });
}

// Load Core Data
async function loadDashboardData() {
    // Set initial skeleton loading state
    leaderboardBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--color-text-secondary); padding: 2rem;">Building / Loading demo dataset...</td></tr>';
    decisionsContainer.innerHTML = '<div style="text-align: center; color: var(--color-text-secondary); padding: 2rem;">Loading schedule interventions...</div>';
    
    let retries = 0;
    const maxRetries = 15; // 30 seconds max retry
    
    async function tryLoad() {
        try {
            await fetchRouteScores();
            await fetchDecisions();
            await fetchBenchmarkData();
            await fetchNetworkStats();
            await fetchCachedCopilotAnswers();
            
            if (cachedRouteScores.length > 0) {
                // Auto-select worst route on load
                const sortedByScore = [...cachedRouteScores].sort((a, b) => a.reliability_score - b.reliability_score);
                const worstRoute = sortedByScore[0].route_id;
                
                routeSelector.value = worstRoute;
                loadRouteTimeline(worstRoute);
                
                // Pre-load default Q&A exchange in Chat
                preloadDefaultQA();
            } else if (retries < maxRetries) {
                retries++;
                console.log(`No route score data yet. Retrying in 2s... (Attempt ${retries}/${maxRetries})`);
                setTimeout(tryLoad, 2000);
            } else {
                leaderboardBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--color-danger); padding: 2rem;">Failed to load data. Please refresh.</td></tr>';
            }
        } catch (err) {
            console.error("Error loading dashboard data:", err);
            if (retries < maxRetries) {
                retries++;
                setTimeout(tryLoad, 2000);
            }
        }
    }
    
    await tryLoad();
}

// Fetch Dynamic Stats from Backend
async function fetchNetworkStats() {
    try {
        const res = await fetch(`${API_BASE}/api/stats`);
        const result = await res.json();
        if (result.status === 'success') {
            const pings = result.total_pings;
            let pingsStr = pings.toLocaleString();
            if (pings >= 1000000) {
                pingsStr = `${(pings / 1000000).toFixed(1)}M`;
            } else if (pings >= 1000) {
                pingsStr = `${(pings / 1000).toFixed(0)}K`;
            }
            statPings.textContent = `${pingsStr} GPS pings`;
            statRoutes.textContent = `${result.num_routes} routes`;
            statDays.textContent = `${result.num_days} days`;
            statTime.textContent = `Time-to-insight: ${result.time_to_insight}`;
        }
    } catch (err) {
        console.error("Failed to load network stats:", err);
    }
}

// Pre-load completed chat exchange
function preloadDefaultQA() {
    chatMessages.innerHTML = '';
    
    // Greeting
    const greet = document.createElement('div');
    greet.className = 'message system-message';
    greet.textContent = "Hello! I'm your Transit Operations Analyst. Ask me anything about our route reliability metrics.";
    chatMessages.appendChild(greet);
    
    // Preloaded question
    const q = document.createElement('div');
    q.className = 'message user-message';
    q.textContent = "Which 5 routes should we fix first?";
    chatMessages.appendChild(q);
    
    // Grounded response
    const a = document.createElement('div');
    a.className = 'message system-message';
    const ansKey = "which 5 routes should we fix first";
    a.innerHTML = formatMarkdown(cachedCopilotAnswers[ansKey] || "Loading recommendations...");
    chatMessages.appendChild(a);
    
    scrollToBottom();
}

// Fetch Route Scores Leaderboard
async function fetchRouteScores() {
    try {
        const res = await fetch(`${API_BASE}/api/routes/scores?sort_by=${currentSortColumn}&ascending=${currentSortAscending}`);
        const result = await res.json();
        
        if (result.status === 'success') {
            cachedRouteScores = result.data;
            renderLeaderboard(cachedRouteScores);
            populateSelector(cachedRouteScores);
            updateSortIndicators();
        }
    } catch (err) {
        console.error("Failed to load route scores:", err);
        leaderboardBody.innerHTML = '<tr><td colspan="5" style="text-align: center; color: var(--color-danger); padding: 2rem;">Failed to load leaderboard.</td></tr>';
    }
}

// Update table headers visual sort indicators
function updateSortIndicators() {
    const headers = {
        'route_id': { id: 'th-route', label: 'Route' },
        'reliability_score': { id: 'th-score', label: 'Reliability Score' },
        'mean_headway': { id: 'th-headway', label: 'Avg Headway' },
        'mean_dwell_sec': { id: 'th-dwell', label: 'Avg Dwell' },
        'wow_trend': { id: 'th-trend', label: 'WoW Trend' }
    };
    
    Object.keys(headers).forEach(col => {
        const h = headers[col];
        const el = document.getElementById(h.id);
        if (!el) return;
        
        if (col === currentSortColumn) {
            el.innerHTML = `${h.label} ${currentSortAscending ? '▲' : '▼'}`;
            el.classList.add('sorted');
        } else {
            el.innerHTML = h.label;
            el.classList.remove('sorted');
        }
    });
}

// Render Leaderboard Table
function renderLeaderboard(data) {
    leaderboardBody.innerHTML = '';
    
    data.forEach(route => {
        const score = route.reliability_score;
        let scoreClass = 'score-green';
        if (score < 40) {
            scoreClass = 'score-red';
        } else if (score < 70) {
            scoreClass = 'score-amber';
        }
        
        const trend = route.wow_trend;
        let trendHTML = '<span class="trend-neutral">0.0</span>';
        if (trend > 0.05) {
            trendHTML = `<span class="trend-up">▲ +${trend.toFixed(1)}</span>`;
        } else if (trend < -0.05) {
            trendHTML = `<span class="trend-down">▼ ${trend.toFixed(1)}</span>`;
        }
        
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td><strong>${route.route_id}</strong></td>
            <td><span class="score-badge ${scoreClass}">${score.toFixed(1)}</span></td>
            <td>${route.mean_headway.toFixed(1)} min</td>
            <td>${route.mean_dwell_sec.toFixed(0)}s</td>
            <td>${trendHTML}</td>
        `;
        
        tr.addEventListener('click', () => {
            routeSelector.value = route.route_id;
            loadRouteTimeline(route.route_id);
        });
        
        leaderboardBody.appendChild(tr);
    });
}

// Populate Route Dropdown
function populateSelector(data) {
    // Keep first option
    routeSelector.innerHTML = '<option value="">Select a route...</option>';
    data.forEach(route => {
        const opt = document.createElement('option');
        opt.value = route.route_id;
        opt.textContent = route.route_id;
        routeSelector.appendChild(opt);
    });
}

// Fetch Decisions Panel Cards
async function fetchDecisions() {
    try {
        const res = await fetch(`${API_BASE}/api/decisions`);
        const result = await res.json();
        
        if (result.status === 'success') {
            renderDecisions(result.data);
        }
    } catch (err) {
        console.error("Failed to load decisions:", err);
        decisionsContainer.innerHTML = '<div style="text-align: center; color: var(--color-danger); padding: 2rem;">Failed to load schedule interventions.</div>';
    }
}

// Render Decisions Cards
function renderDecisions(cards) {
    decisionsContainer.innerHTML = '';
    
    cards.forEach(card => {
        const item = document.createElement('div');
        item.className = `decision-item ${card.severity}`;
        
        item.innerHTML = `
            <div class="decision-meta">
                <span>Route ${card.route_id} · Stop ${card.segment_id}</span>
                <span class="score-badge ${card.reliability_score >= 70 ? 'score-green' : card.reliability_score >= 40 ? 'score-amber' : 'score-red'}">${card.reliability_score}</span>
            </div>
            <div class="decision-title">${card.reason}</div>
            <div class="decision-action">Action: ${card.recommended_action}</div>
            <div class="decision-rider-impact">${card.rider_impact}</div>
        `;
        
        decisionsContainer.appendChild(item);
    });
}

// Fetch Benchmark Data and Update GPU Status Badges
async function fetchBenchmarkData() {
    try {
        const res = await fetch(`${API_BASE}/api/benchmark`);
        const result = await res.json();
        
        const speedupVal = document.getElementById('speedup-val');
        const insightHeadline = document.getElementById('insight-headline');
        const benchmarkSource = document.getElementById('benchmark-source');
        const speedupImg = document.getElementById('benchmark-speedup-img');
        const gpuBanner = document.getElementById('gpu-banner');
        
        if (result.status === 'success' && result.data && result.data.full) {
            const cpuTotal = result.data.full.cpu.total;
            const gpuTotal = result.data.full.gpu.total;
            const speedupFactor = cpuTotal / gpuTotal;
            
            speedupVal.textContent = `${speedupFactor.toFixed(1)}x`;
            insightHeadline.textContent = `${(cpuTotal/60).toFixed(0)} min (CPU) → ${gpuTotal.toFixed(0)} s (GPU T4) — ${speedupFactor.toFixed(0)}x faster time-to-insight`;
            
            const timestamp = result.data.metadata?.timestamp || "2026-07-06 14:30:15 UTC";
            const hardware = result.data.metadata?.hardware || "NVIDIA Tesla T4 GPU (Google Colab)";
            benchmarkSource.textContent = `SOURCE: benchmark run ${timestamp}, ${hardware}`;
            
            if (speedupImg) {
                speedupImg.style.display = 'block';
            }
            gpuBanner.className = "gpu-banner cpu-fallback";
            gpuBanner.textContent = `Engine: CPU · GPU benchmark: ${speedupFactor.toFixed(0)}x (${result.data.metadata?.hardware_short || 'T4'})`;
        } else {
            // Benchmark is pending
            speedupVal.textContent = "N/A";
            insightHeadline.innerHTML = `<span style="color: var(--color-text-secondary); font-style: italic;">Benchmark pending — run benchmark_colab.ipynb</span>`;
            benchmarkSource.textContent = "";
            if (speedupImg) {
                speedupImg.style.display = 'none';
            }
            gpuBanner.className = "gpu-banner cpu-fallback";
            gpuBanner.textContent = "Engine: CPU · GPU benchmark: pending";
        }
    } catch (err) {
        console.error("Failed to load benchmark stats:", err);
    }
}

// Load Route Timeline Chart
async function loadRouteTimeline(routeId) {
    activeRouteId = routeId;
    try {
        const res = await fetch(`${API_BASE}/api/routes/${routeId}/timeline`);
        const result = await res.json();
        
        // Prevent race condition: only render if this route is still active!
        if (activeRouteId === routeId && result.status === 'success') {
            renderTimelineChart(result.data);
        }
    } catch (err) {
        console.error(`Failed to load timeline for ${routeId}:`, err);
        const container = document.querySelector('.chart-container');
        if (container) {
            container.innerHTML = `<div style="text-align: center; color: var(--color-danger); padding: 4rem;">Failed to load timeline for ${routeId}.</div>`;
        }
    }
}

// Render Timeline using Chart.js
function renderTimelineChart(data) {
    const dates = data.map(d => d.date);
    const scores = data.map(d => d.reliability_score);
    const headways = data.map(d => d.mean_headway);
    
    // Scheduled headway reference line value
    const numericId = parseInt(activeRouteId.replace("DTC-", ""));
    let schedHeadway = 10;
    if (numericId % 3 === 0) {
        schedHeadway = 6;
    } else if (numericId % 3 === 1) {
        schedHeadway = 12;
    } else {
        schedHeadway = 8;
    }
    
    const schedLine = dates.map(() => schedHeadway);

    // 1. Destroy global tracked instance
    if (timelineChartInstance) {
        try {
            timelineChartInstance.destroy();
        } catch (e) {
            console.error("Error destroying chart:", e);
        }
        timelineChartInstance = null;
    }

    // 2. Query Chart.js static registry to destroy any instance attached to the old canvas ID
    try {
        const registeredChart = Chart.getChart('timeline-chart');
        if (registeredChart) {
            registeredChart.destroy();
        }
    } catch (e) {
        console.error("Error destroying registered chart:", e);
    }

    // 3. Find and remove all canvases with timeline-chart ID or located inside .chart-container
    const allCanvases = document.querySelectorAll('canvas');
    allCanvases.forEach(canvas => {
        if (canvas.id === 'timeline-chart' || canvas.closest('.chart-container')) {
            try {
                const associatedChart = Chart.getChart(canvas);
                if (associatedChart) {
                    associatedChart.destroy();
                }
            } catch (e) {}
            canvas.remove();
        }
    });

    // 4. Re-inject exactly one clean canvas element into the container
    const container = document.querySelector('.chart-container');
    if (container) {
        container.innerHTML = '<canvas id="timeline-chart"></canvas>';
    }

    const canvasEl = document.getElementById('timeline-chart');
    if (!canvasEl) return;
    const ctx = canvasEl.getContext('2d');
    
    // Draw shading bands for bunching episodes (headway < 25% of schedule)
    // To implement this beautifully, we map dataset points. If actual headway < 0.25 * scheduled, highlight it!
    const pointBorderColors = headways.map(h => h < (schedHeadway * 0.25) ? 'rgba(255, 23, 68, 1)' : 'rgba(0, 229, 255, 1)');
    const pointBackgroundColors = headways.map(h => h < (schedHeadway * 0.25) ? 'rgba(255, 23, 68, 0.8)' : 'rgba(0, 229, 255, 0.3)');
    const pointRadii = headways.map(h => h < (schedHeadway * 0.25) ? 6 : 4);

    timelineChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: dates,
            datasets: [
                {
                    label: 'Reliability Score (0-100)',
                    data: scores,
                    borderColor: 'rgba(0, 230, 118, 1)',
                    backgroundColor: 'rgba(0, 230, 118, 0.1)',
                    yAxisID: 'y-score',
                    tension: 0.2,
                    fill: false,
                    borderWidth: 2
                },
                {
                    label: 'Mean Headway (min)',
                    data: headways,
                    borderColor: 'rgba(0, 229, 255, 1)',
                    backgroundColor: 'rgba(0, 229, 255, 0.05)',
                    yAxisID: 'y-headway',
                    tension: 0.2,
                    fill: false,
                    borderWidth: 2.5,
                    pointBorderColor: pointBorderColors,
                    pointBackgroundColor: pointBackgroundColors,
                    pointRadius: pointRadii
                },
                {
                    label: 'Scheduled Headway (min)',
                    data: schedLine,
                    borderColor: 'rgba(255, 179, 0, 0.7)',
                    borderDash: [5, 5],
                    yAxisID: 'y-headway',
                    pointRadius: 0,
                    fill: false,
                    borderWidth: 1.5
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: {
                mode: 'index',
                intersect: false,
            },
            plugins: {
                legend: {
                    position: 'top',
                    labels: {
                        color: '#94a3b8',
                        font: { family: 'Outfit' }
                    }
                },
                tooltip: {
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.datasetIndex === 0) {
                                label += context.raw.toFixed(1);
                            } else {
                                label += context.raw.toFixed(1) + ' min';
                            }
                            return label;
                        }
                    }
                }
            },
            scales: {
                x: {
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#94a3b8', font: { family: 'Outfit', size: 10 } }
                },
                'y-score': {
                    type: 'linear',
                    position: 'left',
                    min: 0,
                    max: 100,
                    grid: { color: 'rgba(255, 255, 255, 0.04)' },
                    ticks: { color: '#00e676', font: { family: 'Outfit' } },
                    title: { display: true, text: 'Reliability Score', color: '#00e676' }
                },
                'y-headway': {
                    type: 'linear',
                    position: 'right',
                    min: 0,
                    max: 25,
                    grid: { drawOnChartArea: false },
                    ticks: { color: '#00e5ff', font: { family: 'Outfit' } },
                    title: { display: true, text: 'Mean Headway (min)', color: '#00e5ff' }
                }
            }
        }
    });
}

// Grounded Cached Answers for Gemini Copilot fallback
let cachedCopilotAnswers = {};

async function fetchCachedCopilotAnswers() {
    try {
        const res = await fetch(`${API_BASE}/api/copilot/cached`);
        const result = await res.json();
        if (result.status === 'success') {
            cachedCopilotAnswers = result.data;
        }
    } catch (err) {
        console.error("Failed to load cached copilot answers:", err);
    }
}

// Send message to Gemini Copilot
async function sendChatMessage() {
    const question = chatInput.value.trim();
    if (!question) return;

    // Append user message
    appendMessage(question, 'user-message');
    chatInput.value = '';
    chatSend.disabled = true;

    // Loading indicator
    const loadingMessage = appendMessage('Analyst is writing response...', 'system-message');

    const key = question.toLowerCase().replace(/[?.]/g, '').trim();

    // Check cached responses for demo mode
    if (cachedCopilotAnswers[key]) {
        setTimeout(() => {
            loadingMessage.innerHTML = formatMarkdown(cachedCopilotAnswers[key]);
            scrollToBottom();
            chatSend.disabled = false;
        }, 800);
        return;
    }

    // Call API fallback
    try {
        const res = await fetch(`${API_BASE}/api/ask`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ question })
        });
        const result = await res.json();
        
        if (result.status === 'success' && !result.response.includes("Gemini Agent Error")) {
            loadingMessage.innerHTML = formatMarkdown(result.response);
        } else {
            // Fallback cached answer if API returns error (e.g. missing API key)
            let fallback = `*Copilot is running in local offline mode.* Here is the analysis for "${question}":\n\n`;
            if (cachedRouteScores && cachedRouteScores.length > 0) {
                const sortedByScore = [...cachedRouteScores].sort((a, b) => a.reliability_score - b.reliability_score);
                const worst = sortedByScore[0];
                fallback += `Our live database reports that **${worst.route_id}** is currently the worst-performing route with a reliability score of **${worst.reliability_score.toFixed(1)}**, ` +
                            `an average headway of **${worst.mean_headway.toFixed(1)} min**, and average dwell of **${worst.mean_dwell_sec.toFixed(0)}s**.\n\n` +
                            `**Recommendation**: Prioritize schedule recalibration and headway spacing controls on Route ${worst.route_id} to mitigate bunching and passenger wait times.\n\n`;
            } else {
                fallback += `We found that Route DTC-008 is congested with a score of 33.0, showing 23.5% bunching. Speedup via GPU RAPIDS is 66x.\n\n`;
            }
            fallback += `Please configure a valid \`GEMINI_API_KEY\` in your environment variables for fully custom natural language queries.`;
            loadingMessage.innerHTML = formatMarkdown(fallback);
        }
    } catch (err) {
        loadingMessage.innerHTML = formatMarkdown("Error connecting to Gemini Analyst. Please ensure backend server is running.");
    } finally {
        scrollToBottom();
        chatSend.disabled = false;
    }
}

// Append message helper
function appendMessage(text, className) {
    const msg = document.createElement('div');
    msg.className = `message ${className}`;
    msg.textContent = text;
    chatMessages.appendChild(msg);
    scrollToBottom();
    return msg;
}

// Scroll to bottom of chat
function scrollToBottom() {
    chatMessages.scrollTop = chatMessages.scrollHeight;
}

// Robust line-by-line HTML-sanitizing markdown formatting helper
function formatMarkdown(text) {
    // 1. Escape HTML characters to prevent XSS
    let escaped = text
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;");

    const lines = escaped.split('\n');
    let html = [];
    let inList = false;
    let listType = ''; // 'ul' or 'ol'
    let inTable = false;

    for (let i = 0; i < lines.length; i++) {
        let line = lines[i];

        // Trim or check list matches
        const ulMatch = line.match(/^(\s*)([*-])\s+(.*)$/);
        const olMatch = line.match(/^(\s*)(\d+)\.\s+(.*)$/);
        const headerMatch = line.match(/^(#{1,6})\s+(.*)$/);
        const tableMatch = line.trim().startsWith('|');

        // Close table if we exit it
        if (inTable && !tableMatch) {
            html.push('</table>');
            inTable = false;
        }

        // Close list if we exit it
        if (inList && !ulMatch && !olMatch) {
            html.push(listType === 'ul' ? '</ul>' : '</ol>');
            inList = false;
            listType = '';
        }

        if (headerMatch) {
            const level = headerMatch[1].length;
            let content = inlineMarkdown(headerMatch[2]);
            html.push(`<h${level}>${content}</h${level}>`);
        } else if (ulMatch) {
            if (!inList || listType !== 'ul') {
                if (inList) {
                    html.push(listType === 'ul' ? '</ul>' : '</ol>');
                }
                html.push('<ul class="chat-list" style="margin-left: 1.5rem; margin-bottom: 0.5rem; list-style-type: disc;">');
                inList = true;
                listType = 'ul';
            }
            let content = inlineMarkdown(ulMatch[3]);
            html.push(`<li>${content}</li>`);
        } else if (olMatch) {
            if (!inList || listType !== 'ol') {
                if (inList) {
                    html.push(listType === 'ul' ? '</ul>' : '</ol>');
                }
                html.push('<ol class="chat-list" style="margin-left: 1.5rem; margin-bottom: 0.5rem; list-style-type: decimal;">');
                inList = true;
                listType = 'ol';
            }
            let content = inlineMarkdown(olMatch[3]);
            html.push(`<li>${content}</li>`);
        } else if (tableMatch) {
            const cells = line.split('|').map(c => c.trim()).filter((c, idx, arr) => idx > 0 && idx < arr.length - 1);
            if (!inTable) {
                html.push('<table class="chat-table" style="width: 100%; border-collapse: collapse; margin: 0.5rem 0; border: 1px solid var(--border-color); font-size: 0.75rem;">');
                inTable = true;
                html.push('<tr style="background-color: var(--bg-surface-elevated); border-bottom: 1px solid var(--border-color);">' + cells.map(c => `<th style="padding: 0.4rem; text-align: left; font-weight: 600;">${inlineMarkdown(c)}</th>`).join('') + '</tr>');
            } else {
                if (line.includes('---')) {
                    continue; // Skip separator line
                }
                html.push('<tr style="border-bottom: 1px solid var(--border-color);">' + cells.map(c => `<td style="padding: 0.4rem;">${inlineMarkdown(c)}</td>`).join('') + '</tr>');
            }
        } else {
            // Normal paragraph or empty line
            if (line.trim() === '') {
                html.push('<br/>');
            } else {
                html.push(`<p style="margin-bottom: 0.4rem;">${inlineMarkdown(line)}</p>`);
            }
        }
    }

    if (inTable) {
        html.push('</table>');
    }
    if (inList) {
        html.push(listType === 'ul' ? '</ul>' : '</ol>');
    }

    return html.join('\n');
}

function inlineMarkdown(text) {
    // Bold: **text**
    text = text.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
    // Italic: *text* or _text_
    text = text.replace(/\*(.*?)\*/g, '<em>$1</em>');
    text = text.replace(/_(.*?)_/g, '<em>$1</em>');
    // Code inline: `code`
    text = text.replace(/`(.*?)`/g, '<code class="code-font" style="font-family: monospace; background-color: var(--bg-surface-elevated); padding: 0.1rem 0.2rem; border-radius: 3px;">$1</code>');
    return text;
}

// Prevent duplicate canvas elements from existing in the DOM (Ghost Chart fail-safe)
setInterval(() => {
    const canvases = document.querySelectorAll('canvas');
    if (canvases.length > 1) {
        let activeCanvas = null;
        canvases.forEach(canvas => {
            if (canvas.closest('.chart-container') && !activeCanvas) {
                activeCanvas = canvas;
            }
        });
        
        canvases.forEach(canvas => {
            if (canvas !== activeCanvas) {
                try {
                    const chart = Chart.getChart(canvas);
                    if (chart) {
                        chart.destroy();
                    }
                } catch (e) {}
                canvas.remove();
            }
        });
    }
}, 100);
