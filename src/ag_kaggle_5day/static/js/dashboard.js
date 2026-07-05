        function escapeHTML(str) {
            if (str === null || str === undefined) return '';
            const s = String(str);
            return s.replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;');
        }

        // Dynamically inject link pulse animation style
        (function() {
            const style = document.createElement("style");
            style.textContent = `
                @keyframes starmap-pulse {
                    0% { stroke-opacity: var(--min-opacity, 0.1); }
                    50% { stroke-opacity: var(--max-opacity, 0.6); }
                    100% { stroke-opacity: var(--min-opacity, 0.1); }
                }
                .constellation-link {
                    animation: starmap-pulse var(--pulse-dur, 4s) infinite ease-in-out;
                }
            `;
            document.head.appendChild(style);
        })();

        let initialSyncDone = false;
        let lastCacheRefreshedAt = 0;
        let comparisonPollTimeout = null;

        function setButtonCooldown(btn, defaultText, durationMs = 10000) {
            if (!btn) return;
            btn.innerHTML = `Cooldown (${Math.round(durationMs / 1000)} sec)`;
            btn.disabled = true;
            setTimeout(() => {
                btn.innerHTML = defaultText;
                btn.disabled = false;
            }, durationMs);
        }

        let hasSessionKey = false;

        function checkKey() {
            if (clientKeyConfigured) return true;
            if (hasSessionKey) return true;
            
            const sessionFlag = sessionStorage.getItem("has_session_key");
            if (sessionFlag === "true") {
                hasSessionKey = true;
                return true;
            }

            const localFlag = localStorage.getItem("has_session_key");
            const expiry = localStorage.getItem("session_key_expiry");
            if (localFlag === "true" && expiry) {
                if (Date.now() < parseInt(expiry)) {
                    hasSessionKey = true;
                    sessionStorage.setItem("has_session_key", "true");
                    return true;
                } else {
                    localStorage.removeItem("has_session_key");
                    localStorage.removeItem("session_key_expiry");
                }
            }
            return false;
        }

        async function submitKey() {
            const input = document.getElementById('api-key-input');
            const key = input.value.trim();
            if (!key) {
                alert("Please enter a valid Google AI Studio API key.");
                return;
            }

            const remember = document.getElementById('remember-key').checked;
            const connectBtn = document.querySelector('#activation-view .btn-action');
            const originalText = connectBtn.textContent;
            connectBtn.disabled = true;
            connectBtn.textContent = "CONNECTING...";

            try {
                const response = await fetch('/api/auth/connect', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ api_key: key, remember: remember })
                });

                if (!response.ok) {
                    const errData = await response.json();
                    alert(errData.detail || "Failed to connect API key.");
                    connectBtn.disabled = false;
                    connectBtn.textContent = originalText;
                    return;
                }

                hasSessionKey = true;
                sessionStorage.setItem("has_session_key", "true");
                if (remember) {
                    localStorage.setItem("has_session_key", "true");
                    localStorage.setItem("session_key_expiry", (Date.now() + 3600000).toString()); // 1 Hour TTL
                } else {
                    localStorage.removeItem("has_session_key");
                    localStorage.removeItem("session_key_expiry");
                }

                showDashboard();
                await updateConfigStatus();
            } catch (err) {
                console.error("Connect error:", err);
                alert("Network error: failed to connect to the server.");
                connectBtn.disabled = false;
                connectBtn.textContent = originalText;
            }
        }

        /* ===== ARCADE CHATBOT STATE MACHINE ===== */
        // States: 'closed', 'panel', 'arcade'
        let arcadeChatState = 'closed';

        // Shared chat content elements (reparented between panel & arcade)
        const chatContentHTML = `
            <div class="chat-messages" id="chat-messages">
                <div class="message agent">
                    SYSTEM ONLINE — WOR-ACLE Co-Pilot initialized.<br>
                    Ask me about game selection, live stream trends, or hidden gem recommendations.
                </div>
            </div>
            <div class="chat-input-wrapper">
                <input type="text" class="chat-input" id="chat-input" placeholder="ENTER COMMAND..." onkeydown="handleKey(event)">
                <button class="btn-send" onclick="sendMessage()">➔</button>
            </div>
            <div class="suggestions">
                <div class="suggestion-chip" onclick="applySuggestion('What game should I stream tonight to stand out?')">What game should I stream tonight?</div>
                <div class="suggestion-chip" onclick="applySuggestion('What is the current streaming zeitgeist?')">Current zeitgeist?</div>
                <div class="suggestion-chip" onclick="applySuggestion('Suggest an out-of-sample indie game.')">Suggest a hidden gem.</div>
            </div>
        `;

        function initChatbot() {
            if (document.getElementById('arcade-tab')) return;

            // 1. Edge Tab
            const tab = document.createElement('div');
            tab.id = 'arcade-tab';
            tab.className = 'arcade-tab';
            tab.onclick = () => toggleChat();
            tab.ondblclick = () => openArcade();
            tab.innerHTML = `
                <span class="arcade-tab-icon">🕹️</span>
                <span class="arcade-tab-label">WOR-ACLE</span>
            `;
            document.body.appendChild(tab);

            // 2. Side Panel
            const panel = document.createElement('div');
            panel.id = 'arcade-panel';
            panel.className = 'arcade-panel crt-overlay';
            panel.innerHTML = `
                <div class="arcade-panel-header">
                    <h3>🕹️ WOR-ACLE</h3>
                    <div class="arcade-panel-actions">
                        <button class="btn-expand-arcade" onclick="openArcade()" title="Full-screen arcade mode">EXPAND ▶</button>
                        <button class="arcade-panel-close" onclick="closeChat()">✖</button>
                    </div>
                </div>
                <div id="panel-chat-mount"></div>
            `;
            document.body.appendChild(panel);

            // 3. Full-Screen Arcade Overlay
            const overlay = document.createElement('div');
            overlay.id = 'arcade-overlay';
            overlay.className = 'arcade-overlay';
            overlay.innerHTML = `
                <div class="arcade-cabinet">
                    <div class="arcade-marquee">
                        <h2>🕹️ WOR-ACLE</h2>
                        <div class="arcade-marquee-sub">STREAMER CO-PILOT TERMINAL</div>
                    </div>
                    <div class="arcade-screen" id="arcade-screen">
                        <div id="arcade-chat-mount"></div>
                    </div>
                    <div class="arcade-controls">
                        <div class="arcade-controls-label">— COMMAND INTERFACE —</div>
                        <div id="arcade-input-mount"></div>
                    </div>
                    <div class="arcade-footer">
                        <button class="btn-arcade-close" onclick="closeChat()">⬅ EXIT ARCADE</button>
                        <span class="arcade-credit">INSERT COIN — CREDIT 99</span>
                    </div>
                </div>
            `;
            // Close overlay when clicking backdrop (not the cabinet itself)
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) closeChat();
            });
            document.body.appendChild(overlay);

            // 4. Create the shared chat content
            const chatContainer = document.createElement('div');
            chatContainer.id = 'chat-content-container';
            chatContainer.innerHTML = chatContentHTML;
            // Start mounted in the panel
            document.getElementById('panel-chat-mount').appendChild(chatContainer);
            applyKeylessRestrictions();
        }

        function reparentChatTo(targetMountId, inputMountId) {
            const container = document.getElementById('chat-content-container');
            if (!container) return;

            // Find elements globally since they might be split and outside container
            const messagesEl = document.getElementById('chat-messages');
            const inputWrapper = document.querySelector('.chat-input-wrapper');
            const suggestions = document.querySelector('.suggestions');

            // Save scroll position
            const scrollPos = messagesEl ? messagesEl.scrollTop : 0;

            if (inputMountId) {
                // Arcade mode: split messages and input into separate mounts
                const targetMount = document.getElementById(targetMountId);
                const inputMount = document.getElementById(inputMountId);
                if (targetMount && messagesEl) {
                    targetMount.innerHTML = '';
                    targetMount.appendChild(messagesEl);
                }
                if (inputMount) {
                    inputMount.innerHTML = '';
                    if (inputWrapper) inputMount.appendChild(inputWrapper);
                    if (suggestions) inputMount.appendChild(suggestions);
                }
            } else {
                // Panel mode: everything in one mount
                if (messagesEl) container.appendChild(messagesEl);
                if (inputWrapper) container.appendChild(inputWrapper);
                if (suggestions) container.appendChild(suggestions);

                const targetMount = document.getElementById(targetMountId);
                if (targetMount) {
                    targetMount.innerHTML = '';
                    targetMount.appendChild(container);
                }
            }

            // Restore scroll
            if (messagesEl) messagesEl.scrollTop = scrollPos;
        }

        function toggleChat() {
            initChatbot();
            if (arcadeChatState === 'closed') {
                openArcade();
            } else {
                closeChat();
            }
        }

        function openPanel() {
            initChatbot();
            arcadeChatState = 'panel';

            // Close arcade if open
            const overlay = document.getElementById('arcade-overlay');
            if (overlay) overlay.classList.remove('active');

            // Reparent chat to panel
            reparentChatTo('panel-chat-mount', null);

            // Open panel
            const panel = document.getElementById('arcade-panel');
            if (panel) panel.classList.add('open');

            // Update tab state
            const tab = document.getElementById('arcade-tab');
            if (tab) tab.classList.add('active');

            document.body.classList.add('chat-panel-open');

            setTimeout(() => {
                const inp = document.getElementById('chat-input');
                if (inp) inp.focus();
            }, 150);
        }

        function openArcade() {
            initChatbot();
            arcadeChatState = 'arcade';

            // Close panel
            const panel = document.getElementById('arcade-panel');
            if (panel) panel.classList.remove('open');
            document.body.classList.remove('chat-panel-open');
            document.body.classList.add('arcade-open');

            // Reparent chat to arcade screen
            reparentChatTo('arcade-chat-mount', 'arcade-input-mount');

            // Open overlay
            const overlay = document.getElementById('arcade-overlay');
            if (overlay) overlay.classList.add('active');

            // Boot animation
            const screen = document.getElementById('arcade-screen');
            if (screen) {
                screen.classList.add('booting');
                setTimeout(() => screen.classList.remove('booting'), 800);
            }

            // Update tab
            const tab = document.getElementById('arcade-tab');
            if (tab) tab.classList.add('active');

            setTimeout(() => {
                const inp = document.getElementById('chat-input');
                if (inp) inp.focus();
            }, 300);
        }

        function closeChat() {
            arcadeChatState = 'closed';

            // Close panel
            const panel = document.getElementById('arcade-panel');
            if (panel) panel.classList.remove('open');

            // Close overlay
            const overlay = document.getElementById('arcade-overlay');
            if (overlay) overlay.classList.remove('active');

            // Reparent back to panel mount (home position)
            reparentChatTo('panel-chat-mount', null);

            // Reset tab
            const tab = document.getElementById('arcade-tab');
            if (tab) tab.classList.remove('active');

            document.body.classList.remove('chat-panel-open');
            document.body.classList.remove('arcade-open');
        }

        async function logout() {
            try {
                await fetch('/api/auth/disconnect', { method: 'POST' });
            } catch (err) {
                console.error("Failed to disconnect session on server:", err);
            }

            hasSessionKey = false;
            sessionStorage.removeItem("has_session_key");
            localStorage.removeItem("has_session_key");
            localStorage.removeItem("session_key_expiry");
            initialSyncDone = false;

            document.getElementById('api-key-input').value = '';
            document.getElementById('activation-view').style.display = 'flex';
            document.getElementById('dashboard-view').style.display = 'none';
            document.getElementById('planner-view').style.display = 'none';
            document.getElementById('curation-view').style.display = 'none';
            document.getElementById('starmap-view').style.display = 'none';
            document.getElementById('header-actions').style.display = 'none';
            document.getElementById('tab-navigation').style.display = 'none';
            const globalSearch = document.getElementById('global-search-container');
            if (globalSearch) globalSearch.style.display = 'none';
            closeChat();

            const cancelBtn = document.getElementById('btn-cancel-activation');
            if (cancelBtn) {
                cancelBtn.style.display = serverKeyConfigured ? 'block' : 'none';
            }
        }

        function applyKeylessRestrictions() {
            const hasKey = checkKey();
            
            const warningEl = document.getElementById('matchmaker-key-warning');
            if (warningEl) {
                warningEl.style.display = hasKey ? 'none' : 'block';
            }
            
            // 1. Chatbot Input
            const chatInput = document.getElementById('chat-input');
            const sendBtn = document.querySelector('.btn-send');
            if (chatInput) {
                if (!hasKey) {
                    chatInput.disabled = true;
                    chatInput.placeholder = "🔑 CONNECT PERSONAL KEY TO CHAT...";
                    if (sendBtn) sendBtn.disabled = true;
                } else {
                    chatInput.disabled = false;
                    chatInput.placeholder = "ENTER COMMAND...";
                    if (sendBtn) sendBtn.disabled = false;
                }
            }

            // 2. Playbook Planner Generate Button
            const genBtn = document.getElementById('btn-playbooks');
            if (genBtn) {
                if (!hasKey) {
                    genBtn.disabled = true;
                    genBtn.textContent = 'API Key Required for Custom Playbooks';
                } else {
                    genBtn.disabled = false;
                    genBtn.textContent = 'Generate Strategic Playbooks';
                }
            }

            // 3. Header Action Button (Connect/Disconnect Key)
            const keyActionBtn = document.getElementById('btn-key-action');
            if (keyActionBtn) {
                if (hasKey) {
                    keyActionBtn.textContent = 'Disconnect Key';
                    keyActionBtn.className = 'btn-action';
                } else {
                    keyActionBtn.textContent = '🔑 Connect Personal Key';
                    keyActionBtn.className = 'btn-secondary';
                }
            }
        }

        function showDashboard() {
            document.getElementById('activation-view').style.display = 'none';
            document.getElementById('dashboard-view').style.display = 'grid';
            document.getElementById('header-actions').style.display = 'flex';
            document.getElementById('tab-navigation').style.display = 'flex';
            const globalSearch = document.getElementById('global-search-container');
            if (globalSearch) globalSearch.style.display = 'flex';
            switchTab('dashboard');

            initChatbot();
            initSpotlight();
            loadTopSpotlightBanner();

            // Load custom games inputs from localStorage if present
            document.getElementById('custom-game-1').value = localStorage.getItem("custom_game_1") || "";
            document.getElementById('custom-game-2').value = localStorage.getItem("custom_game_2") || "";

            loadModelSettings();

            // Restore category selection from localStorage if present
            const savedCategory = localStorage.getItem('selected_category') || 'overall';
            const categoryEl = document.getElementById('category-selector');
            if (categoryEl) {
                categoryEl.value = savedCategory;
            }

            fetchGames();
            loadEcosystemOverview();
            // Start polling cache status badge
            fetchCacheStatus();
            setInterval(fetchCacheStatus, 60000); // refresh badge every minute

            applyKeylessRestrictions();
        }

        function saveCustomGames() {
            const cg1 = document.getElementById('custom-game-1').value.trim();
            const cg2 = document.getElementById('custom-game-2').value.trim();
            localStorage.setItem("custom_game_1", cg1);
            localStorage.setItem("custom_game_2", cg2);
            triggerScrape();
        }

        function saveModelSettings() {
            const searchModel = document.getElementById('model-search').value;
            const analysisModel = document.getElementById('model-analysis').value;
            const chatModel = document.getElementById('model-chat').value;

            localStorage.setItem('gemini_model_search', searchModel);
            localStorage.setItem('gemini_model_analysis', analysisModel);
            localStorage.setItem('gemini_model_chat', chatModel);

            // Sync to activation screen selectors
            if (document.getElementById('act-model-search')) {
                document.getElementById('act-model-search').value = searchModel;
                document.getElementById('act-model-analysis').value = analysisModel;
                document.getElementById('act-model-chat').value = chatModel;
            }
        }

        function syncActivationModelsToSettings() {
            const searchModel = document.getElementById('act-model-search').value;
            const analysisModel = document.getElementById('act-model-analysis').value;
            const chatModel = document.getElementById('act-model-chat').value;

            localStorage.setItem('gemini_model_search', searchModel);
            localStorage.setItem('gemini_model_analysis', analysisModel);
            localStorage.setItem('gemini_model_chat', chatModel);

            if (document.getElementById('model-search')) {
                document.getElementById('model-search').value = searchModel;
                document.getElementById('model-analysis').value = analysisModel;
                document.getElementById('model-chat').value = chatModel;
            }
        }

        function loadModelSettings() {
            const searchModel = localStorage.getItem('gemini_model_search') || 'gemma-4-31b-it';
            const analysisModel = localStorage.getItem('gemini_model_analysis') || 'gemma-4-31b-it';
            const chatModel = localStorage.getItem('gemini_model_chat') || 'gemma-4-31b-it';

            if (document.getElementById('model-search')) {
                document.getElementById('model-search').value = searchModel;
                document.getElementById('model-analysis').value = analysisModel;
                document.getElementById('model-chat').value = chatModel;
            }

            if (document.getElementById('act-model-search')) {
                document.getElementById('act-model-search').value = searchModel;
                document.getElementById('act-model-analysis').value = analysisModel;
                document.getElementById('act-model-chat').value = chatModel;
            }
        }

        function setupDashboardAutocomplete() {
            const input = document.getElementById('dashboard-streamer-search');
            const listContainer = document.getElementById('dashboard-autocomplete-list');
            if (!input || !listContainer) return;

            input.addEventListener('input', async () => {
                const val = input.value.trim();
                if (!val) {
                    listContainer.style.display = 'none';
                    return;
                }

                try {
                    const res = await fetch(`/api/streamers/autocomplete?q=${encodeURIComponent(val)}`);
                    if (res.ok) {
                        const items = await res.json();
                        if (items && items.length > 0) {
                            listContainer.innerHTML = '';
                            listContainer.style.display = 'block';
                            items.forEach(item => {
                                const div = document.createElement('div');
                                div.textContent = item;
                                div.onclick = () => {
                                    input.value = item;
                                    listContainer.style.display = 'none';
                                };
                                listContainer.appendChild(div);
                            });
                        } else {
                            listContainer.style.display = 'none';
                        }
                    }
                } catch (e) {
                    listContainer.style.display = 'none';
                }
            });

            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const val = input.value.trim();
                    if (val) {
                        listContainer.style.display = 'none';
                        triggerDashboardMediumForm(val);
                    }
                }
            });

            document.addEventListener('click', (e) => {
                if (e.target !== input) {
                    listContainer.style.display = 'none';
                }
            });
        }

        function setupDrawerAutocomplete() {
            const input = document.getElementById('drawer-streamer-search');
            const listContainer = document.getElementById('drawer-autocomplete-list');
            if (!input || !listContainer) return;

            input.addEventListener('input', async () => {
                const val = input.value.trim();
                if (!val) {
                    listContainer.style.display = 'none';
                    return;
                }

                try {
                    const res = await fetch(`/api/streamers/autocomplete?q=${encodeURIComponent(val)}`);
                    if (res.ok) {
                        const items = await res.json();
                        if (items && items.length > 0) {
                            listContainer.innerHTML = '';
                            listContainer.style.display = 'block';
                            items.forEach(item => {
                                const div = document.createElement('div');
                                div.textContent = item;
                                div.style.padding = '0.5rem';
                                div.style.cursor = 'pointer';
                                div.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
                                div.onclick = () => {
                                    input.value = '';
                                    listContainer.style.display = 'none';
                                    openStreamerProfileDrawer(item);
                                };
                                listContainer.appendChild(div);
                            });
                        } else {
                            listContainer.style.display = 'none';
                        }
                    }
                } catch (e) {
                    listContainer.style.display = 'none';
                }
            });

            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const val = input.value.trim();
                    if (val) {
                        listContainer.style.display = 'none';
                        input.value = '';
                        openStreamerProfileDrawer(val);
                    }
                }
            });

            document.addEventListener('click', (e) => {
                if (e.target !== input) {
                    listContainer.style.display = 'none';
                }
            });
        }

        function setupGlobalAutocomplete() {
            const input = document.getElementById('global-streamer-search');
            const listContainer = document.getElementById('global-autocomplete-list');
            if (!input || !listContainer) return;

            input.addEventListener('input', async () => {
                const val = input.value.trim();
                if (!val) {
                    listContainer.style.display = 'none';
                    return;
                }

                try {
                    const res = await fetch(`/api/streamers/autocomplete?q=${encodeURIComponent(val)}`);
                    if (res.ok) {
                        const items = await res.json();
                        if (items && items.length > 0) {
                            listContainer.innerHTML = '';
                            listContainer.style.display = 'block';
                            items.forEach(item => {
                                const div = document.createElement('div');
                                const isObj = typeof item === 'object' && item !== null;
                                const displayName = isObj ? item.display_name : item;
                                const handle = isObj ? item.handle : item;
                                const platform = isObj ? item.platform : '';

                                const span = document.createElement('span');
                                if (platform === 'youtube') {
                                    span.textContent = "🔴 ";
                                    span.style.color = "#f87171";
                                } else if (platform === 'twitch') {
                                    span.textContent = "👾 ";
                                    span.style.color = "#c084fc";
                                }

                                div.textContent = displayName;
                                if (span.textContent) {
                                    div.prepend(span);
                                }

                                div.style.padding = '0.5rem';
                                div.style.cursor = 'pointer';
                                div.style.borderBottom = '1px solid rgba(255,255,255,0.05)';
                                div.style.color = '#fff';
                                div.style.fontFamily = "'Share Tech Mono', monospace";
                                div.style.fontSize = '0.8rem';
                                div.style.background = '#0b0f19';
                                div.onmouseover = () => { div.style.background = 'rgba(0, 240, 255, 0.15)'; div.style.color = 'var(--accent-cyan)'; };
                                div.onmouseout = () => { div.style.background = '#0b0f19'; div.style.color = '#fff'; };
                                div.onclick = () => {
                                    input.value = '';
                                    listContainer.style.display = 'none';
                                    openStreamerProfileDrawer(handle);
                                };
                                listContainer.appendChild(div);
                            });
                        } else {
                            listContainer.style.display = 'none';
                        }
                    }
                } catch (e) {
                    listContainer.style.display = 'none';
                }
            });

            input.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    const val = input.value.trim();
                    if (val) {
                        listContainer.style.display = 'none';
                        input.value = '';
                        openStreamerProfileDrawer(val);
                    }
                }
            });

            document.addEventListener('click', (e) => {
                if (e.target !== input) {
                    listContainer.style.display = 'none';
                }
            });
        }

        function updateSessionResearchList() {
            const section = document.getElementById('session-research-section');
            const list = document.getElementById('session-research-list');
            if (!section || !list) return;

            let sessionData = [];
            try {
                sessionData = JSON.parse(sessionStorage.getItem('my_generated_streamers') || '[]');
            } catch (e) {
                sessionData = [];
            }

            if (sessionData.length > 0) {
                section.style.display = 'block';
                list.innerHTML = '';
                sessionData.forEach(item => {
                    const btn = document.createElement('button');
                    btn.className = 'btn-secondary';
                    btn.style.display = 'block';
                    btn.style.margin = '0.25rem 0';
                    btn.style.textAlign = 'left';
                    btn.style.width = '100%';
                    btn.style.fontSize = '0.8rem';
                    btn.style.padding = '0.5rem';
                    btn.style.background = 'rgba(0, 180, 216, 0.05)';
                    btn.style.border = '1px solid rgba(0, 180, 216, 0.2)';
                    btn.style.color = '#fff';
                    btn.style.cursor = 'pointer';
                    btn.textContent = `🔍 ${item.streamer_handle.toUpperCase()}`;
                    btn.onclick = () => {
                        document.getElementById('dashboard-streamer-search').value = item.streamer_handle;
                        triggerDashboardMediumForm(item.streamer_handle);
                    };
                    list.appendChild(btn);
                });
            } else {
                section.style.display = 'none';
            }
        }

        function showRetroLoader(handle) {
            const input = document.getElementById('dashboard-streamer-search');
            const button = document.getElementById('btn-dashboard-analyze');
            const status = document.getElementById('dashboard-streamer-generating-status');
            if (input) {
                input.disabled = true;
                input.classList.add('generating-pulse');
            }
            if (button) {
                button.disabled = true;
                button.style.opacity = '0.5';
                button.textContent = 'SCRAPING...';
            }
            if (status) {
                status.textContent = `Scraping & generating profile for streamer '${handle}'...`;
                status.style.display = 'block';
            }
        }

        function hideRetroLoader() {
            const input = document.getElementById('dashboard-streamer-search');
            const button = document.getElementById('btn-dashboard-analyze');
            const status = document.getElementById('dashboard-streamer-generating-status');
            if (input) {
                input.disabled = false;
                input.classList.remove('generating-pulse');
            }
            if (button) {
                button.disabled = false;
                button.style.opacity = '1';
                button.textContent = 'ANALYZE';
            }
            if (status) {
                status.style.display = 'none';
            }
        }

        async function triggerDashboardMediumForm(handleParam) {
            const input = document.getElementById('dashboard-streamer-search');
            if (!input) return;
            const handle = (handleParam || input.value).trim();
            if (!handle) return;

            openSpotlightCabinet(handle);
        }

        function initSpotlight() {
            if (document.getElementById('spotlight-tab')) return;

            const tab = document.createElement('div');
            tab.id = 'spotlight-tab';
            tab.className = 'spotlight-tab';
            tab.onclick = () => openSpotlightCabinet();
            tab.innerHTML = `
                <span class="spotlight-tab-icon">📰</span>
                <span class="spotlight-tab-label">SPOTLIGHT</span>
            `;
            document.body.appendChild(tab);
        }

        function initSpotlightOverlay() {
            if (document.getElementById('spotlight-overlay')) return;
            const overlay = document.createElement('div');
            overlay.id = 'spotlight-overlay';
            overlay.className = 'arcade-overlay';
            overlay.style.zIndex = '1999';
            overlay.innerHTML = `
                <div class="arcade-cabinet"
                    style="width: 98vw;
                    height: 96vh;
                    max-width: none;
                    max-height: none;
                    margin: 0;
                    border: 2px solid var(--accent-cyan);
                    box-shadow: 0 0 25px rgba(0, 240, 255, 0.15);">
                    <div class="arcade-marquee"
                        style="border-bottom: 2px solid var(--accent-pink); padding: 0.5rem 1rem; min-height: auto; height: auto; display: flex; align-items: center; justify-content: space-between; flex-direction: row;">
                        <h2 style="font-size: 1rem; margin: 0;">📰 SPOTLIGHT — STREAMER DOSSIER HUB</h2>
                        <div class="arcade-marquee-sub" style="font-size: 0.65rem; margin: 0; text-shadow: none;">
                            WOR-ACLE DATA FEED
                        </div>
                    </div>
                    <div class="arcade-screen" id="spotlight-screen" style="margin: 0.25rem; flex: 1; border: 1px solid rgba(0, 240, 255, 0.2);">
                        <iframe id="spotlight-iframe"
                            class="spotlight-iframe" src=""></iframe>
                    </div>
                    <div class="arcade-footer" style="padding: 0.5rem 1rem; min-height: auto; height: auto;">
                        <button class="btn-arcade-close"
                            onclick="closeSpotlightCabinet()" style="padding: 0.4rem 1rem; font-size: 0.8rem;">
                            ⬅ EXIT SPOTLIGHT
                        </button>
                        <span class="arcade-credit" style="font-size: 0.75rem;">
                            SYSTEM READY — ACTIVE STREAM DOSSIER
                        </span>
                    </div>
                </div>
            `;
            overlay.addEventListener('click', (e) => {
                if (e.target === overlay) closeSpotlightCabinet();
            });
            document.body.appendChild(overlay);
        }

        function openSpotlightCabinet(handle) {
            initSpotlightOverlay();
            const iframe = document.getElementById('spotlight-iframe');
            if (iframe) {
                let url = '/spotlight';
                if (handle) {
                    url += `?handle=${encodeURIComponent(handle)}`;
                }
                const currentSrc = iframe.getAttribute('src');
                const relativeSrc = currentSrc ?
                    currentSrc.replace(window.location.origin, '') : '';
                if (relativeSrc !== url) {
                    iframe.src = url;
                }
            }
            const overlay = document.getElementById('spotlight-overlay');
            if (overlay) overlay.classList.add('active');

            const screen = document.getElementById('spotlight-screen');
            if (screen) {
                screen.classList.add('booting');
                setTimeout(() => screen.classList.remove('booting'), 800);
            }
            const tab = document.getElementById('spotlight-tab');
            if (tab) tab.classList.add('active');

            document.body.classList.add('arcade-open');
        }

        function closeSpotlightCabinet() {
            const overlay = document.getElementById('spotlight-overlay');
            if (overlay) overlay.classList.remove('active');

            const tab = document.getElementById('spotlight-tab');
            if (tab) tab.classList.remove('active');

            const arcadeOverlay = document.getElementById('arcade-overlay');
            const isActive = arcadeOverlay &&
                arcadeOverlay.classList.contains('active');
            if (!isActive) {
                document.body.classList.remove('arcade-open');
            }
        }

        async function loadTopSpotlightBanner() {
            try {
                const res = await fetch('/api/articles/expose/latest');
                if (res.ok) {
                    const data = await res.json();
                    if (data && data.streamer_handle) {
                        const banner = document.getElementById(
                            'top-spotlight-banner'
                        );
                        const title = document.getElementById(
                            'spotlight-banner-title'
                        );
                        const desc = document.getElementById(
                            'spotlight-banner-desc'
                        );
                        if (banner) {
                            if (title) {
                                title.textContent =
                                    `Streamer of the Day: @${data.streamer_handle}`;
                            }
                            if (desc) {
                                desc.textContent = data.title ||
                                    "Check out the latest live metrics " +
                                    "and sentiment analysis dossier.";
                            }
                            banner.style.display = 'grid';
                        }
                    }
                }
            } catch (e) {
                console.error("Failed to load top spotlight banner:", e);
            }
        }


        let serverKeyConfigured = false;
        let clientKeyConfigured = false;
        let serverAffiliatePlaybook = null;
        let currentGeneratedPlaybooks = {};

        async function updateConfigStatus() {
            try {
                const res = await fetch('/api/config');
                const data = await res.json();
                serverKeyConfigured = data.server_key_configured;
                clientKeyConfigured = data.client_key_configured;

                // Sync hasSessionKey with actual cookie validation status from backend
                if (clientKeyConfigured) {
                    hasSessionKey = true;
                    sessionStorage.setItem("has_session_key", "true");
                } else {
                    hasSessionKey = false;
                    sessionStorage.removeItem("has_session_key");
                    localStorage.removeItem("has_session_key");
                    localStorage.removeItem("session_key_expiry");
                }
                applyKeylessRestrictions();

                serverAffiliatePlaybook = data.affiliate_playbook;
                if (serverAffiliatePlaybook) {
                    currentGeneratedPlaybooks['affiliate'] = serverAffiliatePlaybook;
                }

                if (data.deployment_nonce) {
                    const el = document.getElementById('deployment-nonce-stamp');
                    if (el) {
                        el.textContent = `— NONCE: ${data.deployment_nonce}`;
                    }
                }

                // Dynamically populate model selectors from server config
                if (data.available_models) {
                    const selectors = [
                        'act-model-search', 'act-model-analysis', 'act-model-chat',
                        'model-search', 'model-analysis', 'model-chat'
                    ];
                    selectors.forEach(selId => {
                        const sel = document.getElementById(selId);
                        if (sel) {
                            sel.innerHTML = '';
                            data.available_models.forEach(model => {
                                const opt = document.createElement('option');
                                opt.value = model.id;
                                opt.textContent = model.name;
                                sel.appendChild(opt);
                            });
                        }
                    });
                }

                // If model settings are not in localStorage, use defaults from server config
                if (!localStorage.getItem('gemini_model_search') && data.default_model) {
                    localStorage.setItem('gemini_model_search', data.default_model);
                }
                if (!localStorage.getItem('gemini_model_analysis') && data.report_model) {
                    localStorage.setItem('gemini_model_analysis', data.report_model);
                }
                if (!localStorage.getItem('gemini_model_chat') && data.default_model) {
                    localStorage.setItem('gemini_model_chat', data.default_model);
                }

                loadModelSettings();

                // Show/hide cancel activation button based on server key status
                const cancelBtn = document.getElementById('btn-cancel-activation');
                if (cancelBtn) {
                    cancelBtn.style.display = (serverKeyConfigured || hasSessionKey) ? 'block' : 'none';
                }
            } catch (err) {
                console.error("Failed to fetch server config:", err);
            }
        }

        async function initApp() {
            // Restore hasSessionKey from storage if present
            const sessionFlag = sessionStorage.getItem("has_session_key");
            if (sessionFlag === "true") {
                hasSessionKey = true;
            } else {
                const localFlag = localStorage.getItem("has_session_key");
                const expiry = localStorage.getItem("session_key_expiry");
                if (localFlag === "true" && expiry && Date.now() < parseInt(expiry)) {
                    hasSessionKey = true;
                    sessionStorage.setItem("has_session_key", "true");
                }
            }

            await updateConfigStatus();

            if (checkKey() || serverKeyConfigured) {
                showDashboard();
                setupDashboardAutocomplete();
                setupDrawerAutocomplete();
                setupGlobalAutocomplete();
                updateSessionResearchList();
            } else {
                document.getElementById('activation-view').style.display = 'flex';
            }
        }

        function cancelActivation() {
            if (serverKeyConfigured) {
                showDashboard();
            }
        }

        let cachedGamesList = [];
        let sponsoredGamesList = [];
        let currentSponsoredIndex = 0;
        let sponsoredIntervalId = null;
        let currentSparklineMode = 'combined';

        function matchesCategory(category, title, selected) {
            if (!selected || selected === 'overall') return true;
            const cat = (category || '').toLowerCase();
            const t = (title || '').toLowerCase();
            
            if (selected === 'sandbox') {
                return cat.includes('sandbox') || cat.includes('open world') || t.includes('minecraft');
            }
            if (selected === 'rpg') {
                return cat.includes('rpg') || cat.includes('role-playing') || cat.includes('souls') || t.includes('elden ring');
            }
            if (selected === 'fps') {
                return cat.includes('fps') || cat.includes('shooter') || t.includes('valorant');
            }
            if (selected === 'roguelike') {
                return cat.includes('rogue') || t.includes('hades');
            }
            if (selected === 'moba') {
                return cat.includes('moba') || cat.includes('multiplayer online battle arena') || t.includes('league of legends');
            }
            if (selected === 'action-adventure') {
                return cat.includes('action') || cat.includes('adventure') || cat.includes('racing') || cat.includes('driving') || cat.includes('forza') || t.includes('gta') || t.includes('grand theft auto') || t.includes('forza');
            }
            if (selected === 'irl') {
                return cat.includes('irl') || cat.includes('just chatting') || cat.includes('chatting');
            }
            return true;
        }

        function createPlaceholderCardHTML(slotNumber) {
            return `
                <div class="game-card" style="border: 2px dashed rgba(255, 0, 127, 0.3) !important; background: rgba(255, 0, 127, 0.02); display: flex; flex-direction: column; justify-content: center; align-items: center; text-align: center; min-height: 250px; padding: 2rem;">
                    <div style="font-size: 2rem; margin-bottom: 1rem; filter: drop-shadow(0 0 5px rgba(255, 0, 127, 0.5));">🎯</div>
                    <div class="game-title" style="color: var(--accent-pink);">Custom Slot ${slotNumber}</div>
                    <p style="font-size: 0.8rem; color: var(--text-muted); line-height: 1.4; margin-bottom: 1.25rem;">No custom game tracked in this slot.</p>
                    <button class="btn-secondary" onclick="document.getElementById('custom-game-${slotNumber - 12}').focus()" style="font-size: 0.75rem; padding: 0.4rem 0.8rem; border-radius: 6px;">Configure Game ➔</button>
                </div>
            `;
        }

        function createGameCardHTML(g) {
            const twitchV = g.twitch_viewers || 0;
            const youtubeV = g.youtube_viewers || 0;
            const totalV = twitchV + youtubeV;
            const twitchPercent = totalV > 0 ? Math.round((twitchV / totalV) * 100) : 0;
            const youtubePercent = 100 - twitchPercent;

            // Tier-based badge
            let tierBadge;
            const tier = g.tier || (g.custom ? 'custom' : 'sponsored');
            if (tier === 'trending') {
                tierBadge = `<span class="zeitgeist-badge" style="background: linear-gradient(135deg, #10b981, #06b6d4);">🔥 Trending</span>`;
            } else if (tier === 'custom') {
                tierBadge = `<span class="zeitgeist-badge" style="background: linear-gradient(135deg, #ec4899, #f43f5e);">🎯 Custom</span>`;
            } else if (tier === 'editors_pick') {
                tierBadge = `<span class="zeitgeist-badge" style="background: linear-gradient(135deg, #ffe600, #d4af37); color: black; box-shadow: 0 0 10px rgba(255, 230, 0, 0.4);">⭐ Editor's Pick</span>`;
            } else {
                tierBadge = `<span class="zeitgeist-badge" style="background: linear-gradient(135deg, #8b5cf6, #6366f1);">📌 Sponsored</span>`;
            }

            // Data quality badge
            let qualityBadge;
            const dq = g.data_quality || 'no_live_data';
            if (dq === 'live') {
                qualityBadge = `<span class="zeitgeist-badge" style="background: rgba(16,185,129,0.25); border: 1px solid #10b981; color: #10b981; font-size: 0.65rem;">✓ Live Data</span>`;
            } else if (dq === 'estimated') {
                qualityBadge = `<span class="zeitgeist-badge" style="background: rgba(251,191,36,0.25); border: 1px solid #fbbf24; color: #fbbf24; font-size: 0.65rem;">~ Estimated</span>`;
            } else {
                qualityBadge = `<span class="zeitgeist-badge" style="background: rgba(239,68,68,0.25); border: 1px solid #ef4444; color: #ef4444; font-size: 0.65rem;">✗ No Live Data</span>`;
            }

            // Viewer count display
            const twitchDisplay = twitchV > 0 ? twitchV.toLocaleString() : '—';
            const youtubeDisplay = youtubeV > 0 ? youtubeV.toLocaleString() : '—';
            const totalDisplay = totalV > 0 ? totalV.toLocaleString() : '—';

            let streamersHTML = '';
            if (g.top_streamers && g.top_streamers.length > 0) {
                streamersHTML = `
                    <div class="top-streamers-section" style="margin-top: 0.75rem; padding-top: 0.75rem; border-top: 1px dashed rgba(255, 255, 255, 0.1);">
                        <div style="font-size: 0.7rem; color: var(--text-muted); margin-bottom: 0.4rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em;">📡 Top Live Streamers</div>
                        <div style="display: flex; gap: 0.35rem; flex-wrap: wrap;">
                `;
                g.top_streamers.forEach(s => {
                    const viewerDisplay = s.viewer_count >= 1000 ? (s.viewer_count / 1000).toFixed(1) + 'k' : s.viewer_count;
                    const titleEscaped = (s.title || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
                    const nameEscaped = (s.user_name || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '&quot;');
                    const nameText = escapeHTML(s.user_name);
                    const isYT = s.platform === 'youtube';
                    let twitchUser = s.user_login || '';
                    if (twitchUser.startsWith('@')) {
                        twitchUser = twitchUser.substring(1);
                    }
                    const href = isYT ? `https://youtube.com/channel/${encodeURIComponent(s.user_login)}` : `https://twitch.tv/${encodeURIComponent(twitchUser)}`;
                    const tagStyle = isYT ? `
                                    display: inline-flex;
                                    align-items: center;
                                    font-size: 0.72rem;
                                    background: rgba(239, 68, 68, 0.15);
                                    border: 1px solid rgba(239, 68, 68, 0.3);
                                    color: #f87171;
                                    padding: 0.15rem 0.4rem;
                                    border-radius: 6px;
                                    text-decoration: none;
                                    transition: all 0.2s ease;
                    ` : `
                                    display: inline-flex;
                                    align-items: center;
                                    font-size: 0.72rem;
                                    background: rgba(168, 85, 247, 0.15);
                                    border: 1px solid rgba(168, 85, 247, 0.3);
                                    color: #c084fc;
                                    padding: 0.15rem 0.4rem;
                                    border-radius: 6px;
                                    text-decoration: none;
                                    transition: all 0.2s ease;
                    `;
                    const icon = isYT ? '🔴' : '👾';

                    // Fetch Star Map Vibe Tribe & Bellwether info if loaded
                    const ecoInfo = typeof getStreamerEcosystemInfo === 'function' ? getStreamerEcosystemInfo(s.user_login) : null;
                    let colorDot = '';
                    let bellBadge = '';
                    if (ecoInfo) {
                        colorDot = `<span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:${ecoInfo.tribeColor}; margin-right:4px;" title="Vibe Tribe: ${escapeHTML(ecoInfo.tribeLabel)}"></span>`;
                        const rankIdx = typeof topBellwethersList !== 'undefined' ? topBellwethersList.indexOf(s.user_login.toLowerCase()) : -1;
                        if (rankIdx !== -1) {
                            bellBadge = `<span style="background:var(--accent-yellow); color:#000; font-family:'Share Tech Mono'; font-size:0.55rem; font-weight:bold; padding:0rem 0.2rem; margin-left:0.25rem; border-radius:2px;" title="Bellwether Rank #${rankIdx+1} in ecosystem">⚡#${rankIdx+1}</span>`;
                        }
                    }

                    streamersHTML += `
                            <div class="streamer-tag-container" style="position: relative; display: inline-block;">
                                <a href="${href}" target="_blank" class="streamer-tag" style="${tagStyle}" onmouseover="showStreamerTooltip(this, '${titleEscaped}', '${nameEscaped}', ${s.viewer_count})" onmouseout="hideStreamerTooltip()">
                                     ${colorDot}${icon} ${nameText} (${viewerDisplay})${bellBadge}
                                </a>
                            </div>
                    `;
                });
                streamersHTML += `
                        </div>
                    </div>
                `;
            }

            // Viewership History Sparkline SVG
            let sparklineHTML = '';
            if (g.history && g.history.length > 1) {
                const viewersArr = g.history.map(pt => currentSparklineMode === 'twitch' ? (pt.twitch_viewers || 0) : (pt.viewers || 0));
                const minVal = Math.min(...viewersArr);
                const maxVal = Math.max(...viewersArr);
                const range = maxVal - minVal;

                const width = 120;
                const height = 30;
                const points = [];

                for (let i = 0; i < g.history.length; i++) {
                    const x = (i / (g.history.length - 1)) * width;
                    let y = height / 2;
                    const val = currentSparklineMode === 'twitch' ? (g.history[i].twitch_viewers || 0) : (g.history[i].viewers || 0);
                    if (range > 0) {
                        y = height - ((val - minVal) / range) * (height - 4) - 2;
                    }
                    points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
                }

                const polylinePoints = points.join(' ');
                const isUp = viewersArr[viewersArr.length - 1] >= viewersArr[0];
                const strokeColor = isUp ? '#10b981' : '#f43f5e';

                sparklineHTML = `
                    <div style="margin-top: 0.75rem; padding-top: 0.5rem; display: flex; align-items: center; justify-content: space-between; border-top: 1px dashed rgba(255, 255, 255, 0.08);">
                        <span style="font-size: 0.7rem; color: var(--text-muted); font-weight: 600; text-transform: uppercase;">📈 24h Trend</span>
                        <svg width="${width}" height="${height}" style="overflow: visible;">
                            <polyline
                                fill="none"
                                stroke="${strokeColor}"
                                stroke-width="2.2"
                                stroke-linecap="round"
                                stroke-linejoin="round"
                                points="${polylinePoints}"
                            />
                        </svg>
                    </div>
                `;
            }

            const isEditorsPick = tier === 'editors_pick';
            const cardStyle = isEditorsPick ? 'border-color: #ffd700 !important; box-shadow: 0 0 15px rgba(255, 215, 0, 0.4) !important;' : '';

            const categoryLower = (g.category || '').toLowerCase();
            const tags = g.tags || [];
            const hasHypeTag = tags.some(t => {
                const tl = t.toLowerCase();
                return tl.includes('action') || tl.includes('fps') || tl.includes('competitive') || tl.includes('pvp') || tl.includes('shooter') || tl.includes('moba');
            });
            const hasCozyTag = tags.some(t => {
                const tl = t.toLowerCase();
                return tl.includes('cozy') || tl.includes('relaxing') || tl.includes('simulation') || tl.includes('cooperative');
            });

            let vibeLabel = "Cozy Chill";
            let vibeColor = "linear-gradient(135deg, #0284c7, #0ea5e9)"; // sky blue
            if (hasHypeTag || (!hasCozyTag && (categoryLower.includes('fps') || categoryLower.includes('moba') || categoryLower.includes('action') || categoryLower.includes('battle') || totalV > 90000))) {
                vibeLabel = "Sweaty Hype";
                vibeColor = "linear-gradient(135deg, #e11d48, #f43f5e)"; // rose red
            }

            const steamPlayerCount = g.steam_player_count;
            const steamStatHTML = steamPlayerCount !== undefined && steamPlayerCount !== null && steamPlayerCount > 0
                ? `<div class="stat-box" title="Steam concurrent player count">
                       <div class="stat-value" style="color: var(--accent-cyan);">${steamPlayerCount >= 1000 ? (steamPlayerCount / 1000).toFixed(1) + 'k' : steamPlayerCount}</div>
                       <div class="stat-label">Steam Players</div>
                   </div>`
                : '';

             const coverHTML = g.cover_url
                 ? `<img src="${g.cover_url.replace('{width}', '80').replace('{height}', '106')}" alt="${g.title} cover" style="width: 80px; height: 106px; object-fit: cover; border-radius: 6px; border: 1px solid rgba(255,255,255,0.12); margin-right: 1rem; box-shadow: 0 4px 8px rgba(0,0,0,0.4);" />`
                 : '';

             return `
                 <div class="game-card" style="${cardStyle}">
                     <div style="display:flex;gap:0.4rem;flex-wrap:wrap;margin-bottom:0.5rem;">
                         ${tierBadge}
                         ${qualityBadge}
                         <span class="zeitgeist-badge" style="background: ${vibeColor}; border: 1px solid rgba(255,255,255,0.15); color: #fff;">🍃 ${vibeLabel}</span>
                     </div>
                     <div style="display: flex; align-items: flex-start; margin-bottom: 0.75rem;">
                         ${coverHTML}
                         <div style="flex: 1;">
                             <div class="game-title">${g.title}</div>
                             <div class="game-category" style="color: var(--accent-cyan); font-size: 0.8rem; margin-top: 0.25rem; font-family: 'Share Tech Mono', monospace;">${g.category}</div>
                         </div>
                     </div>

                    <!-- Platform viewer partition bar -->
                    <div style="margin: 1rem 0 0.5rem 0;">
                        <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; color: var(--text-muted); margin-bottom: 0.25rem;">
                            <span style="color: #a855f7;">Twitch: ${twitchDisplay}</span>
                            <span style="font-size: 0.65rem; color: var(--text-muted); opacity: 0.75; font-family: 'Share Tech Mono';" title="Last updated: ${g.refreshed_at ? new Date(g.refreshed_at * 1000).toLocaleString() : (lastCacheRefreshedAt ? new Date(lastCacheRefreshedAt * 1000).toLocaleString() : 'Not updated')}">${formatTime(g.refreshed_at)}</span>
                            <span style="color: #f43f5e;">YT: ${youtubeDisplay}</span>
                        </div>
                        <div style="width: 100%; height: 6px; background: rgba(255,255,255,0.1); border-radius: 9999px; overflow: hidden; display: flex;">
                            ${totalV > 0 ? `<div style="width: ${twitchPercent}%; background: #a855f7; height: 100%;"></div><div style="width: ${youtubePercent}%; background: #f43f5e; height: 100%;"></div>` : `<div style="width:100%;background:rgba(255,255,255,0.08);height:100%;"></div>`}
                        </div>
                    </div>

                    <div class="game-stats" style="${steamStatHTML ? 'grid-template-columns: repeat(3, 1fr);' : ''}">
                        <div class="stat-box">
                            <div class="stat-value">${totalDisplay}</div>
                            <div class="stat-label">Total Viewers</div>
                        </div>
                        <div class="stat-box">
                            <div class="stat-value">${g.stream_count || 0}</div>
                            <div class="stat-label">Active Channels${dq !== 'live' ? ' †' : ''}</div>
                        </div>
                        ${steamStatHTML}
                    </div>

                    ${sparklineHTML}

                    ${streamersHTML}

                    <div style="display: flex; justify-content: space-between; align-items: center; margin-top: 0.75rem;">
                        <span class="provenance-tag">Source: ${g.source || 'Unknown'}</span>
                        ${g.source_url ? `<a href="${g.source_url}" target="_blank" style="font-size: 0.75rem; color: var(--accent-cyan); text-decoration: none; font-weight: 500;">View on Platform ➔</a>` : ''}
                    </div>

                    <button class="btn-news" onclick="viewNews('${g.title.replace(/'/g, "\\'")}')">🔍 View News & Updates</button>
                </div>
            `;
        }

        function getActiveSponsoredGames() {
            if (sponsoredGamesList.length === 0) return [null, null];
            const count = sponsoredGamesList.length;
            const g1 = sponsoredGamesList[currentSponsoredIndex % count];
            const g2 = sponsoredGamesList[(currentSponsoredIndex + 1) % count];
            return [g1, g2];
        }

        function startSponsoredRotation() {
            if (sponsoredIntervalId) clearInterval(sponsoredIntervalId);
            sponsoredIntervalId = setInterval(() => {
                if (sponsoredGamesList.length > 2) {
                    currentSponsoredIndex = (currentSponsoredIndex + 1) % sponsoredGamesList.length;
                    renderGamesList();
                }
            }, 8000);
        }

        function renderGamesList() {
            const categoryEl = document.getElementById('category-selector');
            const category = categoryEl ? categoryEl.value : 'overall';

            const gridContainer = document.getElementById('dashboard-grid');
            if (gridContainer) gridContainer.innerHTML = '';

            const trendingGames = cachedGamesList.filter(g => g.tier === 'trending');
            const customGames = cachedGamesList.filter(g => g.custom || g.tier === 'custom');
            sponsoredGamesList = cachedGamesList.filter(g => g.tier === 'sponsored' || (!g.custom && g.tier !== 'trending' && g.tier !== 'editors_pick'));
            const editorsPickGame = cachedGamesList.find(g => g.tier === 'editors_pick');

            // 1. Filter Trending (filtered, top 10)
            const filteredTrending = trendingGames.filter(g => matchesCategory(g.category, g.title, category));
            const topTrending = filteredTrending.slice(0, 10);

            const gridHTML = [];

            // Add top 10 trending slots
            for (let i = 0; i < 10; i++) {
                if (i < topTrending.length) {
                    gridHTML.push(createGameCardHTML(topTrending[i]));
                } else {
                    gridHTML.push(`
                        <div class="game-card" style="border: 1px dashed rgba(255,255,255,0.1) !important; display: flex; align-items: center; justify-content: center; min-height: 250px; color: var(--text-muted);">
                            <span>Empty Trending Slot</span>
                        </div>
                    `);
                }
            }

            // 2. Add Sponsored slots (11-12)
            const [sp1, sp2] = getActiveSponsoredGames();
            [sp1, sp2].forEach(sp => {
                if (sp) {
                    gridHTML.push(createGameCardHTML(sp));
                } else {
                    gridHTML.push(`
                        <div class="game-card" style="border: 1px dashed rgba(255,255,255,0.1) !important; display: flex; align-items: center; justify-content: center; min-height: 250px; color: var(--text-muted);">
                            <span>Rotating Sponsored Slot</span>
                        </div>
                    `);
                }
            });

            // 3. Add Custom slots (13-14)
            const custom1 = customGames[0] || null;
            const custom2 = customGames[1] || null;
            [custom1, custom2].forEach((cust, idx) => {
                const slotNum = 13 + idx;
                if (cust) {
                    gridHTML.push(createGameCardHTML(cust));
                } else {
                    gridHTML.push(createPlaceholderCardHTML(slotNum));
                }
            });

            // 4. Add Editor's Pick slot (15)
            if (editorsPickGame) {
                gridHTML.push(createGameCardHTML(editorsPickGame));
            } else {
                // Inline default fallback Forza Horizon 6 card if cache is not fully updated yet
                gridHTML.push(createGameCardHTML({
                    title: "Forza Horizon 6",
                    category: "Racing",
                    avg_viewers: 35000,
                    twitch_viewers: 35000,
                    youtube_viewers: 0,
                    avg_length_hours: 3.5,
                    score: 85,
                    tier: "editors_pick",
                    source: "Config Fallback"
                }));
            }

            if (gridContainer) {
                gridContainer.innerHTML = gridHTML.join('');
            }
        }

        function handleSparklineModeChange() {
            const selector = document.getElementById('sparkline-mode-selector');
            if (selector) {
                currentSparklineMode = selector.value;
                renderGamesList();
            }
        }

        let topBellwethersList = [];

        function computeTopBellwethers() {
            if (!starmapData || !starmapData.clusters) return;
            const allMembers = [];
            for (const clusterId in starmapData.clusters) {
                const cluster = starmapData.clusters[clusterId];
                if (cluster.members) {
                    cluster.members.forEach(m => {
                        allMembers.push({
                            handle: m.handle.toLowerCase(),
                            score: m.bellwether_score || 0
                        });
                    });
                }
            }
            allMembers.sort((a, b) => b.score - a.score);
            topBellwethersList = allMembers.slice(0, 10).map(m => m.handle);
        }

        function getStreamerEcosystemInfo(handle) {
            if (!starmapData || !starmapData.clusters) return null;
            const cleanHandle = handle.toLowerCase().trim();
            for (const clusterId in starmapData.clusters) {
                const cluster = starmapData.clusters[clusterId];
                if (cluster.members) {
                    const member = cluster.members.find(m => m.handle.toLowerCase() === cleanHandle);
                    if (member) {
                        return {
                            tribeColor: cluster.color,
                            tribeLabel: cluster.label,
                            bellwetherScore: member.bellwether_score
                        };
                    }
                }
            }
            return null;
        }

        async function fetchStarMapEcosystem() {
            try {
                const response = await fetch("/api/starmap");
                if (response.ok) {
                    const data = await response.json();
                    if (data && data.clusters) {
                        starmapData = data;
                        computeTopBellwethers();
                        // Re-render the games list with newly loaded starmap data
                        renderGamesList();
                    }
                }
            } catch (err) {
                console.error("Error loading ecosystem snapshot for cards:", err);
            }
        }

        async function fetchGames() {
            const key = checkKey();
            if (!key && !serverKeyConfigured) return;

            // Trigger background ecosystem retrieval
            fetchStarMapEcosystem();

            try {
                const res = await fetch('/api/games');
                if (res.status === 401) {
                    logout();
                    return;
                }
                const games = await res.json();
                cachedGamesList = games;

                if (!initialSyncDone) {
                    initialSyncDone = true;

                    const cg1 = localStorage.getItem("custom_game_1") || "";
                    const cg2 = localStorage.getItem("custom_game_2") || "";

                    const serverCustomGames = games.filter(g => g.custom || g.tier === 'custom').map(g => g.title.toLowerCase());
                    const clientCustomGames = [];
                    if (cg1.trim()) clientCustomGames.push(cg1.trim().toLowerCase());
                    if (cg2.trim()) clientCustomGames.push(cg2.trim().toLowerCase());

                    serverCustomGames.sort();
                    clientCustomGames.sort();

                    const arraysMatch = serverCustomGames.length === clientCustomGames.length &&
                                        serverCustomGames.every((val, index) => val === clientCustomGames[index]);

                    if (!arraysMatch) {
                        if (serverCustomGames.length > 0) {
                            const customGamesObj = games.filter(g => g.custom || g.tier === 'custom');
                            localStorage.setItem("custom_game_1", customGamesObj[0] ? customGamesObj[0].title : "");
                            const input1 = document.getElementById('custom-game-1');
                            if (input1) input1.value = customGamesObj[0] ? customGamesObj[0].title : "";

                            localStorage.setItem("custom_game_2", customGamesObj[1] ? customGamesObj[1].title : "");
                            const input2 = document.getElementById('custom-game-2');
                            if (input2) input2.value = customGamesObj[1] ? customGamesObj[1].title : "";

                            loadCachedReport();
                        } else if (clientCustomGames.length > 0) {
                            console.log("Client custom games out of sync with server. Triggering scrape to sync.");
                            triggerScrape();
                        }
                    }
                }

                renderGamesList();
            } catch (err) {
                console.error(err);
            }
        }

        async function fetchCacheStatus() {
            try {
                const res = await fetch('/api/cache/status');
                if (!res.ok) return;
                const data = await res.json();
                const badge = document.getElementById('cache-status-badge');
                if (!badge) return;
                if (data.refreshed_at && data.refreshed_at > 0) {
                    const ageMin = Math.round(data.age_seconds / 60);
                    const staleIcon = data.is_stale ? '⚠️' : '⏱';
                    badge.textContent = `${staleIcon} Cache: ${ageMin}m ago`;
                    badge.style.color = data.is_stale ? '#f59e0b' : 'var(--text-muted)';
                    badge.style.borderColor = data.is_stale ? 'rgba(245, 158, 11, 0.3)' : 'var(--border-color)';

                    if (lastCacheRefreshedAt !== 0 && data.refreshed_at > lastCacheRefreshedAt) {
                        console.log("Server cache refreshed. Reloading metrics and report.");
                        fetchGames();
                        loadCachedReport();
                    }
                    lastCacheRefreshedAt = data.refreshed_at;
                } else {
                    badge.textContent = '⏳ Cache: warming up...';
                }
            } catch (err) {
                // silently ignore — non-critical
            }
        }

        async function triggerScrape() {
            const key = checkKey();
            if (!key && !serverKeyConfigured) return;

            const cg1 = localStorage.getItem("custom_game_1") || "";
            const cg2 = localStorage.getItem("custom_game_2") || "";
            const custom_games = [];
            if (cg1) custom_games.push(cg1);
            if (cg2) custom_games.push(cg2);

            const btn = document.getElementById('btn-collect');
            btn.innerHTML = '<span class="loader" style="width:1rem; height:1rem; border-width:2px;"></span> Fetching...';
            btn.disabled = true;

            const terminalCard = document.getElementById('terminal-card');
            const terminalDisplay = document.getElementById('terminal-display');
            terminalCard.style.display = 'block';

            if (custom_games.length === 0) {
                terminalDisplay.textContent = 'Clearing custom games from cache...';
            } else {
                terminalDisplay.textContent = `Scraping viewership: ${custom_games.join(', ')}...`;
            }

            try {
                const searchModel = localStorage.getItem('gemini_model_search') || 'gemma-4-31b-it';
                const res = await fetch('/api/collect', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Gemini-Search-Model': searchModel
                    },
                    body: JSON.stringify({ custom_games })
                });

                if (!res.ok) {
                    const text = await res.text();
                    let errMsg = 'Internal Server Error';
                    try {
                        const errJson = JSON.parse(text);
                        if (errJson && errJson.detail) errMsg = errJson.detail;
                    } catch(e) {}
                    terminalDisplay.textContent = `Error: ${errMsg}`;
                    document.getElementById('pipeline-dot').style.background = '#ef4444';
                    await fetchGames();
                    setTimeout(() => { terminalCard.style.display = 'none'; }, 5000);
                    return;
                }

                const data = await res.json();

                if (data.status === 'success' && data.logs) {
                    let logIdx = 0;
                    const logInterval = setInterval(() => {
                        if (logIdx < data.logs.length) {
                            terminalDisplay.textContent = data.logs[logIdx];
                            logIdx++;
                        } else {
                            clearInterval(logInterval);
                            terminalDisplay.textContent = '✓ Data pipeline complete';
                            document.getElementById('pipeline-dot').style.animation = 'none';
                            document.getElementById('pipeline-dot').style.opacity = '1';
                            fetchGames().then(() => {
                                // After custom scrape, re-run comparison to generate the unified report
                                fetchComparison();
                            });
                            setTimeout(() => {
                                terminalCard.style.display = 'none';
                                document.getElementById('pipeline-dot').style.animation = 'pulse-dot 1.5s ease-in-out infinite';
                            }, 3000);
                        }
                    }, 120);
                } else {
                    terminalDisplay.textContent = 'Error: Failed to compile scraper logs.';
                    document.getElementById('pipeline-dot').style.background = '#ef4444';
                    await fetchGames();
                    setTimeout(() => { terminalCard.style.display = 'none'; }, 5000);
                }
            } catch (err) {
                console.error(err);
                terminalDisplay.textContent = 'Error: Connection lost — ' + err.message;
                document.getElementById('pipeline-dot').style.background = '#ef4444';
                setTimeout(() => { terminalCard.style.display = 'none'; }, 5000);
            } finally {
                setButtonCooldown(btn, 'Refresh Custom Games');
            }
        }

        let activeNewsGame = "";

        async function viewNews(game, forceRefresh = false) {
            activeNewsGame = game;
            const key = checkKey();
            if (!key && !serverKeyConfigured) return;

            const modal = document.getElementById('news-modal');
            const title = document.getElementById('news-modal-title');
            const content = document.getElementById('news-modal-content');
            const refreshBtn = document.getElementById('btn-refresh-news');

            title.innerText = `Latest News for: ${game}`;
            content.innerHTML = '<div style="text-align: center; padding: 2rem;"><span class="loader"></span><p style="margin-top: 1rem; color: var(--text-muted);">Fetching search-grounded updates...</p></div>';
            modal.style.display = 'flex';

            if (refreshBtn) {
                refreshBtn.disabled = true;
                refreshBtn.innerHTML = '<span class="loader" style="width:0.8rem; height:0.8rem; border-width:2px;"></span> Searching...';
            }

            try {
                const searchModel = localStorage.getItem('gemini_model_search') || 'gemma-4-31b-it';
                const url = `/api/news?game=${encodeURIComponent(game)}` + (forceRefresh ? '&refresh=true' : '');
                const res = await fetch(url, {
                    headers: {
                        'X-Gemini-Search-Model': searchModel
                    }
                });
                const data = await res.json();
                content.innerHTML = '';

                if (data.news && data.news.length > 0) {
                    data.news.forEach(item => {
                        content.innerHTML += `
                            <div style="background: rgba(30, 41, 59, 0.6); border: 1px solid var(--border-color); border-radius: 12px; padding: 1.25rem;">
                                <h4 style="color: var(--text-main); font-size: 1.05rem; margin-bottom: 0.5rem;">${item.title}</h4>
                                <p style="color: var(--text-muted); font-size: 0.9rem; line-height: 1.5; margin-bottom: 0.75rem;">${item.summary}</p>
                                <a href="${item.url}" target="_blank" style="color: var(--accent-cyan); font-size: 0.85rem; font-weight: 500; text-decoration: none; display: inline-flex; align-items: center; gap: 0.25rem;">
                                    Read full article ➔
                                </a>
                            </div>
                        `;
                    });
                } else {
                    content.innerHTML = '<p style="color: var(--text-muted); text-align: center; padding: 2rem;">No recent articles found.</p>';
                }
            } catch (err) {
                console.error(err);
                content.innerHTML = '<p style="color: #f43f5e; text-align: center; padding: 2rem;">Failed to fetch news updates.</p>';
            } finally {
                if (refreshBtn) {
                    setButtonCooldown(refreshBtn, 'Perform Fresh Search');
                }
            }
        }

        function closeNewsModal() {
            document.getElementById('news-modal').style.display = 'none';
        }

        function getVisibleGames() {
            const categoryEl = document.getElementById('category-selector');
            const category = categoryEl ? categoryEl.value : 'overall';
            const trendingGames = cachedGamesList.filter(g => g.tier === 'trending');
            const customGames = cachedGamesList.filter(g => g.custom || g.tier === 'custom');
            const filteredTrending = trendingGames.filter(g => matchesCategory(g.category, g.title, category));
            const topTrending = filteredTrending.slice(0, 10);
            
            const visible = [];
            const seen = new Set();
            
            // 1. Custom games
            customGames.forEach(g => {
                const key = g.title.toLowerCase();
                if (!seen.has(key)) {
                    seen.add(key);
                    visible.push({ title: g.title, category: g.category, tier: 'custom', custom: true });
                }
            });
            
            // 2. Active Sponsored game
            const activeSponsored = sponsoredGamesList[currentSponsoredIndex];
            if (activeSponsored) {
                const key = activeSponsored.title.toLowerCase();
                if (!seen.has(key)) {
                    seen.add(key);
                    visible.push({ title: activeSponsored.title, category: activeSponsored.category, tier: 'sponsored', custom: false });
                }
            }
            
            // 3. Top trending games
            topTrending.forEach(g => {
                const key = g.title.toLowerCase();
                if (!seen.has(key)) {
                    seen.add(key);
                    visible.push({ title: g.title, category: g.category, tier: 'trending', custom: false });
                }
            });
            
            return visible;
        }



        async function renderPleasantFailure(displayElement, errorMessage) {
            displayElement.innerHTML = `
                <div class="pleasant-failure-container" style="
                    background: var(--card-bg);
                    border: 2px solid var(--accent-pink) !important;
                    border-radius: 0px !important;
                    padding: 2.5rem;
                    box-shadow: 0 0 15px rgba(255, 0, 127, 0.2);
                    text-align: center;
                    margin-bottom: 2rem;
                ">
                    <!-- Subtle anomaly notice -->
                    <div style="
                        display: inline-flex;
                        align-items: center;
                        gap: 0.75rem;
                        background: rgba(255, 0, 127, 0.1);
                        border: 1px solid rgba(255, 0, 127, 0.4);
                        padding: 0.5rem 1.25rem;
                        border-radius: 0px !important;
                        margin-bottom: 1.5rem;
                    ">
                        <span style="font-size: 1rem; color: var(--accent-pink);">⚠️</span>
                        <span style="font-size: 0.85rem; color: var(--text-main); font-weight: bold; letter-spacing: 0.05em; text-transform: uppercase;">
                            ADVISOR ANOMALY DETECTED
                        </span>
                    </div>

                    <h3 style="
                        color: var(--accent-cyan);
                        font-size: 1.6rem;
                        margin-bottom: 0.75rem;
                        text-transform: uppercase;
                        letter-spacing: 0.05em;
                    ">
                        Recalibrating Stream Analytics
                    </h3>
                    
                    <p style="
                        color: var(--text-muted);
                        font-size: 0.95rem;
                        line-height: 1.6;
                        max-width: 600px;
                        margin: 0 auto 1.75rem auto;
                    ">
                        We encountered a calibration issue generating the comparative report (${errorMessage}). 
                        The advisor will auto-retry on the next interval. In the meantime, browse these live industry news updates to keep your stream strategy sharp!
                    </p>

                    <div style="display: inline-flex; justify-content: center; gap: 1rem; margin-bottom: 2.5rem;">
                        <button class="btn-secondary" onclick="checkKey() ? fetchComparison(true) : loadCachedReport(true)" style="
                            padding: 0.6rem 1.5rem;
                            font-size: 0.9rem;
                            border-radius: 0px !important;
                            transition: all 0.3s ease;
                        ">
                            🔄 Retry Generation
                        </button>
                        <button class="btn-secondary" onclick="window.location.reload()" style="
                            padding: 0.6rem 1.5rem;
                            font-size: 0.9rem;
                            border-radius: 0px !important;
                            transition: all 0.3s ease;
                        ">
                            🖥️ Refresh Page
                        </button>
                    </div>

                    <!-- Rolling News Section -->
                    <div style="
                        border-top: 1px dashed rgba(255, 255, 255, 0.1);
                        padding-top: 2rem;
                        text-align: left;
                    ">
                        <h4 style="
                            font-size: 1.1rem;
                            color: var(--accent-cyan);
                            margin-bottom: 1.25rem;
                            text-transform: uppercase;
                            letter-spacing: 0.05em;
                        ">
                            📰 Live Industry news
                        </h4>
                        
                        <div id="failure-news-feed" style="
                            display: flex;
                            flex-direction: column;
                            gap: 1.25rem;
                            min-height: 150px;
                        ">
                            <div style="text-align: center; padding: 2rem;">
                                <span class="loader" style="width: 1.5rem; height: 1.5rem; border-width: 2px; border-radius: 50%;"></span>
                                <p style="color: var(--text-muted); font-size: 0.85rem; margin-top: 0.75rem; text-transform: uppercase;">Retrieving sector updates...</p>
                            </div>
                        </div>
                    </div>
                </div>
            `;

            try {
                const res = await fetch('/api/news/random?limit=3');
                if (!res.ok) throw new Error("Status " + res.status);
                const data = await res.json();
                
                const feed = document.getElementById('failure-news-feed');
                if (feed) {
                    feed.innerHTML = '';
                    if (data.articles && data.articles.length > 0) {
                        data.articles.forEach(art => {
                            const authorText = art.author ? `<span style="color: var(--text-muted); font-size: 0.75rem; text-transform: uppercase;">Author: ${art.author}</span>` : '';
                            const gameBadge = art.game ? `<span class="zeitgeist-badge" style="background: rgba(0, 180, 216, 0.15); border: 1px solid var(--accent-cyan); color: var(--accent-cyan); font-size: 0.65rem; padding: 0.1rem 0.4rem; border-radius: 0px !important;">${art.game}</span>` : '';
                            
                            feed.innerHTML += `
                                <div class="failure-news-item" style="
                                    background: rgba(9, 9, 17, 0.6);
                                    border: 1px solid var(--border-color);
                                    border-radius: 0px !important;
                                    padding: 1.25rem;
                                    transition: all 0.3s ease;
                                    display: flex;
                                    flex-direction: column;
                                    gap: 0.5rem;
                                " onmouseover="this.style.borderColor='var(--accent-pink)'; this.style.boxShadow='0 0 10px rgba(255, 0, 127, 0.2)';" onmouseout="this.style.borderColor='var(--border-color)'; this.style.boxShadow='none';">
                                    <div style="display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem;">
                                        <h5 style="margin: 0; font-size: 1rem; font-weight: bold; color: var(--text-main); line-height: 1.4; text-transform: uppercase;">
                                            <a href="${art.url}" target="_blank" style="color: var(--text-main); text-decoration: none; transition: color 0.2s;" onmouseover="this.style.color='var(--accent-pink)'" onmouseout="this.style.color='var(--text-main)'">
                                                ${art.title}
                                            </a>
                                        </h5>
                                        ${gameBadge}
                                    </div>
                                    ${authorText}
                                    <p style="margin: 0.25rem 0 0 0; font-size: 0.85rem; color: var(--text-muted); line-height: 1.5;">
                                        ${art.summary}
                                    </p>
                                </div>
                            `;
                        });
                    } else {
                        feed.innerHTML = '<p style="color: var(--text-muted); font-size: 0.85rem; text-align: center; padding: 1.5rem; text-transform: uppercase;">No updates compiled.</p>';
                    }
                }
            } catch (err) {
                console.error(err);
                const feed = document.getElementById('failure-news-feed');
                if (feed) {
                    feed.innerHTML = '<p style="color: var(--accent-pink); font-size: 0.85rem; text-align: center; padding: 1.5rem; text-transform: uppercase;">Offline — updates unavailable.</p>';
                }
            }
        }

        async function loadCachedReport(showLoader = true) {
            // Page-load path: fetch the cached report via GET (no regeneration)
            const display = document.getElementById('comparison-display');
            const cacheBadge = document.getElementById('report-cache-badge');
            const btn = document.getElementById('btn-compare');

            if (showLoader) {
                display.innerHTML = '<div data-loading="true" style="text-align: center; padding: 2rem;"><span class="loader"></span><p style="margin-top: 1rem; color: var(--text-muted);">Loading cached report...</p></div>';
            }

            const cg1 = localStorage.getItem("custom_game_1") || "";
            const cg2 = localStorage.getItem("custom_game_2") || "";
            const custom_games = [];
            if (cg1.trim()) custom_games.push(cg1.trim());
            if (cg2.trim()) custom_games.push(cg2.trim());

            const categoryEl = document.getElementById('category-selector');
            const category = categoryEl ? categoryEl.value : 'overall';

            // Build query URL with parameters
            let url = `/api/compare?category=${encodeURIComponent(category)}`;
            if (custom_games.length > 0) {
                const params = custom_games.map(g => `custom_games=${encodeURIComponent(g)}`).join('&');
                url += '&' + params;
            }

            try {
                const res = await fetch(url);
                const data = await res.json();

                if (data.report) {
                    if (data.report.includes("Error generating") || data.report.includes("Error executing") || data.report.includes("color: #ef4444") || data.report.includes("color: #f43f5e")) {
                        renderPleasantFailure(display, "Service Recalibration");
                    } else {
                        display.innerHTML = data.report;
                        const isLoading = display.querySelector('[data-loading="true"]') !== null;
                        if (isLoading) {
                            if (cacheBadge) cacheBadge.style.display = 'none';
                            if (comparisonPollTimeout) clearTimeout(comparisonPollTimeout);
                            comparisonPollTimeout = setTimeout(() => loadCachedReport(false), 3000);
                        } else {
                            if (cacheBadge) cacheBadge.style.display = 'inline-block';
                            if (btn) {
                                btn.disabled = false;
                                btn.innerHTML = 'Re-run with Custom';
                            }
                        }
                    }
                } else {
                    display.innerHTML = '<p style="color: var(--text-muted); text-align: center;">No cached report yet. Click "Re-run with Custom" to generate one, or wait for the hourly refresh.</p>';
                    if (cacheBadge) cacheBadge.style.display = 'none';
                    if (btn) {
                        btn.disabled = false;
                        btn.innerHTML = 'Re-run with Custom';
                    }
                }
            } catch (err) {
                console.error(err);
                renderPleasantFailure(display, "Connection failure");
                if (cacheBadge) cacheBadge.style.display = 'none';
                if (btn) {
                    btn.disabled = false;
                    btn.innerHTML = 'Re-run with Custom';
                }
            }
        }

        async function handleCategoryChange() {
            const categoryEl = document.getElementById('category-selector');
            const category = categoryEl ? categoryEl.value : 'overall';
            localStorage.setItem('selected_category', category);

            renderGamesList();
            
            const display = document.getElementById('comparison-display');
            const cacheBadge = document.getElementById('report-cache-badge');
            
            // Try to load cached report first to prevent hitting rate limits on category switches
            display.innerHTML = '<div data-loading="true" style="text-align: center; padding: 2rem;"><span class="loader"></span><p style="margin-top: 1rem; color: var(--text-muted);">Checking cache for ' + category + '...</p></div>';
            
            const cg1 = localStorage.getItem("custom_game_1") || "";
            const cg2 = localStorage.getItem("custom_game_2") || "";
            const custom_games = [];
            if (cg1.trim()) custom_games.push(cg1.trim());
            if (cg2.trim()) custom_games.push(cg2.trim());

            let url = `/api/compare?category=${encodeURIComponent(category)}`;
            if (custom_games.length > 0) {
                const params = custom_games.map(g => `custom_games=${encodeURIComponent(g)}`).join('&');
                url += '&' + params;
            }

            try {
                const res = await fetch(url);
                const data = await res.json();

                if (data.report && !data.report.includes("Error generating") && !data.report.includes("Error executing") && !data.report.includes("color: #ef4444") && !data.report.includes("color: #f43f5e")) {
                    display.innerHTML = data.report;
                    const isLoading = display.querySelector('[data-loading="true"]') !== null;
                    if (isLoading) {
                        if (cacheBadge) cacheBadge.style.display = 'none';
                        if (comparisonPollTimeout) clearTimeout(comparisonPollTimeout);
                        comparisonPollTimeout = setTimeout(() => loadCachedReport(false), 3000);
                    } else {
                        if (cacheBadge) cacheBadge.style.display = 'inline-block';
                    }
                } else {
                    // No valid cache found. Auto-generate if key exists, otherwise show empty state.
                    if (checkKey()) {
                        fetchComparison(true);
                    } else {
                        display.innerHTML = '<p style="color: var(--text-muted); text-align: center;">No cached report yet. Click "Re-run with Custom" to generate one, or wait for the hourly refresh.</p>';
                        if (cacheBadge) cacheBadge.style.display = 'none';
                    }
                }
            } catch (err) {
                console.error(err);
                if (checkKey()) {
                    fetchComparison(true);
                } else {
                    renderPleasantFailure(display, "Connection failure");
                    if (cacheBadge) cacheBadge.style.display = 'none';
                }
            }
        }

        async function fetchComparison(showLoader = true) {
            // Button-click / post-scrape path: POST to trigger regeneration
            const key = checkKey();
            if (!key) {
                alert("A personal Gemini API key is required to generate custom comparison reports. Please click 'Connect Personal Key' in the top right to configure your key.");
                return;
            }

            const btn = document.getElementById('btn-compare');
            const display = document.getElementById('comparison-display');
            const cacheBadge = document.getElementById('report-cache-badge');

            const cg1 = localStorage.getItem("custom_game_1") || "";
            const cg2 = localStorage.getItem("custom_game_2") || "";
            const custom_games = [];
            if (cg1) custom_games.push(cg1);
            if (cg2) custom_games.push(cg2);

            const hasCustom = custom_games.length > 0;
            const categoryEl = document.getElementById('category-selector');
            const category = categoryEl ? categoryEl.value : 'overall';
            const visible_games = getVisibleGames();

            if (showLoader) {
                if (btn) {
                    btn.disabled = true;
                    btn.innerHTML = '<span class="loader" style="width:0.8rem; height:0.8rem; border-width:2px;"></span> ' + (hasCustom ? 'Generating with custom...' : 'Regenerating...');
                }
                display.innerHTML = '<div data-loading="true" style="text-align: center; padding: 2rem;"><span class="loader"></span><p style="margin-top: 1rem; color: var(--text-muted);">' + (hasCustom ? 'Generating report with custom games...' : 'Regenerating comparison report...') + '</p></div>';
            }

            try {
                const searchModel = localStorage.getItem('gemini_model_search') || 'gemma-4-31b-it';
                const analysisModel = localStorage.getItem('gemini_model_analysis') || 'gemma-4-31b-it';
                const res = await fetch('/api/compare', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Gemini-Search-Model': searchModel,
                        'X-Gemini-Analysis-Model': analysisModel
                    },
                    body: JSON.stringify({
                        custom_games,
                        category,
                        force_refresh: showLoader,
                        visible_games: visible_games
                    })
                });

                if (!res.ok) {
                    const text = await res.text();
                    let errMsg = 'Rate limit or calibration anomaly';
                    let isRateLimit = (res.status === 429);
                    try {
                        const errJson = JSON.parse(text);
                        if (errJson && errJson.detail) {
                            errMsg = errJson.detail;
                            if (errMsg.toLowerCase().includes("rate limit")) {
                                isRateLimit = true;
                            }
                        }
                    } catch(e) {}
                    const error = new Error(errMsg);
                    error.isRateLimit = isRateLimit;
                    throw error;
                }

                const data = await res.json();

                if (data.report) {
                    if (data.report.includes("Error generating") || data.report.includes("Error executing") || data.report.includes("color: #ef4444") || data.report.includes("color: #f43f5e")) {
                        renderPleasantFailure(display, "API rate limit or calibration error");
                    } else {
                        display.innerHTML = data.report;

                        const isLoading = display.querySelector('[data-loading="true"]') !== null;
                        if (isLoading) {
                            if (cacheBadge) cacheBadge.style.display = 'none';
                            if (comparisonPollTimeout) clearTimeout(comparisonPollTimeout);
                            comparisonPollTimeout = setTimeout(() => {
                                fetchComparison(false);
                            }, 3000);
                        } else {
                            if (cacheBadge) cacheBadge.style.display = 'inline-block';
                            setButtonCooldown(btn, 'Re-run with Custom');
                            // Refresh metrics cards
                            fetchGames();
                        }
                    }
                } else {
                    renderPleasantFailure(display, "No report payload received");
                    if (cacheBadge) cacheBadge.style.display = 'none';
                    setButtonCooldown(btn, 'Re-run with Custom');
                }
            } catch (err) {
                console.error(err);
                if (err.isRateLimit) {
                    // Show a non-fatal temporary notice
                    let notice = document.getElementById('rate-limit-notice');
                    if (!notice) {
                        notice = document.createElement('div');
                        notice.id = 'rate-limit-notice';
                        notice.style.cssText = 'background: rgba(255, 193, 7, 0.1); border: 1px dashed rgba(255, 193, 7, 0.3); color: var(--text-main); padding: 1rem; margin: 1rem 0; border-radius: 8px; font-size: 0.9rem; text-align: center;';
                        
                        const loader = display.querySelector('[data-loading="true"]');
                        if (loader) {
                            const p = loader.querySelector('p');
                            if (p) p.textContent = 'Checking active generation status (rate limited)...';
                        } else {
                            display.appendChild(notice);
                        }
                    }
                    notice.innerHTML = '⚠️ <strong>Rate limit active</strong>: A report is already generating or was recently updated. Checking status in a few seconds...';
                    
                    if (comparisonPollTimeout) clearTimeout(comparisonPollTimeout);
                    comparisonPollTimeout = setTimeout(() => {
                        const existingNotice = document.getElementById('rate-limit-notice');
                        if (existingNotice) existingNotice.remove();
                        loadCachedReport(false);
                    }, 3000);
                } else {
                    renderPleasantFailure(display, err.message || "Connection failure");
                }
                if (cacheBadge) cacheBadge.style.display = 'none';
                setButtonCooldown(btn, 'Re-run with Custom');
            }
        }

        function applySuggestion(text) {
            if (!checkKey()) {
                alert("A personal Gemini API key is required to use chatbot features. Please click 'Connect Personal Key' in the top right to get started.");
                return;
            }
            document.getElementById('chat-input').value = text;
            sendMessage();
        }

        function handleKey(e) {
            if (e.key === 'Enter') {
                sendMessage();
            } else if (e.key === 'Escape') {
                closeChat();
            }
        }

        async function sendMessage() {
            const key = checkKey();
            if (!key && !serverKeyConfigured) {
                logout();
                return;
            }

            const input = document.getElementById('chat-input');
            const sendBtn = document.querySelector('.btn-send');
            const text = input.value.trim();
            if (!text) return;

            input.value = '';
            if (input) input.disabled = true;
            if (sendBtn) sendBtn.disabled = true;

            const messages = document.getElementById('chat-messages');
            messages.innerHTML += `<div class="message user">${text}</div>`;
            messages.scrollTop = messages.scrollHeight;

            const typingId = 'typing-' + Date.now();
            messages.innerHTML += `<div class="message agent" id="${typingId}" style="max-width: 280px; width: 100%; padding: 0.5rem; background: rgba(0,0,0,0.25);"></div>`;
            renderAgentDiagnosticLoader(document.getElementById(typingId), 'chatbot');
            messages.scrollTop = messages.scrollHeight;

            try {
                const chatModel = localStorage.getItem('gemini_model_chat') || 'gemma-4-31b-it';
                const res = await fetch('/api/recommend', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Gemini-Chat-Model': chatModel
                    },
                    body: JSON.stringify({ query: text })
                });

                if (res.status === 401) {
                    logout();
                    return;
                }

                const data = await res.json();
                document.getElementById(typingId).remove();
                
                let messageHtml = `<div class="message agent">`;
                messageHtml += marked.parse(data.recommendation);
                if (data.reasoning) {
                    console.log("[Admin Agent Reasoning Trace]:\n" + data.reasoning);
                    messageHtml += `
                    <details class="arcade-debug" style="margin-top: 0.5rem; border-top: 1px dashed var(--border-color); padding-top: 0.5rem; font-size: 0.8rem; color: var(--text-muted);">
                        <summary style="cursor: pointer; font-family: 'Share Tech Mono', monospace; outline: none; user-select: none; color: var(--accent-cyan);">🛠️ SYSTEM REASONING TRACE</summary>
                        <pre style="white-space: pre-wrap; font-family: 'Share Tech Mono', monospace; background: rgba(0, 0, 0, 0.4); padding: 0.5rem; border-radius: 4px; margin-top: 0.25rem; border: 1px solid var(--border-color); max-height: 250px; overflow-y: auto;">${escapeHTML(data.reasoning)}</pre>
                    </details>`;
                }
                messageHtml += `</div>`;
                messages.innerHTML += messageHtml;

                if (data.refresh_dashboard) {
                    console.log("Chatbot modified dashboard metrics. Refreshing games and report.");
                    initialSyncDone = false;
                    await fetchGames();
                    await loadCachedReport();
                }
            } catch (err) {
                document.getElementById(typingId).remove();
                messages.innerHTML += `<div class="message agent" style="color: #f43f5e;">Error communicating with recommendation advisor. Please check your API key.</div>`;
            } finally {
                if (input) {
                    input.disabled = false;
                    input.focus();
                }
                if (sendBtn) sendBtn.disabled = false;
            }
            messages.scrollTop = messages.scrollHeight;
        }

        let activeVibe = 'chill';
        let activeScale = 'starting';
        let activeGoal = 'growth';

        function switchTab(tabName) {
            // Hide all views
            document.getElementById('dashboard-view').style.display = 'none';
            document.getElementById('planner-view').style.display = 'none';
            document.getElementById('curation-view').style.display = 'none';
            const starmapView = document.getElementById('starmap-view');
            if (starmapView) starmapView.style.display = 'none';

            // Deactivate all tab buttons
            const buttons = document.querySelectorAll('#tab-navigation .tab-btn');
            buttons.forEach(btn => btn.classList.remove('active'));

            // Show active view & button
            if (tabName === 'dashboard') {
                document.getElementById('dashboard-view').style.display = 'grid';
                const activeBtn = Array.from(buttons).find(btn => btn.getAttribute('onclick').includes('dashboard'));
                if (activeBtn) activeBtn.classList.add('active');
            } else if (tabName === 'planner') {
                document.getElementById('planner-view').style.display = 'grid';
                const activeBtn = Array.from(buttons).find(btn => btn.getAttribute('onclick').includes('planner'));
                if (activeBtn) activeBtn.classList.add('active');
                
                // If keyless, disable custom playbook generation and show affiliate playbook by default
                const hasKey = checkKey();
                const genBtn = document.getElementById('btn-playbooks');
                if (genBtn) {
                    if (!hasKey) {
                        genBtn.disabled = true;
                        genBtn.textContent = 'API Key Required for Custom Playbooks';
                    } else {
                        genBtn.disabled = false;
                        genBtn.textContent = 'Generate Strategic Playbooks';
                    }
                }
                if (!hasKey && serverAffiliatePlaybook) {
                    renderAffiliatePlaybookOnly();
                }
            } else if (tabName === 'curation') {
                document.getElementById('curation-view').style.display = 'grid';
                const activeBtn = Array.from(buttons).find(btn => btn.getAttribute('onclick').includes('curation'));
                if (activeBtn) activeBtn.classList.add('active');
                loadCurationBoard();
            } else if (tabName === 'starmap') {
                if (starmapView) starmapView.style.display = 'grid';
                const activeBtn = Array.from(buttons).find(btn => btn.getAttribute('onclick').includes('starmap'));
                if (activeBtn) activeBtn.classList.add('active');
                loadStarMap();
            }
        }

        function renderAffiliatePlaybookOnly() {
            const resultsContainer = document.getElementById('planner-results');
            if (!resultsContainer || !serverAffiliatePlaybook) return;

            resultsContainer.innerHTML = '';
            const grid = document.createElement('div');
            grid.className = 'playbook-grid';
            resultsContainer.appendChild(grid);

            const affCard = document.createElement('div');
            affCard.className = 'playbook-card';

            currentGeneratedPlaybooks['affiliate'] = serverAffiliatePlaybook;

            affCard.innerHTML = `
                <div class="playbook-header">
                    <div>
                        <div class="playbook-title">${serverAffiliatePlaybook.game}</div>
                        <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.15rem;">${serverAffiliatePlaybook.category}</div>
                    </div>
                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                        <span class="playbook-score-badge">Match Score: 100%</span>
                        <button class="btn-secondary" onclick="pinPlaybook('affiliate')" style="padding: 0.35rem 0.75rem; font-size: 0.75rem; border-radius: 8px; font-weight: 600;">📌 Pin Playbook</button>
                    </div>
                </div>
                <div class="playbook-section">
                    <div class="playbook-section-label">Target Platform & Distribution</div>
                    <div class="playbook-section-content">${serverAffiliatePlaybook.platform}</div>
                </div>
                <div class="playbook-section">
                    <div class="playbook-section-label">Engagement Hook & Stream Concept</div>
                    <div class="playbook-section-content" style="border-left: 2px solid var(--accent-purple); padding-left: 0.75rem; font-style: italic;">"${serverAffiliatePlaybook.hook}"</div>
                </div>
                <div class="playbook-section">
                    <div class="playbook-section-label">Tactical Advice</div>
                    <div class="playbook-section-content">${serverAffiliatePlaybook.advice}</div>
                </div>
                <div class="playbook-section">
                    <div class="playbook-section-label">Stream Preparation & Setup</div>
                    <div class="playbook-section-content">${markdownLinksToHtml(serverAffiliatePlaybook.preparation)}</div>
                </div>
            `;
            grid.appendChild(affCard);
        }

        function selectVibe(el, vibe) {
            const cards = document.querySelectorAll('.vibe-card');
            cards.forEach(c => c.classList.remove('selected'));
            el.classList.add('selected');
            activeVibe = vibe;
        }

        function selectScale(el, scale) {
            const cards = document.querySelectorAll('.scale-card');
            cards.forEach(c => c.classList.remove('selected'));
            el.classList.add('selected');
            activeScale = scale;
        }

        function selectGoal(el, goal) {
            const cards = document.querySelectorAll('.goal-card');
            cards.forEach(c => c.classList.remove('selected'));
            el.classList.add('selected');
            activeGoal = goal;
        }

        function updateDurationLabel(val) {
            document.getElementById('duration-val').textContent = parseFloat(val).toFixed(1) + ' hrs';
        }

        async function generatePlaybooks() {
            const key = checkKey();
            if (!key && !serverKeyConfigured) {
                logout();
                return;
            }

            const btn = document.getElementById('btn-playbooks');
            if (btn) {
                btn.disabled = true;
                btn.innerHTML = '<span class="loader" style="width:0.8rem; height:0.8rem; border-width:2px; display:inline-block; vertical-align:middle; margin-right:0.5rem;"></span> Generating playbooks...';
            }

            const resultsContainer = document.getElementById('planner-results');
            resultsContainer.innerHTML = '';

            const categoryEl = document.getElementById('category-selector');
            const category = categoryEl ? categoryEl.value : 'overall';

            const trendingGames = cachedGamesList.filter(g => g.tier === 'trending');
            const customGames = cachedGamesList.filter(g => g.custom || g.tier === 'custom');
            const filteredTrending = trendingGames.filter(g => matchesCategory(g.category, g.title, category));
            const topTrending = filteredTrending.slice(0, 5);

            const activeSponsored = sponsoredGamesList[currentSponsoredIndex];

            const targetGames = [];
            const seen = new Set();

            // 1. Custom games
            customGames.forEach(g => {
                const key = g.title.toLowerCase();
                if (!seen.has(key)) {
                    seen.add(key);
                    targetGames.push({ title: g.title, isCustom: true, isSponsored: false });
                }
            });

            // 2. Active Sponsored game
            if (activeSponsored) {
                const key = activeSponsored.title.toLowerCase();
                if (!seen.has(key)) {
                    seen.add(key);
                    targetGames.push({ title: activeSponsored.title, isCustom: false, isSponsored: true });
                }
            }

            // 3. Top trending games
            topTrending.forEach(g => {
                const key = g.title.toLowerCase();
                if (!seen.has(key)) {
                    seen.add(key);
                    targetGames.push({ title: g.title, isCustom: false, isSponsored: false });
                }
            });

            if (targetGames.length === 0) {
                resultsContainer.innerHTML = '<p style="color: var(--text-muted); text-align: center;">No matches found. Try collecting some games or updating your API key.</p>';
                return;
            }

            const grid = document.createElement('div');
            grid.className = 'playbook-grid';
            resultsContainer.appendChild(grid);

            const cards = [];
            targetGames.forEach((tg, idx) => {
                const card = document.createElement('div');
                card.className = 'playbook-card';
                card.id = `pb-card-${idx}`;
                grid.appendChild(card);
                renderAgentDiagnosticLoader(card, 'playbooks', `Compiling strategy for ${tg.title}...`);
                cards.push({ game: tg.title, isCustom: tg.isCustom, isSponsored: tg.isSponsored, element: card });
            });

            try {
                const duration = parseFloat(document.getElementById('duration-input').value);
                const chatModel = localStorage.getItem('gemini_model_chat') || 'gemma-4-31b-it';
                const customContextEl = document.getElementById('custom-context-input');
                const customContext = customContextEl ? customContextEl.value : '';
                let affiliatePlaybook = null;
                const generatedPlaybooksList = [];
                // Pre-determine a random insertion index, constraint: must be after 1 (i.e. >= 2)
                const targetInsertionIndex = Math.max(2, Math.floor(Math.random() * (cards.length + 1)));

                async function fetchDynamicAffiliate(contextPlaybooks) {
                    if (!serverAffiliatePlaybook) return null;
                    try {
                        const res = await fetch('/api/playbook', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-Gemini-Chat-Model': chatModel
                            },
                            body: JSON.stringify({
                                vibe: activeVibe,
                                scale: activeScale,
                                duration: duration,
                                stream_goal: activeGoal,
                                game: "Stream Gear & Setup",
                                previous_playbooks: contextPlaybooks
                            })
                        });
                        const playbookData = await res.json();
                        if (playbookData.playbooks && playbookData.playbooks.length > 0) {
                            return playbookData.playbooks[0];
                        }
                    } catch (affGenErr) {
                        console.error("Failed to generate dynamic affiliate playbook, falling back to static:", affGenErr);
                    }
                    return serverAffiliatePlaybook;
                }

                for (let i = 0; i < cards.length; i++) {
                    const c = cards[i];
                    try {
                        const res = await fetch('/api/playbook', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/json',
                                'X-Gemini-Chat-Model': chatModel
                            },
                            body: JSON.stringify({
                                vibe: activeVibe,
                                scale: activeScale,
                                duration: duration,
                                stream_goal: activeGoal,
                                game: c.game,
                                custom_context: customContext
                            })
                        });

                        if (res.status === 401) {
                            logout();
                            return;
                        }

                        const playbookData = await res.json();

                        if (playbookData.playbooks && playbookData.playbooks.length > 0) {
                            const p = playbookData.playbooks[0];
                            generatedPlaybooksList.push(p);

                            let newsHtml = '';
                            if (p.news && p.news.length > 0) {
                                newsHtml = '<div style="margin-top: 0.5rem; display: flex; flex-direction: column; gap: 0.4rem;">';
                                p.news.forEach(art => {
                                    newsHtml += `
                                        <div style="font-size: 0.8rem; background: rgba(15, 23, 42, 0.4); padding: 0.5rem; border-radius: 6px; border: 1px solid rgba(255,255,255,0.05);">
                                            <a href="${art.url}" target="_blank" style="color: var(--accent-cyan); text-decoration: none; font-weight: 600;">📰 ${art.title}</a>
                                            <div style="color: var(--text-muted); font-size: 0.75rem; margin-top: 0.15rem;">${art.summary}</div>
                                        </div>
                                    `;
                                });
                                newsHtml += '</div>';
                            } else {
                                newsHtml = '<div style="font-size: 0.8rem; color: var(--text-muted); font-style: italic;">No recent news found.</div>';
                            }

                            currentGeneratedPlaybooks[p.game.toLowerCase()] = p;
                            const safeKey = p.game.toLowerCase().replace(/'/g, "\\'");

                            let disclaimerHtml = '';
                            if (c.isSponsored) {
                                disclaimerHtml = `
                                    <div style="font-size: 0.75rem; color: var(--text-muted); font-style: italic; background: rgba(0, 180, 216, 0.05); padding: 0.4rem 0.75rem; border: 1px solid rgba(0, 180, 216, 0.15); margin-top: -0.5rem; margin-bottom: 0.5rem; border-radius: 0px !important;">
                                        ⚠️ Sponsored Ad: This game is sponsored. Content creators may receive promotional perks.
                                    </div>
                                `;
                            }

                            c.element.innerHTML = `
                                <div class="playbook-header">
                                    <div>
                                        <div class="playbook-title">${p.game} ${c.isCustom ? '<span style="font-size: 0.75rem; font-family: \'Share Tech Mono\', monospace; padding: 0.15rem 0.4rem; background: rgba(168, 85, 247, 0.15); color: #a855f7; border: 1px solid rgba(168, 85, 247, 0.3);">CUSTOM</span>' : ''}</div>
                                        <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.15rem;">${p.category}</div>
                                    </div>
                                    <div style="display: flex; gap: 0.5rem; align-items: center;">
                                        <span class="playbook-score-badge">Match Score: ${p.score}%</span>
                                        <button class="btn-secondary" onclick="pinPlaybook('${safeKey}')" style="padding: 0.35rem 0.75rem; font-size: 0.75rem; border-radius: 8px; font-weight: 600;">📌 Pin Playbook</button>
                                    </div>
                                </div>
                                ${disclaimerHtml}
                                ${p.formatted_time ? `
                                <div style="display: flex; gap: 1rem; font-size: 0.75rem; color: var(--accent-cyan); background: rgba(6, 182, 212, 0.05); padding: 0.4rem 0.75rem; border: 1px solid rgba(6, 182, 212, 0.15); margin-top: -0.5rem; margin-bottom: 0.5rem; font-family: 'Share Tech Mono', monospace; border-radius: 0px !important;">
                                    <span>🕒 Generated: ${p.formatted_time}</span>
                                    <span>👥 Live Viewers: ${p.total_viewers ? p.total_viewers.toLocaleString() : '—'}</span>
                                    <span>🎯 Goal: ${p.stream_goal ? p.stream_goal.toUpperCase() : 'N/A'}</span>
                                </div>
                                ` : ''}
                                <div class="playbook-section">
                                    <div class="playbook-section-label">Target Platform & Distribution</div>
                                    <div class="playbook-section-content">${p.platform}</div>
                                </div>
                                <div class="playbook-section">
                                    <div class="playbook-section-label">Engagement Hook & Stream Concept</div>
                                    <div class="playbook-section-content" style="border-left: 2px solid var(--accent-purple); padding-left: 0.75rem; font-style: italic;">"${p.hook}"</div>
                                </div>
                                <div class="playbook-section">
                                    <div class="playbook-section-label">Tactical Advice</div>
                                    <div class="playbook-section-content">${p.advice}</div>
                                </div>
                                <div class="playbook-section">
                                    <div class="playbook-section-label">Stream Preparation & Setup</div>
                                    <div class="playbook-section-content">${markdownLinksToHtml(p.preparation || 'No specific prep requirements.')}</div>
                                </div>
                                <div class="playbook-section">
                                    <div class="playbook-section-label">Latest Community & Patch News</div>
                                    ${newsHtml}
                                </div>
                            `;
                        } else {
                            c.element.innerHTML = `<div style="padding: 2rem; text-align: center; color: #f43f5e;">Failed to generate playbook for ${c.game}</div>`;
                        }
                    } catch (fetchErr) {
                        console.error(fetchErr);
                        c.element.innerHTML = `<div style="padding: 2rem; text-align: center; color: #f43f5e;">Error generating playbook: ${fetchErr.message || fetchErr}</div>`;
                    }

                    // Check if we reached the target insertion index sequentially
                    if (generatedPlaybooksList.length === targetInsertionIndex && !affiliatePlaybook) {
                        affiliatePlaybook = await fetchDynamicAffiliate(generatedPlaybooksList);
                    }
                }

                // If the loop finished and affiliatePlaybook has not been generated yet
                if (!affiliatePlaybook) {
                    affiliatePlaybook = await fetchDynamicAffiliate(generatedPlaybooksList);
                }

                // Render affiliate playbook card at targetInsertionIndex if present
                if (affiliatePlaybook) {
                    const affCard = document.createElement('div');
                    affCard.className = 'playbook-card';
                    currentGeneratedPlaybooks['affiliate'] = affiliatePlaybook;

                    affCard.innerHTML = `
                        <div class="playbook-header">
                            <div>
                                <div class="playbook-title">${affiliatePlaybook.game}</div>
                                <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.15rem;">${affiliatePlaybook.category}</div>
                            </div>
                            <div style="display: flex; gap: 0.5rem; align-items: center;">
                                <span class="playbook-score-badge">Match Score: ${affiliatePlaybook.score || 100}%</span>
                                <button class="btn-secondary" onclick="pinPlaybook('affiliate')" style="padding: 0.35rem 0.75rem; font-size: 0.75rem; border-radius: 8px; font-weight: 600;">📌 Pin Playbook</button>
                            </div>
                        </div>
                        ${affiliatePlaybook.formatted_time ? `
                        <div style="display: flex; gap: 1rem; font-size: 0.75rem; color: var(--accent-cyan); background: rgba(6, 182, 212, 0.05); padding: 0.4rem 0.75rem; border: 1px solid rgba(6, 182, 212, 0.15); margin-top: -0.5rem; margin-bottom: 0.5rem; font-family: 'Share Tech Mono', monospace; border-radius: 0px !important;">
                            <span>🕒 Generated: ${affiliatePlaybook.formatted_time}</span>
                            <span>🎯 Goal: ${affiliatePlaybook.stream_goal ? affiliatePlaybook.stream_goal.toUpperCase() : 'N/A'}</span>
                        </div>
                        ` : ''}
                        <div class="playbook-section">
                            <div class="playbook-section-label">Target Platform & Distribution</div>
                            <div class="playbook-section-content">${affiliatePlaybook.platform}</div>
                        </div>
                        <div class="playbook-section">
                            <div class="playbook-section-label">Engagement Hook & Stream Concept</div>
                            <div class="playbook-section-content" style="border-left: 2px solid var(--accent-purple); padding-left: 0.75rem; font-style: italic;">"${affiliatePlaybook.hook}"</div>
                        </div>
                        <div class="playbook-section">
                            <div class="playbook-section-label">Tactical Advice</div>
                            <div class="playbook-section-content">${affiliatePlaybook.advice}</div>
                        </div>
                        <div class="playbook-section">
                            <div class="playbook-section-label">Stream Preparation & Setup</div>
                            <div class="playbook-section-content">${markdownLinksToHtml(affiliatePlaybook.preparation || 'No specific prep requirements.')}</div>
                        </div>
                    `;
                    const insertPos = Math.min(targetInsertionIndex, grid.children.length);
                    if (insertPos >= grid.children.length) {
                        grid.appendChild(affCard);
                    } else {
                        grid.insertBefore(affCard, grid.children[insertPos]);
                    }
                }
            } catch (err) {
                console.error(err);
                resultsContainer.innerHTML = `<p style="color: #f43f5e; text-align: center;">Error generating playbooks: ${err.message || err}</p>`;
            } finally {
                if (btn) {
                    setButtonCooldown(btn, 'Generate Strategic Playbooks');
                }
            }
        }

        function pinPlaybook(playbookInput) {
            try {
                let playbook;
                if (typeof playbookInput === 'string') {
                    const trimmed = playbookInput.trim();
                    if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
                        playbook = JSON.parse(playbookInput);
                    } else {
                        playbook = currentGeneratedPlaybooks[trimmed.toLowerCase()];
                    }
                } else {
                    playbook = playbookInput;
                }

                if (!playbook) {
                    console.error("Playbook not found to pin for input:", playbookInput);
                    alert("Could not pin playbook: Playbook data is missing.");
                    return;
                }

                let saved = [];
                const existing = localStorage.getItem('curated_stream_playbooks');
                if (existing) {
                    saved = JSON.parse(existing);
                }

                // Check if already exists
                const dup = saved.some(item => item.game.toLowerCase() === playbook.game.toLowerCase() && item.vibe === activeVibe);
                if (dup) {
                    alert(`${playbook.game} (vibe: ${activeVibe}) is already pinned to your curation board!`);
                    return;
                }

                playbook.vibe = activeVibe;
                playbook.scale = activeScale;
                playbook.duration = parseFloat(document.getElementById('duration-input').value);
                playbook.stream_goal = playbook.stream_goal || activeGoal;
                playbook.note = "";
                playbook.pinned_at = Date.now();

                saved.push(playbook);
                localStorage.setItem('curated_stream_playbooks', JSON.stringify(saved));
                alert(`📌 ${playbook.game} successfully pinned to Saved Playbooks!`);
                if (typeof loadCurationBoard === 'function') {
                    loadCurationBoard();
                }
            } catch (err) {
                console.error("Failed to pin playbook:", err);
            }
        }

        function markdownLinksToHtml(text) {
            if (!text) return '';
            let html = '';
            if (typeof marked !== 'undefined' && marked.parse) {
                html = marked.parse(text);
            } else {
                html = text.replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank">$1</a>');
                html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
                html = html.replace(/\n/g, '<br>');
            }
            
            const tempDiv = document.createElement('div');
            tempDiv.innerHTML = html;
            const anchors = tempDiv.getElementsByTagName('a');
            for (let i = 0; i < anchors.length; i++) {
                anchors[i].setAttribute('target', '_blank');
                anchors[i].style.color = 'var(--accent-cyan)';
                anchors[i].style.textDecoration = 'underline';
            }
            return tempDiv.innerHTML;
        }

        function loadCurationBoard() {
            const list = document.getElementById('curated-playbooks-list');
            list.innerHTML = '';

            let saved = [];
            const existing = localStorage.getItem('curated_stream_playbooks');
            if (existing) {
                saved = JSON.parse(existing);
            }

            if (saved.length === 0) {
                list.innerHTML = `
                    <div style="grid-column: 1 / -1; text-align: center; padding: 4rem; border: 1px dashed rgba(255,255,255,0.1); border-radius: 12px; width: 100%;">
                        <span style="font-size: 2.5rem; display: block; margin-bottom: 1rem;">✨</span>
                        <h3 style="color: var(--text-main);">Your Curation Board is Empty</h3>
                        <p style="color: var(--text-muted); font-size: 0.9rem; margin-top: 0.5rem; max-width: 400px; margin-left: auto; margin-right: auto;">
                            Go to the Playbook Planner, select your vibe, and pin your favorite stream options to build your strategy sheet!
                        </p>
                    </div>
                `;
                return;
            }

            // Sort by pinned time (newest first)
            saved.sort((a, b) => b.pinned_at - a.pinned_at);

            saved.forEach((p, idx) => {
                const card = document.createElement('div');
                card.className = 'playbook-card curated-card';

                // Display custom vibe & scale badges
                const vibeEmoji = p.vibe === 'chill' ? '☕' : p.vibe === 'competitive' ? '🏆' : p.vibe === 'community' ? '👥' : '🎬';

                card.innerHTML = `
                    <div class="playbook-header">
                        <div>
                            <div class="playbook-title">${p.game}</div>
                            <div style="font-size: 0.8rem; color: var(--text-muted); margin-top: 0.15rem; display: flex; gap: 0.4rem; align-items: center; flex-wrap: wrap;">
                                <span>${p.category}</span>
                                ${!p.is_affiliate ? `
                                <span>•</span>
                                <span style="color: #cbd5e1;">${vibeEmoji} ${p.vibe.toUpperCase()}</span>
                                <span>•</span>
                                <span style="color: #cbd5e1;">⏱ ${p.duration}h</span>
                                ` : ''}
                                ${p.stream_goal ? `<span>•</span><span style="color: var(--accent-purple);">🎯 ${p.stream_goal.toUpperCase()}</span>` : ''}
                                ${p.formatted_time ? `<span>•</span><span style="color: var(--accent-cyan);">🕒 ${p.formatted_time}</span>` : ''}
                            </div>
                        </div>
                        <button onclick="deleteCurationPin(${idx})" style="background: rgba(239, 68, 68, 0.15); border: 1px solid rgba(239, 68, 68, 0.4); color: #ef4444; padding: 0.3rem 0.6rem; border-radius: 8px; font-size: 0.75rem; cursor: pointer; transition: all 0.2s ease;">✕ Remove</button>
                    </div>
                    <div class="playbook-section">
                        <div class="playbook-section-label">Target Platform</div>
                        <div class="playbook-section-content">${p.platform}</div>
                    </div>
                    <div class="playbook-section">
                        <div class="playbook-section-label">Engagement Concept</div>
                        <div class="playbook-section-content" style="border-left: 2px solid var(--accent-purple); font-style: italic;">"${p.hook}"</div>
                    </div>
                    <div class="playbook-section">
                        <div class="playbook-section-label">Tactical Advice</div>
                        <div class="playbook-section-content">${p.advice}</div>
                    </div>
                    <div class="playbook-section">
                        <div class="playbook-section-label">Stream Preparation & Setup</div>
                        <div class="playbook-section-content">${markdownLinksToHtml(p.preparation || 'No specific prep requirements.')}</div>
                    </div>
                    <div class="playbook-section" style="margin-top: 0.5rem; border-top: 1px solid rgba(255,255,255,0.05); padding-top: 0.75rem;">
                        <div class="playbook-section-label" style="color: #a855f7; display: flex; justify-content: space-between; align-items: center; width: 100%;">
                            <span>My Private Strategy Notes</span>
                            <span style="font-size: 0.7rem; color: var(--text-muted); font-weight: normal;">auto-saves</span>
                        </div>
                        <textarea class="note-input" placeholder="e.g. Try streaming this Friday! Need to update overlay..." oninput="saveCurationNote(${idx}, this.value)">${p.note || ''}</textarea>
                    </div>
                `;
                list.appendChild(card);
            });
        }

        function saveCurationNote(idx, val) {
            let saved = JSON.parse(localStorage.getItem('curated_stream_playbooks') || '[]');
            saved.sort((a, b) => b.pinned_at - a.pinned_at);
            if (saved[idx]) {
                saved[idx].note = val;
                localStorage.setItem('curated_stream_playbooks', JSON.stringify(saved));
            }
        }

        function deleteCurationPin(idx) {
            let saved = JSON.parse(localStorage.getItem('curated_stream_playbooks') || '[]');
            saved.sort((a, b) => b.pinned_at - a.pinned_at);
            const gameTitle = saved[idx] ? saved[idx].game : 'Playbook';
            if (confirm(`Are you sure you want to remove ${gameTitle} from your curation board?`)) {
                saved.splice(idx, 1);
                localStorage.setItem('curated_stream_playbooks', JSON.stringify(saved));
                loadCurationBoard();
            }
        }

        function exportCurationBoard() {
            let saved = JSON.parse(localStorage.getItem('curated_stream_playbooks') || '[]');
            if (saved.length === 0) {
                alert("Your Curation Board is empty. Nothing to export!");
                return;
            }
            saved.sort((a, b) => b.pinned_at - a.pinned_at);

            let md = `# My Curated Stream Strategy Board\\nGenerated: ${new Date().toLocaleDateString()}\\n\\n`;

            saved.forEach((p, idx) => {
                md += `## ${idx + 1}. ${p.game} (${p.category})\\n`;
                const vibeStr = p.vibe ? p.vibe.toUpperCase() : 'N/A';
                const durationStr = p.duration ? p.duration + ' hours' : 'N/A';
                md += `- **Stream Settings**: Vibe=${vibeStr} | Scale=${p.scale || 'N/A'} | Target Duration=${durationStr}\\n`;
                md += `- **Recommended Platform**: ${p.platform}\\n`;
                md += `- **Engagement Hook**: *"${p.hook}"*\\n`;
                md += `- **Tactical Advice**: ${p.advice}\\n`;
                if (p.preparation) {
                    md += `- **Stream Preparation & Setup**:\\n${p.preparation.replace(/\n/g, '\\n')}\\n`;
                }
                if (p.note && p.note.trim()) {
                    md += `- **My Notes**: _"${p.note.trim()}"_\\n`;
                }
                md += `\\n---\\n\\n`;
            });

            navigator.clipboard.writeText(md).then(() => {
                alert("📋 Markdown report successfully copied to your clipboard! Paste it into Discord or your text editor.");
            }).catch(err => {
                console.error("Clipboard copy failed:", err);
                alert("Clipboard copy failed. Here is the raw markdown content:\\n\\n" + md);
            });
        }

        // On Load initialization
        initApp();


        function escapeHTML(str) {
            if (str === null || str === undefined) return '';
            const s = String(str);
            return s.replace(/&/g, '&amp;')
                    .replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;')
                    .replace(/"/g, '&quot;')
                    .replace(/'/g, '&#39;');
        }

        function formatTime(timestamp) {
            const t = timestamp || lastCacheRefreshedAt;
            if (!t) return '';
            const date = new Date(t * 1000);
            return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        }

        function showStreamerTooltip(el, title, name, viewers) {
            const tooltip = document.getElementById('streamer-tooltip');
            if (!tooltip) return;
            
            const rect = el.getBoundingClientRect();
            const safeName = escapeHTML(name);
            const safeTitle = escapeHTML(title);
            tooltip.innerHTML = `
                <div style="font-weight: 600; color: #c084fc; margin-bottom: 0.2rem;">👾 ${safeName}</div>
                <div style="color: var(--text-muted); font-style: italic; margin-bottom: 0.4rem; line-height: 1.2;">"${safeTitle || 'No stream title'}"</div>
                <div style="font-size: 0.7rem; color: #10b981; font-weight: 600;">🟢 ${viewers.toLocaleString()} watching</div>
            `;
            
            tooltip.style.display = 'block';
            // Position tooltip above the tag
            tooltip.style.left = (rect.left + window.scrollX + (rect.width - tooltip.offsetWidth) / 2) + 'px';
            tooltip.style.top = (rect.top + window.scrollY - tooltip.offsetHeight - 8) + 'px';
        }

        function hideStreamerTooltip() {
            const tooltip = document.getElementById('streamer-tooltip');
            if (tooltip) tooltip.style.display = 'none';
        }

        // Global click delegator for streamer links/tags
        document.addEventListener('click', function(e) {
            const link = e.target.closest('.streamer-tag, .streamer-link, a[href*="twitch.tv/"], a[href*="youtube.com/channel/"]');
            if (link) {
                // Let links inside the streamer drawer function normally
                if (link.closest('#streamer-profile-drawer')) {
                    return;
                }
                e.preventDefault();
                let handle = link.getAttribute('data-handle');
                if (!handle) {
                    const href = link.getAttribute('href');
                    if (href) {
                        try {
                            const url = new URL(href);
                            handle = url.pathname.split('/').filter(Boolean).pop();
                        } catch (err) {
                            const parts = href.split('/');
                            handle = parts[parts.length - 1];
                        }
                    }
                }
                if (!handle) {
                    // Try parsing handle from inner text (strip icon prefix)
                    const text = link.innerText || link.textContent || "";
                    const m = text.match(/(?:👾|🔴|\s)*([a-zA-Z0-9_]{3,25})/);
                    if (m) {
                        handle = m[1];
                    }
                }
                if (handle) {
                    openStreamerProfileDrawer(handle);
                }
            }
        });

        function createSparklineSVG(historyData, key, strokeColor) {
            if (!historyData || historyData.length < 2) {
                return `<div style="font-size: 0.75rem; color: var(--text-muted); font-style: italic;">Insufficient history data</div>`;
            }
            
            // Sort history by timestamp ascending
            const sortedHistory = [...historyData].sort((a, b) => (a.timestamp || 0) - (b.timestamp || 0));
            const vals = sortedHistory.map(h => h[key] || 0.0);
            
            const minVal = Math.min(...vals);
            const maxVal = Math.max(...vals);
            
            let finalMin = minVal;
            let finalRange = maxVal - minVal;
            
            if (key === 'rolling_sentiment_score') {
                finalMin = -1.0;
                finalRange = 2.0;
            }
            
            // Apply 3-point moving average smoothing to remove high-frequency noise
            const smoothedVals = [];
            for (let i = 0; i < vals.length; i++) {
                if (i === 0) {
                    smoothedVals.push(vals[i]);
                } else if (i === vals.length - 1) {
                    smoothedVals.push(vals[i]);
                } else {
                    smoothedVals.push((vals[i - 1] + vals[i] + vals[i + 1]) / 3);
                }
            }

            const width = 310;
            const height = 35;
            const points = [];
            
            for (let i = 0; i < sortedHistory.length; i++) {
                const x = (i / (sortedHistory.length - 1)) * width;
                let y = height / 2;
                if (finalRange > 0) {
                    y = height - ((smoothedVals[i] - finalMin) / finalRange) * (height - 6) - 3;
                }
                points.push(`${x.toFixed(1)},${y.toFixed(1)}`);
            }
            
            const latestVal = vals[vals.length - 1];
            const peakVal = maxVal;
            
            let label = key.replace(/_/g, ' ');
            if (key === 'viewer_count') label = 'VIEWERS';
            else if (key === 'msg_per_minute') label = 'CHAT SPEED';
            else if (key === 'chat_volatility') label = 'VOLATILITY';
            else if (key === 'rolling_sentiment_score') label = 'SENTIMENT';
            
            let displayVal = latestVal >= 1000 ? (latestVal/1000).toFixed(1)+'k' : latestVal.toFixed(latestVal % 1 === 0 ? 0 : 2);
            let displayPeak = peakVal >= 1000 ? (peakVal/1000).toFixed(1)+'k' : peakVal.toFixed(peakVal % 1 === 0 ? 0 : 2);
            
            // Generate guide overlays
            let guidesHTML = '';
            if (key === 'rolling_sentiment_score') {
                const zeroY = height / 2;
                guidesHTML = `
                    <line x1="0" y1="${zeroY}" x2="${width}" y2="${zeroY}" stroke="rgba(255,255,255,0.15)" stroke-dasharray="2,3" stroke-width="1" />
                    <text x="2" y="8" fill="rgba(255,255,255,0.3)" font-size="7px" font-family="Share Tech Mono">+1 (POS)</text>
                    <text x="2" y="${height - 3}" fill="rgba(255,255,255,0.3)" font-size="7px" font-family="Share Tech Mono">-1 (NEG)</text>
                `;
            }
            
            return `
                <div style="margin-bottom: 0.6rem;">
                    <div style="display: flex; justify-content: space-between; font-size: 0.72rem; color: var(--text-muted); margin-bottom: 0.2rem;">
                        <span style="font-weight: bold; text-transform: uppercase;">${label}</span>
                        <span>Latest: <strong style="color: #fff;">${displayVal}</strong> | Peak: <strong style="color: ${strokeColor};">${displayPeak}</strong></span>
                    </div>
                    <div style="background: rgba(0,0,0,0.5); border: 1px solid rgba(255,255,255,0.05); padding: 0.2rem; display: flex; justify-content: center; align-items: center; position: relative;">
                        <svg width="100%" height="${height}" viewBox="0 0 ${width} ${height}" style="overflow: visible;">
                            ${guidesHTML}
                            <polyline fill="none" stroke="${strokeColor}" stroke-width="1.5" points="${points.join(' ')}" style="filter: drop-shadow(0 0 3px ${strokeColor});"/>
                        </svg>
                    </div>
                </div>
            `;
        }

        function openStreamerProfileDrawer(handle, preserveRadar = false, forceRefresh = false) {
            const drawer = document.getElementById('streamer-profile-drawer');
            if (!drawer) return;

            // Normalize handle: preserve case for 24-character YouTube channel IDs starting with uc/UC
            const trimmed = handle.trim();
            const isYT_init = /^[uU][cC][a-zA-Z0-9_-]{22}$/.test(trimmed);
            const cleanHandle = isYT_init ? trimmed : trimmed.toLowerCase();
            currentDrawerStreamer = cleanHandle;

            // Cancel any active profile fetches and intervals
            if (activeProfileAbortController) {
                try {
                    activeProfileAbortController.abort();
                } catch (e) {}
            }
            if (activeProfileLoadingInterval) {
                clearInterval(activeProfileLoadingInterval);
                activeProfileLoadingInterval = null;
            }
            activeProfileAbortController = new AbortController();
            const signal = activeProfileAbortController.signal;

            // Hide all sub-panels during synchronizations
            const panelsToHide = [
                'drawer-radar-section',
                'drawer-history-section',
                'drawer-clips-section',
                'drawer-correlations-section',
                'drawer-live-radar-section',
                'drawer-forecast-section',
                'drawer-timeline-section'
            ];
            panelsToHide.forEach(id => {
                const el = document.getElementById(id);
                if (el) el.style.display = 'none';
            });

            // Immediately show drawer and set loading status for better UX
            drawer.style.right = '0px';
            const infoElInit = document.getElementById('drawer-profile-info');
            if (infoElInit) {
                infoElInit.innerHTML = `
                    <div style="text-align: center; padding: 3rem 1rem; font-family: 'Press Start 2P'; font-size: 0.72rem; color: var(--accent-cyan);">
                        <div class="generating-pulse" style="display: inline-block; padding: 0.85rem; border: 1px solid var(--accent-cyan); background: rgba(0, 240, 255, 0.05); margin-bottom: 1.5rem;">
                            [ SYNCHRONIZING PROFILE ]
                        </div>
                        <p id="drawer-loading-status" style="font-family: 'Share Tech Mono'; font-size: 0.95rem; color: #fff; line-height: 1.4; margin-bottom: 0.6rem;">
                            Contacting live streaming nodes...
                        </p>
                        <p style="font-family: 'Share Tech Mono'; font-size: 0.8rem; color: var(--text-muted); line-height: 1.4; max-width: 320px; margin: 0 auto;">
                            First-time aggregation scans YouTube page structure, caches metrics, and uses Gemini to build personality archetypes. This may take up to 2 minutes.
                        </p>
                    </div>
                `;

                let phaseIndex = 0;
                const loadingPhases = [
                    "Contacting live streaming nodes...",
                    "Scraping YouTube streams tab structure...",
                    "Resolving Twitch channel links...",
                    "Caching real-time metrics...",
                    "Retrieving Gemini API key from pool...",
                    "Synthesizing chat sentiments...",
                    "Running Ridge regression forecast...",
                    "Building personality archetypes...",
                    "Querying Vibe Tribe connections..."
                ];
                activeProfileLoadingInterval = setInterval(() => {
                    const statusEl = document.getElementById('drawer-loading-status');
                    if (statusEl) {
                        phaseIndex = (phaseIndex + 1) % loadingPhases.length;
                        statusEl.textContent = loadingPhases[phaseIndex];
                    }
                }, 2500);
            }

            // Reset forecast UI state
            activeForecastData = null;
            const chartContainer = document.getElementById('forecast-chart-container');
            const svgWrapper = document.getElementById('forecast-svg-wrapper');
            const statsEl = document.getElementById('forecast-stats');
            const statusEl = document.getElementById('forecast-status');
            if (chartContainer) chartContainer.style.display = 'none';
            if (svgWrapper) svgWrapper.innerHTML = '';
            if (statsEl) statsEl.innerHTML = '';
            if (statusEl) statusEl.textContent = 'READY';

            if (!preserveRadar) {
                // Reset live monitor UI state
                const radarStatus = document.getElementById('live-radar-status');
                const radarConsole = document.getElementById('live-radar-console');
                const streamBox = document.getElementById('live-chat-stream-box');
                
                if (activeChatStreamSource) {
                    activeChatStreamSource.close();
                    activeChatStreamSource = null;
                }
                if (liveRadarTimer) {
                    clearInterval(liveRadarTimer);
                    liveRadarTimer = null;
                }
                
                if (radarStatus) radarStatus.textContent = 'READY';
                if (radarConsole) radarConsole.style.display = 'none';
                if (streamBox) streamBox.style.display = 'none';
                
                const buttonsContainer = document.getElementById('drawer-live-radar-buttons-container');
                if (buttonsContainer) buttonsContainer.innerHTML = '';
            }

            const url = `/api/streamers/${encodeURIComponent(cleanHandle)}/profile` + (forceRefresh ? '?refresh=true' : '');
            fetch(url, { signal })
                .then(res => {
                    if (!res.ok) {
                        return res.json().then(errData => {
                            throw new Error(errData.detail || errData.message || 'Server returned error ' + res.status);
                        }).catch(() => {
                            throw new Error('Server returned error ' + res.status);
                        });
                    }
                    return res.json();
                })
                .then(data => {
                    if (currentDrawerStreamer !== cleanHandle) {
                        console.log("Discarding stale profile response for " + cleanHandle);
                        return;
                    }
                    if (activeProfileLoadingInterval) {
                        clearInterval(activeProfileLoadingInterval);
                        activeProfileLoadingInterval = null;
                    }
                    const panelsToShow = [
                        'drawer-radar-section',
                        'drawer-live-radar-section',
                        'drawer-forecast-section',
                        'drawer-timeline-section'
                    ];
                    panelsToShow.forEach(id => {
                        const el = document.getElementById(id);
                        if (el) {
                            if (id === 'drawer-radar-section' || id === 'drawer-live-radar-section') {
                                el.style.display = 'flex';
                            } else {
                                el.style.display = 'block'; // some panels use block layout
                            }
                        }
                    });
                    const infoEl = document.getElementById('drawer-profile-info');
                    if (infoEl) {
                        infoEl.classList.remove('crt-flicker');
                        void infoEl.offsetWidth; // Force reflow
                        infoEl.classList.add('crt-flicker');
                    }

                    const profile = data.profile || {};
                    const sentiment = data.sentiment || {};
                    const moments = data.moments || [];

                    if (profile.streamer_handle) {
                        currentDrawerStreamer = profile.streamer_handle;
                    }

                    currentDrawerLinkedTwitch = data.linked_twitch || null;
                    currentDrawerLinkedYoutube = data.linked_youtube || null;

                    let youtubeStatsHTML = '';
                    if (typeof profile.youtube_subscribers !== 'undefined' && profile.youtube_subscribers !== null) {
                        youtubeStatsHTML = `
                            <div style="background: rgba(239, 68, 68, 0.08); border: 1px solid rgba(239, 68, 68, 0.25); padding: 0.5rem; font-size: 0.75rem; color: #fca5a5; margin-bottom: 0.75rem;">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.52rem; color: #ef4444; display: block; margin-bottom: 0.4rem; letter-spacing: 0.05em; text-align: center;">
                                    [ YOUTUBE METRICS ]
                                </div>
                                <div style="display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 0.35rem; text-align: center; font-size: 0.7rem;">
                                    <div>Subs: <strong>${(profile.youtube_subscribers || 0).toLocaleString()}</strong></div>
                                    <div>Views: <strong>${(profile.youtube_views || 0).toLocaleString()}</strong></div>
                                    <div>Videos: <strong>${(profile.youtube_videos || 0).toLocaleString()}</strong></div>
                                </div>
                            </div>
                        `;
                    }

                    let recentVideosHTML = '';
                    if (profile.recent_youtube_video_url || profile.recent_twitch_video_url) {
                        let ytLink = '';
                        if (profile.recent_youtube_video_url) {
                            ytLink = `
                                <div style="margin-bottom: 0.4rem;">
                                    <span style="color: #ef4444; font-weight: bold;">📺 Latest YT Video:</span><br>
                                    <a href="${profile.recent_youtube_video_url}" target="_blank" style="color: var(--accent-cyan); text-decoration: underline; margin-left: 0.25rem; font-size: 0.7rem;">
                                        ${escapeHTML(profile.recent_youtube_video_title || 'Watch Video')}
                                    </a>
                                </div>
                            `;
                        }
                        let twitchLink = '';
                        if (profile.recent_twitch_video_url) {
                            twitchLink = `
                                <div>
                                    <span style="color: #a855f7; font-weight: bold;">👾 Recent Twitch VOD:</span><br>
                                    <a href="${profile.recent_twitch_video_url}" target="_blank" style="color: var(--accent-cyan); text-decoration: underline; margin-left: 0.25rem; font-size: 0.7rem;">
                                        ${escapeHTML(profile.recent_twitch_video_title || 'Watch VOD')}
                                    </a>
                                </div>
                            `;
                        }
                        recentVideosHTML = `
                            <div style="background: rgba(0, 240, 255, 0.03); border: 1px solid rgba(0, 240, 255, 0.15); padding: 0.5rem; font-size: 0.72rem; color: #cbd5e1; margin-bottom: 0.75rem; font-family: 'Share Tech Mono'; text-align: left;">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.52rem; color: var(--accent-cyan); display: block; margin-bottom: 0.4rem; letter-spacing: 0.05em; text-align: center;">
                                    [ RECENT TRANSMISSIONS ]
                                </div>
                                ${ytLink}
                                ${twitchLink}
                            </div>
                        `;
                    }

                    let topGamesHTML = '';
                    if (profile.top_games && profile.top_games.length > 0) {
                        const gameList = profile.top_games.filter(g => g !== 'Unknown' && g !== 'Variety').map(g => 
                            `<span style="display: inline-block; background: rgba(181, 23, 158, 0.15); border: 1px solid rgba(181, 23, 158, 0.35); color: #f43f5e; padding: 0.15rem 0.35rem; font-size: 0.65rem; font-weight: bold; margin-right: 0.3rem; margin-bottom: 0.3rem; font-family: 'Share Tech Mono';">🎮 ${escapeHTML(g)}</span>`
                        ).join('');
                        if (gameList) {
                            topGamesHTML = `
                                <div style="background: rgba(181, 23, 158, 0.03); border: 1px solid rgba(181, 23, 158, 0.15); padding: 0.5rem; font-size: 0.72rem; color: #cbd5e1; margin-bottom: 0.75rem; text-align: left;">
                                    <div style="font-family: 'Press Start 2P'; font-size: 0.52rem; color: #f43f5e; display: block; margin-bottom: 0.4rem; letter-spacing: 0.05em; text-align: center;">
                                        [ TOP GAMES ]
                                    </div>
                                    <div style="display: flex; flex-wrap: wrap;">${gameList}</div>
                                </div>
                            `;
                        }
                    }

                    const archetype = profile.archetype_cluster || 'Cozy_Social_Interactive';
                    const archetypeDisplay = archetype.replace(/_/g, ' ');
                    
                    const isYT = sentiment.source === 'youtube' || 
                                 cleanHandle.toLowerCase().startsWith('uc') || 
                                 (profile.youtube_title && !profile.twitch_display_name && !profile.linked_twitch);
                    const cleanTwitchHandle = cleanHandle.startsWith('@') ? cleanHandle.substring(1) : cleanHandle;
                    let streamLink = isYT 
                        ? `https://youtube.com/channel/${encodeURIComponent(cleanHandle)}` 
                        : `https://twitch.tv/${encodeURIComponent(cleanTwitchHandle)}`;
                    if (streamLink.includes('twitch.tv/@')) {
                        streamLink = streamLink.replace('twitch.tv/@', 'twitch.tv/');
                    } else if (streamLink.includes('twitch.tv/%40')) {
                        streamLink = streamLink.replace('twitch.tv/%40', 'twitch.tv/');
                    }

                    const tagsHTML = (sentiment.game_tags || []).map(t => 
                        `<span style="background: rgba(6, 182, 212, 0.1); border: 1px solid rgba(6, 182, 212, 0.35); color: var(--accent-cyan); padding: 0.1rem 0.3rem; font-size: 0.6rem; font-weight: bold; text-transform: uppercase;">#${escapeHTML(t)}</span>`
                    ).join(' ');

                    const tagsContainer = tagsHTML 
                        ? `<div style="display: flex; gap: 0.25rem; flex-wrap: wrap; margin-bottom: 0.75rem;">${tagsHTML}</div>` 
                        : '';

                    // Priority 1: Check live status in client-side cachedGamesList
                    let liveState = null;
                    if (cachedGamesList && cachedGamesList.length > 0) {
                        for (const g of cachedGamesList) {
                            if (g.top_streamers) {
                                const match = g.top_streamers.find(s => {
                                    const login = s.user_login ? s.user_login.toLowerCase().trim() : '';
                                    const name = s.user_name ? s.user_name.toLowerCase().trim() : '';
                                    const hLower = cleanHandle.toLowerCase().trim();
                                    const twitchLower = (data.linked_twitch || '').toLowerCase().trim();
                                    const ytLower = (data.linked_youtube || '').toLowerCase().trim();
                                    
                                    if (!hLower) return false;
                                    return (login && login === hLower) ||
                                           (name && name === hLower) ||
                                           (twitchLower && login && login === twitchLower) ||
                                           (twitchLower && name && name === twitchLower) ||
                                           (ytLower && login && login === ytLower) ||
                                           (ytLower && name && name === ytLower);
                                });
                                if (match) {
                                    liveState = {
                                        isLive: true,
                                        game: g.title,
                                        viewers: match.viewer_count,
                                        platform: match.platform || (isYT ? 'youtube' : 'twitch')
                                    };
                                    break;
                                }
                            }
                        }
                    }

                    // Priority 2: Check sentiment document values
                    if (!liveState) {
                        const rawViewers = sentiment.viewer_count;
                        const isOfflineText = sentiment.sentiment === 'Offline';
                        const hasViewers = rawViewers !== undefined && rawViewers !== null && rawViewers > 0;
                        
                        if (hasViewers && !isOfflineText) {
                            liveState = {
                                isLive: true,
                                game: sentiment.game_name || profile.primary_game || 'Unknown Game',
                                viewers: rawViewers,
                                platform: isYT ? 'youtube' : 'twitch'
                            };
                        } else {
                            // Check adaptive fallback
                            const adaptive = profile.adaptive_metrics || sentiment.adaptive_metrics || {};
                            const view_val = adaptive.viewer_count || {};
                            const mpm_val = adaptive.msg_per_minute || {};
                            const isCurrentlyActive = (view_val.state_val || 0) > 1.0 || (mpm_val.state_val || 0) > 0.5;

                            if (isCurrentlyActive && !isOfflineText) {
                                liveState = {
                                    isLive: true,
                                    game: sentiment.game_name || profile.primary_game || 'Active Stream',
                                    viewers: Math.round(view_val.state_val || 0),
                                    platform: isYT ? 'youtube' : 'twitch'
                                };
                            } else {
                                liveState = {
                                    isLive: false,
                                    game: 'Offline',
                                    viewers: 0,
                                    platform: isYT ? 'youtube' : 'twitch'
                                };
                            }
                        }
                    }

                    let statusHTML = '';
                    if (liveState.isLive) {
                        statusHTML = `
                            <div style="display: inline-flex; align-items: center; gap: 0.4rem; background: rgba(16, 185, 129, 0.15); border: 1px solid var(--accent-green); color: var(--accent-green); font-family: 'Share Tech Mono'; font-size: 0.75rem; font-weight: bold; padding: 0.15rem 0.5rem; text-transform: uppercase; box-shadow: 0 0 8px rgba(0, 255, 102, 0.15);">
                                🟢 LIVE [INSTANT]
                            </div>
                        `;
                    } else {
                        statusHTML = `
                            <div style="display: inline-flex; align-items: center; gap: 0.4rem; background: rgba(148, 163, 184, 0.1); border: 1px solid #94a3b8; color: #94a3b8; font-family: 'Share Tech Mono'; font-size: 0.75rem; font-weight: bold; padding: 0.15rem 0.5rem; text-transform: uppercase;">
                                ⚪ OFFLINE
                            </div>
                        `;
                    }

                    let ratioHTML = '';
                    if (sentiment.spectator_ratio !== undefined && sentiment.spectator_ratio !== null) {
                        const ratio = sentiment.spectator_ratio;
                        let ratioType = "Cozy Viewer Balance";
                        let ratioColor = "var(--accent-cyan)";
                        if (ratio > 0.4) {
                            ratioType = "High Spectator Hype";
                            ratioColor = "var(--accent-pink)";
                        } else if (ratio < 0.05) {
                            ratioType = "Saturated Player Density";
                            ratioColor = "#94a3b8";
                        }
                        ratioHTML = `
                            <div style="background: rgba(6, 182, 212, 0.05); border: 1px solid rgba(6, 182, 212, 0.2); padding: 0.5rem 0.75rem; font-size: 0.75rem; color: #fff; margin-bottom: 0.75rem;">
                                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.25rem;">
                                    <span>📈 Spectator Ratio:</span>
                                    <strong style="color: ${ratioColor}; font-size: 0.85rem;">${ratio.toFixed(4)}</strong>
                                </div>
                                <div style="font-size: 0.65rem; color: var(--text-muted);">
                                    Vibe: <span style="color: ${ratioColor}; font-weight: bold;">${ratioType}</span> (Helix Viewers / Steam Players)
                                </div>
                            </div>
                        `;
                    }

                    const density = profile.interaction_density || {};
                    const idr = density.interactive_density_rate || 0.0;
                    const mpm = density.msg_per_minute || 0.0;
                    const vol = density.chat_volatility || 0.0;
                    const tier = profile.tier || 'affiliate';
                    const closestWell = profile.closest_gravity_well || '';
                    
                    let idrHTML = '';
                    if (idr > 0.0 || tier === 'micro_streamer') {
                        idrHTML = `
                            <div style="background: rgba(0, 240, 255, 0.05); border: 1px solid rgba(0, 240, 255, 0.2); padding: 0.5rem; font-size: 0.75rem; color: #cbd5e1; margin-bottom: 0.75rem;">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.55rem; color: var(--accent-cyan); margin-bottom: 0.4rem; letter-spacing: 0.05em;">
                                    [ INTERACTIVE DENSITY HUD ]
                                </div>
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.35rem; font-size: 0.72rem;">
                                    <div>IDR Ratio: <strong style="color: var(--accent-pink);">${idr.toFixed(3)}</strong></div>
                                    <div>Tier: <strong style="color: var(--accent-green);">${tier.toUpperCase()}</strong></div>
                                    <div>Msg Speed: <strong>${mpm.toFixed(1)}/m</strong></div>
                                    <div>Volatility: <strong>${vol.toFixed(2)}</strong></div>
                                </div>
                                ${closestWell ? `<div style="margin-top: 0.3rem; border-top: 1px dashed rgba(255,255,255,0.06); padding-top: 0.3rem; font-size: 0.7rem; color: var(--text-muted);">Orbit Alignment: <span style="color: #c084fc; font-weight: bold;">⚡ @${closestWell}</span></div>` : ''}
                            </div>
                        `;
                    }

                    const adaptive = profile.adaptive_metrics || sentiment.adaptive_metrics || {};
                    let adaptiveHTML = '';
                    if (Object.keys(adaptive).length > 0) {
                        const mpm_val = adaptive.msg_per_minute || {};
                        const vol_val = adaptive.chat_volatility || {};
                        const view_val = adaptive.viewer_count || {};
                        const sent_val = adaptive.rolling_sentiment_score || {};
                        
                        adaptiveHTML = `
                            <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.06); padding: 0.5rem; font-size: 0.75rem; color: #cbd5e1; margin-bottom: 0.75rem;">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.55rem; color: #c084fc; margin-bottom: 0.4rem; letter-spacing: 0.05em;">
                                    [ ADAPTIVE STATE INDICES ]
                                </div>
                                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.35rem; font-size: 0.72rem;">
                                    <div>Audience Inertia: <strong>${Math.round(view_val.state_val || 0)}</strong> <span style="font-size: 0.65rem; color: var(--text-muted);">(${Math.round(view_val.last_impulse || 0)} Peak)</span></div>
                                    <div>Msg Speed: <strong>${(mpm_val.state_val || 0).toFixed(1)}/m</strong> <span style="font-size: 0.65rem; color: var(--text-muted);">(${(mpm_val.last_impulse || 0).toFixed(1)} Peak)</span></div>
                                    <div>Volatility: <strong>${(vol_val.state_val || 0).toFixed(2)}</strong> <span style="font-size: 0.65rem; color: var(--text-muted);">(${(vol_val.last_impulse || 0).toFixed(2)} Peak)</span></div>
                                    <div>Sentiment: <strong>${(sent_val.state_val || 0).toFixed(2)}</strong> <span style="font-size: 0.65rem; color: var(--text-muted);">(${(sent_val.last_impulse || 0).toFixed(2)} Peak)</span></div>
                                </div>
                            </div>
                        `;
                    }

                    const breakdown = sentiment.sentiment_breakdown || {};
                    let breakdownHTML = '';
                    let dominantVibeHTML = '';
                    if (Object.keys(breakdown).length > 0) {
                        const cozyPct = Math.round((breakdown.cozy || 0) * 100);
                        const hypePct = Math.round((breakdown.hype || 0) * 100);
                        const polarPct = Math.round((breakdown.polarization || 0) * 100);
                        const spamPct = Math.round((breakdown.spam || 0) * 100);
                        
                        let maxVal = -1;
                        let maxKey = '';
                        for (const [k, v] of Object.entries(breakdown)) {
                            if (v > maxVal) {
                                maxVal = v;
                                maxKey = k;
                            }
                        }
                        if (maxVal > 0.25) {
                            let label = '';
                            let color = '';
                            if (maxKey === 'cozy') { label = '🌿 COZY'; color = 'var(--accent-green)'; }
                            else if (maxKey === 'hype') { label = '⚡ HYPE'; color = 'var(--accent-cyan)'; }
                            else if (maxKey === 'polarization') { label = '🔥 POLARIZED'; color = 'var(--accent-pink)'; }
                            else if (maxKey === 'spam') { label = '👾 SPAMMY'; color = 'var(--accent-yellow)'; }
                            
                            dominantVibeHTML = `
                                <span style="
                                    font-size: 0.55rem;
                                    font-family: 'Press Start 2P';
                                    padding: 0.15rem 0.35rem;
                                    border: 1px solid ${color};
                                    background: rgba(0,0,0,0.4);
                                    color: ${color};
                                    border-radius: 3px;
                                    text-shadow: 0 0 4px ${color};
                                    margin-left: 0.4rem;
                                    display: inline-block;
                                    vertical-align: middle;
                                ">${label}</span>
                            `;
                        }
                        
                        breakdownHTML = `
                            <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.06); padding: 0.5rem; font-size: 0.75rem; color: #cbd5e1; margin-bottom: 0.75rem;">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.55rem; color: var(--accent-pink); margin-bottom: 0.4rem; letter-spacing: 0.05em;">
                                    [ CHAT VIBE BREAKDOWN ]
                                </div>
                                <div style="display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.7rem;">
                                    <div>
                                        <div style="display: flex; justify-content: space-between; font-size: 0.65rem; margin-bottom: 0.1rem;">
                                            <span>🌿 COZY / COMMUNITY:</span>
                                            <span>${cozyPct}%</span>
                                        </div>
                                        <div style="width: 100%; height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; overflow: hidden;">
                                            <div style="width: ${cozyPct}%; height: 100%; background: var(--accent-green);"></div>
                                        </div>
                                    </div>
                                    <div>
                                        <div style="display: flex; justify-content: space-between; font-size: 0.65rem; margin-bottom: 0.1rem;">
                                            <span>⚡ HYPE / EXCITEMENT:</span>
                                            <span>${hypePct}%</span>
                                        </div>
                                        <div style="width: 100%; height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; overflow: hidden;">
                                            <div style="width: ${hypePct}%; height: 100%; background: var(--accent-cyan);"></div>
                                        </div>
                                    </div>
                                    <div>
                                        <div style="display: flex; justify-content: space-between; font-size: 0.65rem; margin-bottom: 0.1rem;">
                                            <span>🔥 POLARIZATION / DRAMA:</span>
                                            <span>${polarPct}%</span>
                                        </div>
                                        <div style="width: 100%; height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; overflow: hidden;">
                                            <div style="width: ${polarPct}%; height: 100%; background: var(--accent-pink);"></div>
                                        </div>
                                    </div>
                                    <div>
                                        <div style="display: flex; justify-content: space-between; font-size: 0.65rem; margin-bottom: 0.1rem;">
                                            <span>👾 SPAM / EMOTE FLOOD:</span>
                                            <span>${spamPct}%</span>
                                        </div>
                                        <div style="width: 100%; height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; overflow: hidden;">
                                            <div style="width: ${spamPct}%; height: 100%; background: var(--accent-yellow);"></div>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        `;
                    }

                    const summaryText = profile.composite_chat_summary || sentiment.summary || '';
                    let summaryHTML = '';
                    if (summaryText) {
                        summaryHTML = `
                            <div style="background: rgba(9, 9, 17, 0.6); border: 1px solid rgba(255, 255, 255, 0.08); padding: 0.75rem; margin-bottom: 0.75rem; border-left: 3px solid var(--accent-cyan);">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.6rem; color: var(--accent-cyan); margin-bottom: 0.4rem; letter-spacing: 0.05em;">[ RECENT CHRONICLE ]</div>
                                <div style="font-size: 0.8rem; line-height: 1.4; color: #cbd5e1;">${escapeHTML(summaryText)}</div>
                            </div>
                        `;
                    } else {
                        summaryHTML = `
                            <div style="background: rgba(9, 9, 17, 0.6); border: 1px dashed rgba(255, 255, 255, 0.1); padding: 0.75rem; margin-bottom: 0.75rem; text-align: center;">
                                <div style="font-size: 0.75rem; color: var(--text-muted); font-style: italic;">* NO CHRONICLE DATA LOGGED *</div>
                            </div>
                        `;
                    }

                    const activeGameText = liveState.game || 'Offline';
                    const activeViewersVal = liveState.isLive ? `${liveState.viewers.toLocaleString()} watching` : '—';

                    // Check if both Twitch and YouTube are linked/active
                    let streamButtonsHTML = '';
                    if (data.linked_twitch && data.linked_youtube) {
                        let cleanTwitchLinked = data.linked_twitch || '';
                        if (cleanTwitchLinked.startsWith('@')) {
                            cleanTwitchLinked = cleanTwitchLinked.substring(1);
                        }
                        let twitchUrl = sentiment.twitch_url || `https://twitch.tv/${cleanTwitchLinked}`;
                        if (twitchUrl.includes('twitch.tv/@')) {
                            twitchUrl = twitchUrl.replace('twitch.tv/@', 'twitch.tv/');
                        } else if (twitchUrl.includes('twitch.tv/%40')) {
                            twitchUrl = twitchUrl.replace('twitch.tv/%40', 'twitch.tv/');
                        }
                        const ytUrl = sentiment.youtube_url || `https://youtube.com/channel/${data.linked_youtube}`;
                        streamButtonsHTML = `
                            <div style="display: flex; gap: 0.5rem; margin-bottom: 0.25rem;">
                                <a href="${twitchUrl}" target="_blank" style="
                                    flex: 1;
                                    background: #9146FF;
                                    color: #fff;
                                    text-align: center;
                                    text-decoration: none;
                                    font-weight: bold;
                                    font-size: 0.75rem;
                                    padding: 0.5rem 0;
                                    border: 1px solid #fff;
                                    transition: opacity 0.2s;
                                " onmouseover="this.style.opacity='0.8'" onmouseout="this.style.opacity='1'">👾 TWITCH STREAM</a>
                                <a href="${ytUrl}" target="_blank" style="
                                    flex: 1;
                                    background: #FF0000;
                                    color: #fff;
                                    text-align: center;
                                    text-decoration: none;
                                    font-weight: bold;
                                    font-size: 0.75rem;
                                    padding: 0.5rem 0;
                                    border: 1px solid #fff;
                                    transition: opacity 0.2s;
                                " onmouseover="this.style.opacity='0.8'" onmouseout="this.style.opacity='1'">🔴 YOUTUBE STREAM</a>
                            </div>
                        `;
                    } else {
                        streamButtonsHTML = `
                            <div style="display: flex; gap: 0.5rem; margin-bottom: 0.25rem;">
                                <a href="${streamLink}" target="_blank" style="
                                    flex: 1;
                                    background: var(--accent-cyan);
                                    color: #000;
                                    text-align: center;
                                    text-decoration: none;
                                    font-weight: bold;
                                    font-size: 0.85rem;
                                    padding: 0.5rem 0;
                                    border: 1px solid #fff;
                                    transition: opacity 0.2s;
                                " onmouseover="this.style.opacity='0.8'" onmouseout="this.style.opacity='1'">GO TO STREAM ➔</a>
                            </div>
                        `;
                    }

                    // Spotlight and Expose links inside Community Intel section
                    let intelHTML = '';
                    if (data.has_spotlight || data.has_expose) {
                        let spotlightBtn = data.has_spotlight ? `
                            <a href="/spotlight?handle=${encodeURIComponent(cleanHandle)}" target="_blank" style="
                                flex: 1;
                                background: linear-gradient(135deg, var(--accent-magenta) 0%, #a855f7 100%);
                                color: #fff;
                                text-align: center;
                                text-decoration: none;
                                font-weight: bold;
                                font-size: 0.72rem;
                                padding: 0.6rem 0.4rem;
                                border: 1px solid rgba(255, 255, 255, 0.2);
                                border-radius: 6px;
                                display: flex;
                                flex-direction: column;
                                align-items: center;
                                justify-content: center;
                                gap: 0.2rem;
                                transition: all 0.2s ease;
                                text-shadow: 0 1px 2px rgba(0,0,0,0.5);
                            " onmouseover="this.style.opacity='0.9'; this.style.transform='translateY(-1px)';" onmouseout="this.style.opacity='1'; this.style.transform='none';">
                                <span style="font-size: 1.1rem;">📊</span>
                                <span style="font-family: 'Share Tech Mono'; letter-spacing: 0.5px;">SPOTLIGHT DOSSIER</span>
                                <span style="font-size: 0.55rem; font-weight: normal; opacity: 0.8; font-family: sans-serif;">AI Vibe & Sentiment Report</span>
                            </a>
                        ` : '';
                        
                        let exposeBtn = data.has_expose ? `
                            <a href="/expose?handle=${encodeURIComponent(cleanHandle)}" target="_blank" style="
                                flex: 1;
                                background: linear-gradient(135deg, var(--accent-yellow) 0%, #eab308 100%);
                                color: #000;
                                text-align: center;
                                text-decoration: none;
                                font-weight: bold;
                                font-size: 0.72rem;
                                padding: 0.6rem 0.4rem;
                                border: 1px solid rgba(255, 255, 255, 0.2);
                                border-radius: 6px;
                                display: flex;
                                flex-direction: column;
                                align-items: center;
                                justify-content: center;
                                gap: 0.2rem;
                                transition: all 0.2s ease;
                                text-shadow: 0 1px 1px rgba(255,255,255,0.2);
                            " onmouseover="this.style.opacity='0.9'; this.style.transform='translateY(-1px)';" onmouseout="this.style.opacity='1'; this.style.transform='none';">
                                <span style="font-size: 1.1rem;">📰</span>
                                <span style="font-family: 'Share Tech Mono'; letter-spacing: 0.5px;">DAILY EXPOSE</span>
                                <span style="font-size: 0.55rem; font-weight: normal; opacity: 0.8; font-family: sans-serif;">Long-form Archive Article</span>
                            </a>
                        ` : '';
                        
                        intelHTML = `
                            <div style="background: rgba(255, 0, 127, 0.05); border: 1px dashed rgba(255, 0, 127, 0.25); padding: 0.65rem; margin-bottom: 0.75rem; border-radius: 8px;">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.55rem; color: var(--accent-pink); margin-bottom: 0.5rem; letter-spacing: 0.05em; text-align: center;">
                                    [ COMMUNITY INTEL ]
                                </div>
                                <div style="display: flex; gap: 0.4rem; justify-content: center;">
                                    ${spotlightBtn}
                                    ${exposeBtn}
                                </div>
                            </div>
                        `;
                    } else {
                        intelHTML = `
                            <div style="background: rgba(255, 255, 255, 0.02); border: 1px dashed rgba(255, 255, 255, 0.1); padding: 0.65rem; margin-bottom: 0.75rem; text-align: center; border-radius: 8px;">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.55rem; color: var(--text-muted); margin-bottom: 0.5rem; letter-spacing: 0.05em;">
                                    [ COMMUNITY INTEL ]
                                </div>
                                <a href="/spotlight?handle=${encodeURIComponent(cleanHandle)}" target="_blank" style="
                                    display: inline-flex;
                                    flex-direction: column;
                                    align-items: center;
                                    justify-content: center;
                                    background: linear-gradient(135deg, rgba(255, 0, 127, 0.1) 0%, rgba(168, 85, 247, 0.1) 100%);
                                    color: var(--accent-magenta);
                                    border: 1px solid var(--accent-magenta);
                                    border-radius: 6px;
                                    text-decoration: none;
                                    font-family: 'Share Tech Mono';
                                    font-size: 0.75rem;
                                    font-weight: bold;
                                    padding: 0.6rem 0.5rem;
                                    gap: 0.2rem;
                                    transition: all 0.2s ease;
                                    width: 100%;
                                    box-sizing: border-box;
                                " onmouseover="this.style.background='var(--accent-magenta)'; this.style.color='#000'; this.style.transform='translateY(-1px)';" onmouseout="this.style.background='linear-gradient(135deg, rgba(255, 0, 127, 0.1) 0%, rgba(168, 85, 247, 0.1) 100%)'; this.style.color='var(--accent-magenta)'; this.style.transform='none';">
                                    <span style="font-size: 1.1rem;">⚡</span>
                                    <span style="letter-spacing: 0.5px;">GENERATE SPOTLIGHT DOSSIER</span>
                                    <span style="font-size: 0.55rem; font-weight: normal; opacity: 0.8; font-family: sans-serif; text-transform: none;">Create a new live AI profile & dossier</span>
                                </a>
                            </div>
                        `;
                    }

                    const avatarUrl = isYT ? (profile.youtube_avatar || '') : (profile.twitch_avatar || '');
                    const language = profile.language || sentiment.language || 'en';
                    const schedule = profile.schedule || null;
                    let scheduleHTML = '';
                    if (schedule && schedule.segments && schedule.segments.length > 0) {
                        const nextSegments = schedule.segments.slice(0, 3).map(s => {
                            const startTime = new Date(s.start_time).toLocaleDateString([], {weekday: 'short', hour: '2-digit', minute:'2-digit'});
                            return `<div style="font-size: 0.7rem; color: #cbd5e1; margin-bottom: 0.2rem; font-family: 'Share Tech Mono';">📅 <strong>${startTime}</strong> - ${escapeHTML(s.title || 'Live Stream')}</div>`;
                        }).join('');
                        scheduleHTML = `
                            <div style="background: rgba(168, 85, 247, 0.05); border: 1px solid rgba(168, 85, 247, 0.2); padding: 0.5rem; font-size: 0.75rem; color: #cbd5e1; margin-bottom: 0.75rem;">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.55rem; color: #c084fc; margin-bottom: 0.4rem; letter-spacing: 0.05em;">
                                    [ UPCOMING TRANSMISSIONS ]
                                </div>
                                ${nextSegments}
                            </div>
                        `;
                    }

                    const bio = isYT ? (profile.youtube_description || '') : (profile.twitch_description || '');
                    let bioHTML = '';
                    if (bio && bio.trim()) {
                        bioHTML = `
                            <div style="background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06); padding: 0.5rem; font-size: 0.72rem; color: #94a3b8; margin-bottom: 0.75rem; font-family: sans-serif; line-height: 1.4;">
                                <div style="font-family: 'Press Start 2P'; font-size: 0.55rem; color: var(--accent-cyan); margin-bottom: 0.35rem; letter-spacing: 0.05em;">
                                    [ BIOGRAPHICAL ARCHIVE ]
                                </div>
                                <div>${escapeHTML(bio.length > 250 ? bio.substring(0, 250) + "..." : bio)}</div>
                            </div>
                        `;
                    }

                    infoEl.innerHTML = `
                        <div style="display: flex; flex-direction: column; gap: 0.4rem; margin-bottom: 0.75rem; border-bottom: 1px dashed rgba(255,255,255,0.08); padding-bottom: 0.6rem;">
                            <div style="display: flex; justify-content: space-between; align-items: center; gap: 0.5rem; flex-wrap: wrap;">
                                <div style="display: flex; gap: 0.6rem; align-items: center;">
                                    ${avatarUrl ? `<img src="${escapeHTML(avatarUrl)}" style="width: 32px; height: 32px; border-radius: 4px; border: 1px solid var(--accent-cyan); object-fit: cover;" />` : `<span style="font-size: 1.3rem;">${isYT ? '🔴' : '👾'}</span>`}
                                    <div style="font-family: 'Press Start 2P'; font-size: 0.8rem; color: #fff; line-height: 1.2; word-break: break-all;">
                                        ${escapeHTML(data.display_name || cleanHandle)}
                                        ${dominantVibeHTML}
                                    </div>
                                </div>
                                <div style="flex-shrink: 0;">
                                    ${statusHTML}
                                </div>
                            </div>
                            <div style="display: flex; flex-direction: column; gap: 0.15rem; font-size: 0.7rem; color: var(--text-muted);">
                                <div id="drawer-tribe-details"></div>
                                <div>Active Game: <span style="color: var(--accent-cyan); font-weight: bold;">${escapeHTML(activeGameText)}</span></div>
                                <div>Language: <span style="color: var(--accent-pink); font-weight: bold; text-transform: uppercase;">${escapeHTML(language)}</span></div>
                                <div style="margin-top: 0.35rem; display: flex; justify-content: flex-start;">
                                    <button class="btn-secondary" style="font-size: 0.65rem; padding: 0.15rem 0.4rem; border: 1px solid rgba(0, 240, 255, 0.3); background: rgba(0, 240, 255, 0.05); color: var(--accent-cyan); cursor: pointer; font-family: 'Share Tech Mono'; font-weight: bold; border-radius: 0px !important;" onclick="openStreamerProfileDrawer('${escapeHTML(cleanHandle)}', false, true)">
                                        🔄 RE-SYNC PROFILE
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div id="drawer-starmap-button-container" style="display: none; margin-bottom: 0.75rem;"></div>

                        <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.5rem; margin-bottom: 0.75rem;">
                            <div style="background: rgba(168, 85, 247, 0.08); border: 1px solid rgba(168, 85, 247, 0.25); padding: 0.5rem; font-size: 0.75rem; color: #d8b4fe;">
                                <span style="font-family: 'Press Start 2P'; font-size: 0.55rem; color: #c084fc; display: block; margin-bottom: 0.2rem; letter-spacing: 0.05em;">[ ARCHETYPE ]</span>
                                <strong>${archetypeDisplay}</strong><br>
                                <span style="font-size: 0.65rem; opacity: 0.75;">Status: ${profile.fabric_status ? profile.fabric_status.toUpperCase() : 'PRELIMINARY'}</span>
                            </div>
                            <div style="background: rgba(16, 185, 129, 0.05); border: 1px solid rgba(16, 185, 129, 0.2); padding: 0.5rem; font-size: 0.75rem; color: #a7f3d0;">
                                <span style="font-family: 'Press Start 2P'; font-size: 0.55rem; color: var(--accent-green); display: block; margin-bottom: 0.2rem; letter-spacing: 0.05em;">[ VIEWERSHIP ]</span>
                                <strong>${activeViewersVal}</strong><br>
                                <span style="font-size: 0.65rem; color: var(--text-muted);">Source: ${sentiment.source ? sentiment.source.toUpperCase() : 'CACHE'}</span>
                            </div>
                        </div>

                        ${bioHTML}
                        ${idrHTML}
                        ${youtubeStatsHTML}
                        ${recentVideosHTML}
                        ${topGamesHTML}
                        ${scheduleHTML}
                        ${summaryHTML}
                        ${tagsContainer}
                        ${ratioHTML}
                        ${intelHTML}
                        ${breakdownHTML}
                        ${adaptiveHTML}
                        ${streamButtonsHTML}
                    `;

                    const buttonsContainer = document.getElementById('drawer-live-radar-buttons-container');
                    if (buttonsContainer) {
                        let buttonsHTML = '';
                        const hasTwitch = data.linked_twitch;
                        const hasYT = data.linked_youtube;
                        
                        if (hasTwitch && hasYT) {
                            buttonsHTML = `
                                <div style="display: flex; flex-direction: column; gap: 0.4rem; width: 100%;">
                                    <div style="font-size: 0.65rem; color: var(--accent-cyan); font-family: 'Press Start 2P'; margin-bottom: 0.15rem; display: flex; align-items: center; gap: 0.35rem;">
                                        <span>👾</span> TWITCH CHAT TELEMETRY
                                    </div>
                                    <div style="display: flex; gap: 0.4rem; margin-bottom: 0.4rem;">
                                        <button id="btn-live-radar-start-twitch" class="btn" style="flex: 1; font-size: 0.72rem; padding: 0.35rem 0.2rem; border: 1px solid var(--accent-cyan); background: rgba(0, 240, 255, 0.05); color: var(--accent-cyan); cursor: pointer; font-family: 'Share Tech Mono'; font-weight: bold; border-radius: 0px;" onclick="startLiveChatRadar('twitch')">ACTIVATE TWITCH RADAR</button>
                                        <button id="btn-live-radar-stream-twitch" class="btn" style="flex: 1; font-size: 0.72rem; padding: 0.35rem 0.2rem; border: 1px solid var(--accent-pink); background: rgba(255, 0, 127, 0.05); color: var(--accent-pink); cursor: pointer; font-family: 'Share Tech Mono'; font-weight: bold; border-radius: 0px;" onclick="toggleLiveChatStream('twitch')">STREAM TWITCH CHAT</button>
                                    </div>
                                    <div style="font-size: 0.65rem; color: #ef4444; font-family: 'Press Start 2P'; margin-bottom: 0.15rem; display: flex; align-items: center; gap: 0.35rem;">
                                        <span>🔴</span> YOUTUBE CHAT TELEMETRY
                                    </div>
                                    <div style="display: flex; gap: 0.4rem;">
                                        <button id="btn-live-radar-start-youtube" class="btn" style="flex: 1; font-size: 0.72rem; padding: 0.35rem 0.2rem; border: 1px solid #ef4444; background: rgba(239, 68, 68, 0.05); color: #fca5a5; cursor: pointer; font-family: 'Share Tech Mono'; font-weight: bold; border-radius: 0px;" onclick="startLiveChatRadar('youtube')">ACTIVATE YT RADAR</button>
                                        <button id="btn-live-radar-stream-youtube" class="btn" style="flex: 1; font-size: 0.72rem; padding: 0.35rem 0.2rem; border: 1px solid var(--accent-pink); background: rgba(255, 0, 127, 0.05); color: var(--accent-pink); cursor: pointer; font-family: 'Share Tech Mono'; font-weight: bold; border-radius: 0px;" onclick="toggleLiveChatStream('youtube')">STREAM YT CHAT</button>
                                    </div>
                                </div>
                            `;
                        } else if (hasYT || /^[uU][cC][a-zA-Z0-9_-]{22}$/.test(cleanHandle)) {
                            buttonsHTML = `
                                <div style="display: flex; gap: 0.4rem; width: 100%;">
                                    <button id="btn-live-radar-start-youtube" class="btn" style="flex: 1; font-size: 0.72rem; padding: 0.4rem; border: 1px solid #ef4444; background: rgba(239, 68, 68, 0.05); color: #fca5a5; cursor: pointer; font-family: 'Share Tech Mono'; font-weight: bold; border-radius: 0px;" onclick="startLiveChatRadar('youtube')">ACTIVATE YOUTUBE RADAR</button>
                                    <button id="btn-live-radar-stream-youtube" class="btn" style="flex: 1; font-size: 0.72rem; padding: 0.4rem; border: 1px solid var(--accent-pink); background: rgba(255, 0, 127, 0.05); color: var(--accent-pink); cursor: pointer; font-family: 'Share Tech Mono'; font-weight: bold; border-radius: 0px;" onclick="toggleLiveChatStream('youtube')">STREAM YOUTUBE CHAT</button>
                                </div>
                            `;
                        } else {
                            buttonsHTML = `
                                <div style="display: flex; gap: 0.4rem; width: 100%;">
                                    <button id="btn-live-radar-start-twitch" class="btn" style="flex: 1; font-size: 0.72rem; padding: 0.4rem; border: 1px solid var(--accent-cyan); background: rgba(0, 240, 255, 0.05); color: var(--accent-cyan); cursor: pointer; font-family: 'Share Tech Mono'; font-weight: bold; border-radius: 0px;" onclick="startLiveChatRadar('twitch')">ACTIVATE TWITCH RADAR</button>
                                    <button id="btn-live-radar-stream-twitch" class="btn" style="flex: 1; font-size: 0.72rem; padding: 0.4rem; border: 1px solid var(--accent-pink); background: rgba(255, 0, 127, 0.05); color: var(--accent-pink); cursor: pointer; font-family: 'Share Tech Mono'; font-weight: bold; border-radius: 0px;" onclick="toggleLiveChatStream('twitch')">STREAM TWITCH CHAT</button>
                                </div>
                            `;
                        }
                        buttonsContainer.innerHTML = buttonsHTML;
                    }

                    const dotTwitch = document.getElementById('vibe-dot');
                    const dotYT = document.getElementById('vibe-dot-youtube');
                    const coordDisplay = document.getElementById('vibe-coordinates-display');
                    
                    const twitchActive = sentiment.twitch_viewers > 0;
                    const ytActive = sentiment.youtube_viewers > 0;

                    const mu = twitchActive ? (sentiment.twitch_rolling_sentiment || 0.0) : (ytActive ? (sentiment.youtube_rolling_sentiment || 0.0) : (sentiment.rolling_sentiment_score || 0.0));
                    const sigma = twitchActive ? (sentiment.twitch_chat_volatility || 0.0) : (ytActive ? (sentiment.youtube_chat_volatility || 0.0) : (sentiment.chat_volatility || 0.0));

                    let coordText = '';
                    if (twitchActive) {
                        const tMu = sentiment.twitch_rolling_sentiment || 0.0;
                        const tSigma = sentiment.twitch_chat_volatility || 0.0;
                        const tCx = 30 + (tMu * 24);
                        const tCy = 30 - ((Math.min(tSigma, 1.2) / 1.2) * 24);
                        dotTwitch.setAttribute('cx', tCx.toFixed(1));
                        dotTwitch.setAttribute('cy', tCy.toFixed(1));
                        dotTwitch.style.display = 'block';
                        coordText += `Twitch: μ=${tMu > 0 ? '+' : ''}${tMu.toFixed(2)} σ=${tSigma.toFixed(2)}`;
                    } else {
                        const cx = 30 + (mu * 24);
                        const cy = 30 - ((Math.min(sigma, 1.2) / 1.2) * 24);
                        dotTwitch.setAttribute('cx', cx.toFixed(1));
                        dotTwitch.setAttribute('cy', cy.toFixed(1));
                        dotTwitch.style.display = 'block';
                        coordText += `μ=${mu > 0 ? '+' : ''}${mu.toFixed(2)} | σ=${sigma.toFixed(2)}`;
                    }

                    if (ytActive && dotYT) {
                        const yMu = sentiment.youtube_rolling_sentiment || 0.0;
                        const ySigma = sentiment.youtube_chat_volatility || 0.0;
                        const yCx = 30 + (yMu * 24);
                        const yCy = 30 - ((Math.min(ySigma, 1.2) / 1.2) * 24);
                        dotYT.setAttribute('cx', yCx.toFixed(1));
                        dotYT.setAttribute('cy', yCy.toFixed(1));
                        dotYT.style.display = 'block';
                        if (coordText.indexOf('Twitch') !== -1) {
                            coordText = `Twitch: μ=${(sentiment.twitch_rolling_sentiment || 0.0).toFixed(2)} σ=${(sentiment.twitch_chat_volatility || 0.0).toFixed(2)} | YT: μ=${yMu > 0 ? '+' : ''}${yMu.toFixed(2)} σ=${ySigma.toFixed(2)}`;
                        } else {
                            coordText = `YouTube: μ=${yMu > 0 ? '+' : ''}${yMu.toFixed(2)} σ=${ySigma.toFixed(2)}`;
                        }
                    } else if (dotYT) {
                        dotYT.style.display = 'none';
                    }

                    coordDisplay.textContent = coordText;

                    let vibeDesc = "cozy / balanced";
                    if (mu > 0.3) {
                        vibeDesc = sigma > 0.5 ? "hype / positive" : "cozy / positive";
                    } else if (mu < -0.3) {
                        vibeDesc = sigma > 0.5 ? "chaotic / volatile" : "tense / muted";
                    } else if (sigma > 0.6) {
                        vibeDesc = "high energy / hype";
                    }
                    document.getElementById('vibe-description-display').textContent = `Vibe: ${vibeDesc}`;

                    const timelineEl = document.getElementById('drawer-timeline');
                    timelineEl.innerHTML = '';
                    
                    const history = data.history || [];
                    if (history.length === 0) {
                        timelineEl.innerHTML = `<div style="font-size: 0.75rem; color: var(--text-muted); font-style: italic; text-align: center; margin-top: 1rem;">No recent chat summaries recorded.</div>`;
                    } else {
                        const groups = [];
                        history.forEach(h => {
                            const summaryText = (h.summary || '').trim();
                            if (!summaryText) {
                                groups.push({
                                    summary: '',
                                    game_name: h.game_name,
                                    timestamps: [h.timestamp],
                                    records: [h]
                                });
                                return;
                            }
                            
                            let match = groups.find(g => g.summary === summaryText);
                            if (match) {
                                match.timestamps.push(h.timestamp);
                                match.records.push(h);
                            } else {
                                groups.push({
                                    summary: summaryText,
                                    game_name: h.game_name,
                                    timestamps: [h.timestamp],
                                    records: [h]
                                });
                            }
                        });

                        groups.forEach(g => {
                            g.timestamps.sort((a, b) => b - a);
                            const latestTs = g.timestamps[0];
                            const oldestTs = g.timestamps[g.timestamps.length - 1];
                            
                            let timeSpanStr = '';
                            const formatTime = (ts) => new Date(ts * 1000).toLocaleString([], {month: 'short', day: 'numeric', hour: '2-digit', minute:'2-digit'});
                            if (g.timestamps.length > 1 && (latestTs - oldestTs) > 30) {
                                timeSpanStr = `${formatTime(oldestTs)} - ${new Date(latestTs * 1000).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
                            } else {
                                timeSpanStr = formatTime(latestTs);
                            }

                            const distinctTriggers = new Set();
                            const metricsList = [];
                            g.records.forEach(r => {
                                if (r.last_highlight && r.last_highlight.trigger_type) {
                                    distinctTriggers.add(r.last_highlight.trigger_type);
                                }
                                
                                let vibeColor = 'var(--text-muted)';
                                if (r.sentiment === 'Positive') vibeColor = 'var(--accent-green)';
                                else if (r.sentiment === 'Negative') vibeColor = 'var(--accent-pink)';
                                else if (r.sentiment === 'Mixed') vibeColor = 'var(--accent-yellow)';
                                
                                metricsList.push({
                                    mpm: r.msg_per_minute || 0,
                                    sentiment: r.sentiment || 'Neutral',
                                    vibeColor: vibeColor
                                });
                            });

                            let triggerBadgeStr = '';
                            if (distinctTriggers.size > 0) {
                                const triggersArray = Array.from(distinctTriggers).map(t => escapeHTML(t));
                                triggerBadgeStr = `<div style="font-size: 0.65rem; color: var(--accent-pink); margin-top: 0.2rem; font-weight: bold; letter-spacing: 0.05em;">💥 TRIGGERS: ${triggersArray.join(' | ')}</div>`;
                            }

                            const metricsString = metricsList.map(m => {
                                return `<span style="border: 1px solid rgba(255,255,255,0.08); background: rgba(0,0,0,0.25); padding: 0.05rem 0.35rem; font-size: 0.65rem; color: var(--text-muted); display: inline-flex; align-items: center; gap: 0.25rem;">
                                    <span>${m.mpm.toFixed(1)} mpm</span>
                                    <strong style="color: ${m.vibeColor};">${m.sentiment}</strong>
                                </span>`;
                            }).join(' ');

                            timelineEl.innerHTML += `
                                <div style="position: relative; margin-bottom: 0.75rem; border-bottom: 1px dashed rgba(255,255,255,0.05); padding-bottom: 0.5rem; text-align: left;">
                                    <div style="display: flex; justify-content: space-between; align-items: center; font-size: 0.72rem; color: var(--text-muted); margin-bottom: 0.25rem;">
                                        <span style="color: #fff; font-weight: 600;">🎮 ${escapeHTML(g.game_name)}</span>
                                        <span>${timeSpanStr}</span>
                                    </div>
                                    <div style="font-size: 0.78rem; line-height: 1.35; color: #cbd5e1; font-style: italic; margin-bottom: 0.4rem;">"${escapeHTML(g.summary || 'No summary available.')}"</div>
                                    <div style="display: flex; flex-direction: column; gap: 0.25rem;">
                                        <div style="display: flex; flex-wrap: wrap; gap: 0.3rem; align-items: center;">
                                            <span style="font-size: 0.65rem; color: var(--text-muted); text-transform: uppercase;">Checkpoints:</span>
                                            ${metricsString}
                                        </div>
                                        ${triggerBadgeStr}
                                    </div>
                                </div>
                            `;
                        });
                    }

                    const clipsSection = document.getElementById('drawer-clips-section');
                    const clipsList = document.getElementById('drawer-clips-list');
                    if (clipsSection && clipsList) {
                        clipsList.innerHTML = '';
                        const clips = profile.recent_clips || sentiment.recent_clips || [];
                        if (clips.length > 0) {
                            clipsSection.style.display = 'flex';
                            clips.forEach(c => {
                                clipsList.innerHTML += `
                                    <a href="${escapeHTML(c.url)}" target="_blank" style="
                                        display: flex;
                                        justify-content: space-between;
                                        align-items: center;
                                        background: rgba(0, 0, 0, 0.4);
                                        border: 1px solid rgba(0, 240, 255, 0.2);
                                        padding: 0.5rem 0.75rem;
                                        text-decoration: none;
                                        color: #fff;
                                        font-size: 0.8rem;
                                        font-family: 'Share Tech Mono';
                                        transition: all 0.2s;
                                        box-shadow: 0 2px 4px rgba(0,0,0,0.5);
                                    " onmouseover="this.style.background='rgba(0, 240, 255, 0.08)'; this.style.borderColor='var(--accent-cyan)'; this.style.boxShadow='0 0 8px rgba(0, 240, 255, 0.2)';" onmouseout="this.style.background='rgba(0, 0, 0, 0.4)'; this.style.borderColor='rgba(0, 240, 255, 0.2)'; this.style.boxShadow='0 2px 4px rgba(0,0,0,0.5)';">
                                        <span style="overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 240px; font-weight: 500;">▶ ${escapeHTML(c.title)}</span>
                                        <span style="color: var(--accent-cyan); font-size: 0.7rem; font-weight: bold; margin-left: 0.5rem; flex-shrink: 0;">👁️ ${c.view_count.toLocaleString()}</span>
                                    </a>
                                `;
                            });
                        } else {
                            clipsSection.style.display = 'none';
                        }
                    }

                    // Render history sparklines
                    const historySection = document.getElementById('drawer-history-section');
                    const historyList = document.getElementById('drawer-history-list');
                    if (historySection && historyList) {
                        historyList.innerHTML = '';
                        if (history.length >= 2) {
                            historySection.style.display = 'flex';
                            historyList.innerHTML += createSparklineSVG(history, 'viewer_count', 'var(--accent-green)');
                            historyList.innerHTML += createSparklineSVG(history, 'msg_per_minute', 'var(--accent-cyan)');
                            historyList.innerHTML += createSparklineSVG(history, 'chat_volatility', 'var(--accent-pink)');
                            historyList.innerHTML += createSparklineSVG(history, 'rolling_sentiment_score', 'var(--accent-yellow)');
                        } else {
                            historySection.style.display = 'none';
                        }
                    }

                    // Fetch correlations
                    fetch(`/api/streamers/${encodeURIComponent(cleanHandle)}/correlations`, { signal })
                        .then(res => res.json())
                        .then(corrData => {
                            if (currentDrawerStreamer !== cleanHandle) {
                                return;
                            }
                            // Populate tribe label and bellwether rank
                            const tribeEl = document.getElementById('drawer-tribe-details');
                            if (tribeEl && corrData.vibe_tribe) {
                                const dotHtml = `<span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:${corrData.tribe_color || 'var(--accent-cyan)'}; margin-right:4px;"></span>`;
                                const bellRankText = corrData.bellwether_rank ? ` · ⚡ Bellwether #${corrData.bellwether_rank}` : '';
                                tribeEl.innerHTML = `${dotHtml} ${escapeHTML(corrData.vibe_tribe)}${bellRankText}`;
                            }

                            // Render starmap jump button
                            const starmapBtnContainer = document.getElementById('drawer-starmap-button-container');
                            if (starmapBtnContainer && corrData.vibe_tribe && corrData.tribe_id) {
                                starmapBtnContainer.style.display = 'block';
                                starmapBtnContainer.innerHTML = `
                                    <button onclick="goToStarMapTribe('${corrData.tribe_id}', '${escapeHTML(cleanHandle)}')" style="
                                        width: 100%;
                                        background: transparent;
                                        color: ${corrData.tribe_color || 'var(--accent-cyan)'};
                                        border: 2px solid ${corrData.tribe_color || 'var(--accent-cyan)'};
                                        font-family: 'Press Start 2P';
                                        font-size: 0.55rem;
                                        padding: 0.45rem 0;
                                        cursor: pointer;
                                        box-shadow: 0 0 10px rgba(0, 240, 255, 0.1);
                                        transition: all 0.2s ease;
                                        border-radius: 0px !important;
                                    " onmouseover="this.style.background='${corrData.tribe_color || 'var(--accent-cyan)'}'; this.style.color='#000';" onmouseout="this.style.background='transparent'; this.style.color='${corrData.tribe_color || 'var(--accent-cyan)'}';">
                                        ⭐ VIEW IN ${corrData.vibe_tribe.toUpperCase()} MAP
                                    </button>
                                `;
                            }

                            renderVibeConnections(corrData);
                        })
                        .catch(err => {
                            if (err.name === 'AbortError') return;
                            console.error("Error loading correlations:", err);
                            const section = document.getElementById('drawer-correlations-section');
                            if (section) section.style.display = 'none';
                        });

                    drawer.style.right = '0px';
                })
                .catch(err => {
                    if (activeProfileLoadingInterval) {
                        clearInterval(activeProfileLoadingInterval);
                        activeProfileLoadingInterval = null;
                    }
                    if (err.name === 'AbortError') return;
                    console.error("Error loading streamer profile drawer:", err);
                    
                    const infoEl = document.getElementById('drawer-profile-info');
                    if (infoEl) {
                        infoEl.innerHTML = `
                            <div style="text-align: center; padding: 3rem 1rem; font-family: 'Press Start 2P'; font-size: 0.72rem; color: var(--accent-pink);">
                                <div style="display: inline-block; padding: 0.85rem; border: 1px solid var(--accent-pink); background: rgba(255, 0, 127, 0.05); margin-bottom: 1.5rem;">
                                    [ SYNCHRONIZATION FAILED ]
                                </div>
                                <p style="font-family: 'Share Tech Mono'; font-size: 0.95rem; color: #fff; line-height: 1.4; margin-bottom: 0.6rem;">
                                    ${escapeHTML(err.message)}
                                </p>
                                <p style="font-family: 'Share Tech Mono'; font-size: 0.8rem; color: var(--text-muted); line-height: 1.4; max-width: 320px; margin: 0 auto; margin-top: 1rem;">
                                    If you were re-syncing this profile, make sure you have supplied a valid Gemini API Key in the settings panel.
                                </p>
                            </div>
                        `;
                    }
                });
        }

        function goToStarMapTribe(tribeId, handle) {
            closeStreamerProfileDrawer();
            switchTab('starmap');
            const checkAndZoom = () => {
                if (starmapData && starmapData.clusters && starmapData.clusters[tribeId]) {
                    zoomToCluster(tribeId, null, null);
                } else {
                    setTimeout(checkAndZoom, 100);
                }
            };
            checkAndZoom();
        }

        let activeChatStreamSource = null;
        let liveRadarTimer = null;
        let currentDrawerStreamer = null;
        let activeProfileAbortController = null;
        let currentDrawerLinkedTwitch = null;
        let currentDrawerLinkedYoutube = null;
        let activeProfileLoadingInterval = null;
        let matchmakerBtnInterval = null;

        function startLiveChatRadar(platform) {
            const baseHandle = currentDrawerStreamer;
            if (!baseHandle) return;

            // Determine target handle based on platform
            let handle = baseHandle;
            if (platform === 'youtube' && currentDrawerLinkedYoutube) {
                handle = currentDrawerLinkedYoutube;
            } else if (platform === 'twitch' && currentDrawerLinkedTwitch) {
                handle = currentDrawerLinkedTwitch;
            }

            const btnId = platform === 'youtube' ? 'btn-live-radar-start-youtube' : 'btn-live-radar-start-twitch';
            const btn = document.getElementById(btnId);
            const statusText = document.getElementById('live-radar-status');
            const consoleBox = document.getElementById('live-radar-console');
            const logEl = document.getElementById('live-radar-log');
            const progress = document.getElementById('live-radar-progress');

            if (!statusText || !consoleBox || !logEl || !progress) return;

            // Close any active stream first
            if (activeChatStreamSource) {
                activeChatStreamSource.close();
                activeChatStreamSource = null;
                const streamBtnYT = document.getElementById('btn-live-radar-stream-youtube');
                const streamBtnTwitch = document.getElementById('btn-live-radar-stream-twitch');
                [streamBtnYT, streamBtnTwitch].forEach(streamBtn => {
                    if (streamBtn) {
                        streamBtn.textContent = streamBtn.id.includes('youtube') ? 'STREAM YT CHAT' : 'STREAM TWITCH CHAT';
                        streamBtn.style.background = 'rgba(255, 0, 127, 0.05)';
                        streamBtn.style.color = 'var(--accent-pink)';
                    }
                });
            }
            const streamBox = document.getElementById('live-chat-stream-box');
            if (streamBox) streamBox.style.display = 'none';

            if (btn) {
                btn.disabled = true;
                btn.style.opacity = '0.5';
            }
            statusText.textContent = 'SCANNING...';
            consoleBox.style.display = 'flex';
            logEl.innerHTML = '';
            progress.style.width = '0%';

            const addLog = (text) => {
                const div = document.createElement('div');
                div.textContent = `[${new Date().toLocaleTimeString()}] ${text}`;
                logEl.appendChild(div);
                consoleBox.scrollTop = consoleBox.scrollHeight;
            };

            const isYT = platform === 'youtube' || /^[uU][cC][a-zA-Z0-9_-]{22}$/.test(handle);
            addLog(`Initializing Live Chat Radar for ${isYT ? '' : '@'}${handle}...`);
            if (isYT) {
                addLog(`Establishing connection to YouTube Live chat scraper...`);
            } else {
                addLog(`Establishing connection to Twitch IRC node...`);
            }

            let seconds = 0;
            const duration = 30;
            progress.style.width = '0%';
            
            if (liveRadarTimer) clearInterval(liveRadarTimer);
            
            const analysisModel = localStorage.getItem('gemini_model_analysis') || 'gemma-4-31b-it';
            const monitorPromise = fetch(`/api/streamers/${encodeURIComponent(handle)}/live-monitor`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-Gemini-Analysis-Model': analysisModel
                }
            }).then(res => res.json());

            liveRadarTimer = setInterval(() => {
                seconds += 0.5;
                const percent = Math.min((seconds / duration) * 100, 95);
                progress.style.width = `${percent}%`;

                if (seconds === 3.0) {
                    if (isYT) {
                        addLog(`Connected live parser. Joined channel ${handle}.`);
                        addLog(`Buffering YouTube live chat frames...`);
                    } else {
                        addLog(`Connected anonymous node. Joined channel #${handle.toLowerCase()}.`);
                        addLog(`Sniffing IRC chat packets...`);
                    }
                } else if (seconds === 10.0) {
                    addLog(`Received message stream. Analyzing frequency metrics...`);
                } else if (seconds === 20.0) {
                    addLog(`Running real-time Gemini sentiment classification...`);
                }
            }, 500);

            monitorPromise.then(data => {
                clearInterval(liveRadarTimer);
                progress.style.width = '100%';
                if (btn) {
                    btn.disabled = false;
                    btn.style.opacity = '1';
                }

                if (data.status === 'offline') {
                    statusText.textContent = 'OFFLINE';
                    addLog(`⚠ Monitoring aborted: No chat activity detected (channel offline).`);
                } else if (data.status === 'success') {
                    statusText.textContent = 'COMPLETE';
                    addLog(`✔ Scan complete: ${data.messages_count} messages processed.`);
                    addLog(`Chat Speed: ${data.mpm.toFixed(1)} msg/min.`);
                    addLog(`Sentiment score: ${data.sentiment_score.toFixed(2)} (${data.sentiment.toUpperCase()}).`);
                    addLog(`Chronicle: "${data.summary}"`);
                    
                    setTimeout(() => {
                        openStreamerProfileDrawer(baseHandle, true);
                    }, 2000);
                } else {
                    statusText.textContent = 'ERROR';
                    addLog(`⚠ Scan failed: ${data.detail || data.message || 'Unknown error.'}`);
                }
            }).catch(err => {
                clearInterval(liveRadarTimer);
                if (btn) {
                    btn.disabled = false;
                    btn.style.opacity = '1';
                }
                statusText.textContent = 'ERROR';
                addLog(`⚠ Fatal: Failed to reach metrics server.`);
            });
        }

        function toggleLiveChatStream(platform) {
            const baseHandle = currentDrawerStreamer;
            if (!baseHandle) return;

            // Determine target handle based on platform
            let handle = baseHandle;
            if (platform === 'youtube' && currentDrawerLinkedYoutube) {
                handle = currentDrawerLinkedYoutube;
            } else if (platform === 'twitch' && currentDrawerLinkedTwitch) {
                handle = currentDrawerLinkedTwitch;
            }

            const btnId = platform === 'youtube' ? 'btn-live-radar-stream-youtube' : 'btn-live-radar-stream-twitch';
            const btn = document.getElementById(btnId);
            const streamBox = document.getElementById('live-chat-stream-box');
            const streamLog = document.getElementById('live-chat-stream-log');

            if (!btn || !streamBox || !streamLog) return;

            if (activeChatStreamSource) {
                activeChatStreamSource.close();
                activeChatStreamSource = null;
                btn.textContent = platform === 'youtube' ? 'STREAM YT CHAT' : 'STREAM TWITCH CHAT';
                btn.style.background = 'rgba(255, 0, 127, 0.05)';
                btn.style.color = 'var(--accent-pink)';
                streamBox.style.display = 'none';
            } else {
                // Hide radar console when streaming chat
                const radarConsole = document.getElementById('live-radar-console');
                if (radarConsole) radarConsole.style.display = 'none';

                streamBox.style.display = 'block';
                streamLog.innerHTML = `<div style="color: var(--accent-cyan)">Connecting stream console...</div>`;
                btn.textContent = 'STOP STREAM';
                btn.style.background = 'var(--accent-pink)';
                btn.style.color = '#000';

                activeChatStreamSource = new EventSource(`/api/streamers/${encodeURIComponent(handle)}/chat-stream`);
                
                activeChatStreamSource.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        const row = document.createElement('div');
                        if (data.sender === 'SYSTEM') {
                            row.style.color = 'var(--accent-cyan)';
                            row.textContent = `[SYSTEM] ${data.message}`;
                        } else {
                            row.innerHTML = `<span style="color: var(--accent-pink)">@${escapeHTML(data.sender)}</span>: ${escapeHTML(data.message)}`;
                        }
                        streamLog.appendChild(row);
                        streamBox.scrollTop = streamBox.scrollHeight;
                        
                        while (streamLog.childNodes.length > 50) {
                            streamLog.removeChild(streamLog.firstChild);
                        }
                    } catch (e) {
                        const row = document.createElement('div');
                        row.style.color = 'var(--text-muted)';
                        row.textContent = event.data;
                        streamLog.appendChild(row);
                        streamBox.scrollTop = streamBox.scrollHeight;
                    }
                };

                activeChatStreamSource.onerror = (err) => {
                    const row = document.createElement('div');
                    row.style.color = 'var(--accent-pink)';
                    row.textContent = `[SYSTEM] Connection terminated.`;
                    streamLog.appendChild(row);
                    activeChatStreamSource.close();
                    activeChatStreamSource = null;
                    btn.textContent = platform === 'youtube' ? 'STREAM YT CHAT' : 'STREAM TWITCH CHAT';
                    btn.style.background = 'rgba(255, 0, 127, 0.05)';
                    btn.style.color = 'var(--accent-pink)';
                };
            }
        }

        function closeStreamerProfileDrawer() {
            if (activeChatStreamSource) {
                activeChatStreamSource.close();
                activeChatStreamSource = null;
            }
            if (liveRadarTimer) {
                clearInterval(liveRadarTimer);
                liveRadarTimer = null;
            }
            const drawer = document.getElementById('streamer-profile-drawer');
            if (drawer) {
                drawer.style.right = '-450px';
            }
        }

        function renderVibeConnections(corrData) {
            const section = document.getElementById('drawer-correlations-section');
            const list = document.getElementById('drawer-correlations-list');
            if (!section || !list) return;

            const supportive = corrData.supportive || [];
            const opposing = corrData.opposing || [];
            
            if (supportive.length === 0 && opposing.length === 0) {
                section.style.display = 'none';
                return;
            }

            section.style.display = 'flex';
            
            let html = '';
            
            const renderCard = (conn) => {
                const scorePct = Math.round(conn.combined_score * 100);
                const absScore = Math.abs(scorePct);
                
                let barColor = 'var(--accent-cyan)';
                if (conn.tag === 'Hype-Aligned') barColor = 'var(--accent-pink)';
                else if (conn.tag === 'Vibe-Coupled') barColor = 'var(--accent-purple)';
                else if (conn.tag === 'Ecosystem-Parallel') barColor = '#f59e0b';
                else if (conn.tag === 'Counter-Programmed') barColor = '#f43f5e';

                const velocity = conn.convergence_velocity || 0;
                const direction = conn.convergence_direction || 'stable';
                const arrow = direction === 'converging' ? '▲' : direction === 'diverging' ? '▼' : '●';
                const velColor = direction === 'converging' ? 'var(--accent-cyan)' : 'var(--accent-pink)';
                const velHTML = velocity > 0 
                    ? `<span style="font-size: 0.65rem; color: ${velColor}; margin-left: 0.5rem; font-family: 'Share Tech Mono', monospace; font-weight: bold;">${arrow} ${direction.toUpperCase()} (${(velocity * 10).toFixed(1)}/h)</span>`
                    : '';

                const reasonsHTML = conn.reasons 
                    ? `<div style="font-size: 0.65rem; color: var(--text-muted); margin-top: 0.25rem; font-family: 'Share Tech Mono', monospace; text-align: left;">░ Reasons: ${escapeHTML(conn.reasons)}</div>`
                    : '';

                return `
                    <div style="background: rgba(255, 255, 255, 0.02); border: 1px solid rgba(255, 255, 255, 0.05); padding: 0.4rem 0.6rem; font-size: 0.75rem; margin-bottom: 0.35rem;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.2rem;">
                            <span style="font-weight: bold; color: #fff; cursor: pointer; text-decoration: underline;" onclick="openStreamerProfileDrawer('${escapeHTML(conn.streamer)}')">${escapeHTML(conn.display_name || conn.streamer)}</span>
                            <div style="display: flex; align-items: center;">
                                <span style="font-size: 0.65rem; color: ${barColor}; font-weight: bold; text-transform: uppercase;">[ ${escapeHTML(conn.tag)} ]</span>
                                ${velHTML}
                            </div>
                        </div>
                        <div style="display: flex; align-items: center; gap: 0.5rem;">
                            <div style="flex: 1; height: 4px; background: rgba(255,255,255,0.08); border-radius: 2px; overflow: hidden;">
                                <div style="width: ${absScore}%; height: 100%; background: ${barColor};"></div>
                            </div>
                            <span style="font-size: 0.7rem; width: 30px; text-align: right; color: ${scorePct >= 0 ? 'var(--accent-cyan)' : 'var(--accent-pink)'};">${scorePct >= 0 ? '+' : ''}${scorePct}%</span>
                        </div>
                        ${reasonsHTML}
                    </div>
                `;
            };

            if (supportive.length > 0) {
                html += `
                    <div style="font-family: 'Share Tech Mono', monospace; font-size: 0.7rem; color: var(--accent-cyan); margin: 0.5rem 0 0.25rem 0; font-weight: bold;">▲ SUPPORTIVE PEERS</div>
                    ${supportive.map(renderCard).join('')}
                `;
            }
            if (opposing.length > 0) {
                html += `
                    <div style="font-family: 'Share Tech Mono', monospace; font-size: 0.7rem; color: var(--accent-pink); margin: 0.5rem 0 0.25rem 0; font-weight: bold;">▼ OPPOSING PEERS</div>
                    ${opposing.map(renderCard).join('')}
                `;
            }

            list.innerHTML = html;
        }

        // Global Escape key handler for arcade chat, profile drawer, and starmap chat
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                if (arcadeChatState !== 'closed') {
                    closeChat();
                }
                closeStreamerProfileDrawer();
                
                const smChatOut = document.getElementById("starmap-chat-output");
                if (smChatOut) smChatOut.style.display = "none";
            }
        });

        // ---------------------------------------------------------------------------
        // STAR MAP MODULE (Phase II Enhanced Analytics)
        // ---------------------------------------------------------------------------
        let starmapData = null;
        let currentTribeId = null;
        let warpActive = false;
        let pendingTribeId = null;
        let isNebulaActive = false;
        let activeNebulaMembers = null;
        let activeNebulaClusterId = null;
        let nebulaLoadingPromise = null;

        // 3D Star Map Perspective Engine Globals
        let starmapAngleX = 0.35;
        let starmapAngleY = 0.45;
        let starmapZoom = 1.0;
        let starmapPanX = 0;
        let starmapPanY = 0;
        let isDraggingStarmap = false;
        let lastDragMouseX = 0;
        let lastDragMouseY = 0;
        let activeDraggedNode = null;
        let nodeDragStartX = 0;
        let nodeDragStartY = 0;
        let isDraggingNodeActive = false;

        function project3D(x, y, z, width, height) {
            // 1. Rotate around Y axis (horizontal rotation)
            const cosY = Math.cos(starmapAngleY);
            const sinY = Math.sin(starmapAngleY);
            let x1 = x * cosY - z * sinY;
            let z1 = x * sinY + z * cosY;

            // 2. Rotate around X axis (vertical pitch)
            const cosX = Math.cos(starmapAngleX);
            const sinX = Math.sin(starmapAngleX);
            let y2 = y * cosX - z1 * sinX;
            let z2 = y * sinX + z1 * cosX;

            // 3. Perspective Projection calculations
            const fov = 600;
            const baseScale = 220;
            const cameraDistance = 2.2;
            const depthFactor = fov / (fov + (z2 + cameraDistance) * baseScale);
            
            const px = width / 2 + x1 * baseScale * depthFactor * starmapZoom + starmapPanX;
            const py = height / 2 + y2 * baseScale * depthFactor * starmapZoom + starmapPanY;

            // Normalize so that relativeScale is exactly 1.0 when z2 = 0 and starmapZoom = 1.0
            const defaultDepth = fov / (fov + cameraDistance * baseScale);
            const relativeScale = (depthFactor / defaultDepth) * starmapZoom;

            return {
                x: px,
                y: py,
                depth: z2,
                perspective: relativeScale
            };
        }

        function initStarmapEvents() {
            const svg = document.getElementById("starmap-svg");
            if (!svg || svg.dataset.eventsInitialized) return;
            svg.dataset.eventsInitialized = "true";

            svg.addEventListener("mousedown", (e) => {
                const nodeElement = e.target.closest("g[data-node-id], g[data-member-handle]");
                if (nodeElement) {
                    if (currentTribeId) {
                        const handle = nodeElement.getAttribute("data-member-handle");
                        const cluster = starmapData.clusters[currentTribeId];
                        if (cluster) {
                            activeDraggedNode = cluster.members.find(m => m.handle === handle);
                        }
                    } else {
                        const tribeId = nodeElement.getAttribute("data-node-id");
                        activeDraggedNode = starmapData.galaxy.tribes.find(t => t.id === tribeId);
                    }
                    lastDragMouseX = e.clientX;
                    lastDragMouseY = e.clientY;
                    nodeDragStartX = e.clientX;
                    nodeDragStartY = e.clientY;
                    isDraggingNodeActive = false;
                    e.stopPropagation();
                } else {
                    isDraggingStarmap = true;
                    lastDragMouseX = e.clientX;
                    lastDragMouseY = e.clientY;
                }
            });

            document.addEventListener("mousemove", (e) => {
                if (activeDraggedNode) {
                    const totalDist = Math.hypot(e.clientX - nodeDragStartX, e.clientY - nodeDragStartY);
                    if (!isDraggingNodeActive && totalDist > 5) {
                        isDraggingNodeActive = true;
                    }

                    if (isDraggingNodeActive) {
                        const dx = e.clientX - lastDragMouseX;
                        const dy = e.clientY - lastDragMouseY;
                        const sensitivity = 0.004 / starmapZoom;

                        const cosX = Math.cos(starmapAngleX);
                        const sinX = Math.sin(starmapAngleX);
                        const cosY = Math.cos(starmapAngleY);
                        const sinY = Math.sin(starmapAngleY);

                        activeDraggedNode.x += (dx * cosY - dy * sinY * sinX) * sensitivity;
                        activeDraggedNode.y += (dy * cosX) * sensitivity;
                        activeDraggedNode.z += (-dx * sinY - dy * cosY * sinX) * sensitivity;

                        lastDragMouseX = e.clientX;
                        lastDragMouseY = e.clientY;

                        if (isNebulaActive) {
                            renderNebulaView(currentTribeId);
                        } else if (currentTribeId) {
                            renderClusterView(currentTribeId);
                        } else {
                            renderGalaxyView();
                        }
                    }
                } else if (isDraggingStarmap) {
                    const dx = e.clientX - lastDragMouseX;
                    const dy = e.clientY - lastDragMouseY;

                    if (e.shiftKey) {
                        starmapPanX += dx;
                        starmapPanY += dy;
                    } else {
                        starmapAngleY += dx * 0.005;
                        starmapAngleX = Math.max(-Math.PI/2 + 0.1, Math.min(Math.PI/2 - 0.1, starmapAngleX + dy * 0.005));
                    }

                    lastDragMouseX = e.clientX;
                    lastDragMouseY = e.clientY;

                    if (isNebulaActive) {
                        renderNebulaView(currentTribeId);
                    } else if (currentTribeId) {
                        renderClusterView(currentTribeId);
                    } else {
                        renderGalaxyView();
                    }
                }
            });

            document.addEventListener("mouseup", () => {
                isDraggingStarmap = false;
                activeDraggedNode = null;
            });

            svg.addEventListener("wheel", (e) => {
                e.preventDefault();
                const delta = e.deltaY < 0 ? 1.1 : 0.9;
                starmapZoom = Math.max(0.3, Math.min(4.0, starmapZoom * delta));
                if (isNebulaActive) {
                    renderNebulaView(currentTribeId);
                } else if (currentTribeId) {
                    renderClusterView(currentTribeId);
                } else {
                    renderGalaxyView();
                }
            });

            // Mobile Touch Events Support (Rotate, Pinch-Zoom, Pan)
            let touchStartDist = 0;
            let isTouchDragging = false;
            let lastTouchX = 0;
            let lastTouchY = 0;

            svg.addEventListener("touchstart", (e) => {
                if (e.touches.length === 1) {
                    const nodeElement = e.touches[0].target.closest("g[data-node-id], g[data-member-handle]");
                    if (!nodeElement) {
                        isTouchDragging = true;
                        lastTouchX = e.touches[0].clientX;
                        lastTouchY = e.touches[0].clientY;
                    }
                } else if (e.touches.length === 2) {
                    isTouchDragging = false;
                    const t1 = e.touches[0];
                    const t2 = e.touches[1];
                    touchStartDist = Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY);
                    lastTouchX = (t1.clientX + t2.clientX) / 2;
                    lastTouchY = (t1.clientY + t2.clientY) / 2;
                }
            }, { passive: true });

            svg.addEventListener("touchmove", (e) => {
                if (isTouchDragging && e.touches.length === 1) {
                    const touch = e.touches[0];
                    const dx = touch.clientX - lastTouchX;
                    const dy = touch.clientY - lastTouchY;
                    
                    starmapAngleY += dx * 0.008;
                    starmapAngleX = Math.max(-Math.PI/2 + 0.1, Math.min(Math.PI/2 - 0.1, starmapAngleX + dy * 0.008));
                    
                    lastTouchX = touch.clientX;
                    lastTouchY = touch.clientY;
                    
                    if (isNebulaActive) {
                        renderNebulaView(currentTribeId);
                    } else if (currentTribeId) {
                        renderClusterView(currentTribeId);
                    } else {
                        renderGalaxyView();
                    }
                } else if (e.touches.length === 2) {
                    const t1 = e.touches[0];
                    const t2 = e.touches[1];
                    const dist = Math.hypot(t2.clientX - t1.clientX, t2.clientY - t1.clientY);
                    
                    // Zoom
                    if (touchStartDist > 0) {
                        const ratio = dist / touchStartDist;
                        starmapZoom = Math.max(0.3, Math.min(4.0, starmapZoom * ratio));
                        touchStartDist = dist;
                    }

                    // Pan
                    const midX = (t1.clientX + t2.clientX) / 2;
                    const midY = (t1.clientY + t2.clientY) / 2;
                    const dx = midX - lastTouchX;
                    const dy = midY - lastTouchY;
                    starmapPanX += dx;
                    starmapPanY += dy;
                    
                    lastTouchX = midX;
                    lastTouchY = midY;

                    if (isNebulaActive) {
                        renderNebulaView(currentTribeId);
                    } else if (currentTribeId) {
                        renderClusterView(currentTribeId);
                    } else {
                        renderGalaxyView();
                    }
                }
            }, { passive: true });

            svg.addEventListener("touchend", () => {
                isTouchDragging = false;
                touchStartDist = 0;
            }, { passive: true });
        }

        async function loadStarMap() {
            initWarpCanvas();
            initStarmapEvents();
            const svg = document.getElementById("starmap-svg");
            
            // If data is already cached, render it immediately to prevent black screen/loading flickers
            if (starmapData) {
                if (currentTribeId && starmapData.clusters && starmapData.clusters[currentTribeId]) {
                    renderClusterView(currentTribeId);
                } else {
                    zoomToGalaxy(true);
                }
            } else {
                svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="var(--accent-cyan)" font-family="'Share Tech Mono', monospace" font-size="1.2rem">CONNECTING TO WOR-ACLE STAR MAP... <tspan fill="#fff">█</tspan></text>`;
            }
            
            try {
                const response = await fetch("/api/starmap");
                if (!response.ok) throw new Error("Failed to load starmap API");
                starmapData = await response.json();
                
                if (starmapData.meta && starmapData.meta.status === "no_data") {
                    svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="var(--accent-pink)" font-family="'Share Tech Mono', monospace" font-size="1rem">NO ECOSYSTEM DATA GENERATED YET. INITIATE DAILY ANALYTICS CRON FIRST.</text>`;
                    return;
                }
                
                // Keep the active warp animation untouched
                if (!warpActive) {
                    if (pendingTribeId && starmapData.clusters && starmapData.clusters[pendingTribeId]) {
                        const target = pendingTribeId;
                        pendingTribeId = null;
                        zoomToCluster(target, null, null);
                    } else if (currentTribeId && starmapData.clusters && starmapData.clusters[currentTribeId]) {
                        renderClusterView(currentTribeId);
                    } else {
                        zoomToGalaxy(true);
                    }
                } else {
                    // Warp will call renderClusterView automatically once finished
                    pendingTribeId = null;
                }
            } catch (err) {
                console.error(err);
                if (!starmapData) {
                    svg.innerHTML = `<text x="50%" y="50%" text-anchor="middle" fill="red" font-family="'Share Tech Mono', monospace" font-size="1rem">STAR MAP ERROR: CONNECTION INTERRUPTED</text>`;
                }
            }
        }

        function initWarpCanvas() {
            const canvas = document.getElementById("starmap-warp-canvas");
            if (!canvas) return;
            canvas.width = canvas.parentElement.clientWidth;
            canvas.height = canvas.parentElement.clientHeight;
        }

        function runWarpAnimation(targetX, targetY, direction, callback) {
            const canvas = document.getElementById("starmap-warp-canvas");
            if (!canvas) return;
            const ctx = canvas.getContext("2d");
            const centerX = canvas.width / 2;
            const centerY = canvas.height / 2;
            
            warpActive = true;
            let frame = 0;
            const maxFrames = 20;
            
            const particles = [];
            const numParticles = 60;
            const originX = targetX || centerX;
            const originY = targetY || centerY;
            
            for (let i = 0; i < numParticles; i++) {
                const angle = Math.random() * Math.PI * 2;
                const speed = Math.random() * 8 + 4;
                particles.push({
                    x: originX,
                    y: originY,
                    vx: Math.cos(angle) * speed * (direction === "in" ? 1 : -0.5),
                    vy: Math.sin(angle) * speed * (direction === "in" ? 1 : -0.5),
                    color: direction === "in" ? "rgba(0, 240, 255, " : "rgba(236, 72, 153, "
                });
            }
            
            function animate() {
                if (!warpActive) return;
                
                ctx.fillStyle = "rgba(2, 2, 5, 0.25)";
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                
                frame++;
                
                particles.forEach(p => {
                    ctx.beginPath();
                    ctx.strokeStyle = p.color + (1 - frame/maxFrames) + ")";
                    ctx.lineWidth = 2;
                    ctx.moveTo(p.x, p.y);
                    const nextX = p.x + p.vx * (1 + frame * 0.15);
                    const nextY = p.y + p.vy * (1 + frame * 0.15);
                    ctx.lineTo(nextX, nextY);
                    ctx.stroke();
                    
                    p.x = nextX;
                    p.y = nextY;
                });
                
                if (frame < maxFrames) {
                    requestAnimationFrame(animate);
                } else {
                    warpActive = false;
                    ctx.clearRect(0, 0, canvas.width, canvas.height);
                    if (callback) callback();
                }
            }
            animate();
        }

        function zoomToGalaxy(skipAnimation = false) {
            currentTribeId = null;
            if (skipAnimation) {
                renderGalaxyView();
            } else {
                runWarpAnimation(null, null, "out", () => {
                    renderGalaxyView();
                });
            }
        }

        function zoomToCluster(clusterId, clickX, clickY) {
            currentTribeId = clusterId;
            runWarpAnimation(clickX, clickY, "in", () => {
                renderClusterView(clusterId);
            });
        }

        function renderGalaxyView() {
            isNebulaActive = false;
            activeNebulaMembers = null;
            activeNebulaClusterId = null;
            nebulaLoadingPromise = null;
            const svg = document.getElementById("starmap-svg");
            const width = svg.clientWidth || svg.parentElement.clientWidth || 800;
            const height = svg.clientHeight || svg.parentElement.clientHeight || 500;
            svg.innerHTML = "";
            
            let hud = document.getElementById("starmap-hud");
            if (!hud) {
                hud = document.createElement("div");
                hud.id = "starmap-hud";
                hud.style.position = "absolute";
                hud.style.bottom = "10px";
                hud.style.left = "10px";
                hud.style.right = "10px";
                hud.style.background = "rgba(2, 2, 5, 0.95)";
                hud.style.border = "1px solid var(--accent-cyan)";
                hud.style.padding = "0.5rem 0.75rem";
                hud.style.fontFamily = "'Share Tech Mono', monospace";
                hud.style.fontSize = "0.72rem";
                hud.style.color = "#fff";
                hud.style.pointerEvents = "none";
                hud.style.display = "none";
                hud.style.zIndex = "100";
                hud.style.boxShadow = "0 0 10px rgba(0, 240, 255, 0.15)";
                svg.parentElement.appendChild(hud);
            } else {
                hud.style.display = "none";
            }
            
            document.getElementById("starmap-back-btn").style.display = "none";
            document.getElementById("starmap-title").textContent = "⭐ STAR MAP: GALAXY VIEW";
            
            const sideHeader = document.getElementById("starmap-side-header");
            const sideInputBar = document.getElementById("starmap-input-bar");
            const sideOutput = document.getElementById("starmap-chat-output");
            if (sideHeader) sideHeader.textContent = "░ ECOSYSTEM OVERVIEW";
            if (sideInputBar) sideInputBar.style.display = "none";
            
            if (!starmapData) return;

            if (sideOutput) {
                sideOutput.style.display = "block";
                
                const allMembers = [];
                const activeAlerts = [];
                if (starmapData.clusters) {
                    Object.keys(starmapData.clusters).forEach(cId => {
                        const tribe = starmapData.clusters[cId];
                        tribe.members.forEach(m => {
                            allMembers.push({ handle: m.handle, display_name: m.display_name, score: m.bellwether_score, tribeColor: tribe.color, tribeName: tribe.label });
                        });
                        
                        tribe.intra_links.forEach(l => {
                            if (l.a === l.b) return; // skip self-pairs defensively
                            if (l.velocity > 0.03) {
                                const memA = tribe.members.find(m => m.handle === l.a);
                                const memB = tribe.members.find(m => m.handle === l.b);
                                const dispA = memA ? (memA.display_name || memA.handle) : l.a;
                                const dispB = memB ? (memB.display_name || memB.handle) : l.b;
                                activeAlerts.push({ 
                                    a: l.a, 
                                    b: l.b, 
                                    disp_a: dispA,
                                    disp_b: dispB,
                                    velocity: l.velocity, 
                                    acceleration: l.acceleration, 
                                    direction: l.direction, 
                                    color: tribe.color 
                                });
                            }
                        });
                    });
                }
                
                allMembers.sort((a,b) => b.score - a.score);
                activeAlerts.sort((a,b) => b.velocity - a.velocity);
                
                let bellwethersHTML = allMembers.map((m, idx) => `
                    <div style="display: flex; justify-content: space-between; font-size: 0.72rem; padding: 0.2rem 0; border-bottom: 1px solid rgba(255,255,255,0.03);">
                        <span style="color:#fff; cursor:pointer; text-decoration:underline; font-family:'Share Tech Mono';" onclick="openStreamerProfileDrawer('${escapeHTML(m.handle)}')">⚡ #${idx+1} @${escapeHTML(m.display_name || m.handle)}</span>
                        <span style="color:${m.tribeColor || 'var(--accent-cyan)'}; font-size: 0.65rem; font-family:'Share Tech Mono';">${escapeHTML(m.tribeName)}</span>
                    </div>
                `).join('');
                
                let alertsHTML = activeAlerts.slice(0, 3).map(a => {
                    let accelBadge = '';
                    if (a.acceleration !== undefined && a.acceleration !== null) {
                        if (a.acceleration > 0.05) {
                            accelBadge = `<span style="color:#22c55e; font-size:0.6rem; font-weight:bold; margin-left:0.3rem;">▲ ACCEL (+${(a.acceleration * 10).toFixed(2)}/h²)</span>`;
                        } else if (a.acceleration < -0.05) {
                            accelBadge = `<span style="color:#f97316; font-size:0.6rem; font-weight:bold; margin-left:0.3rem;">▼ DECEL (${(a.acceleration * 10).toFixed(2)}/h²)</span>`;
                        } else {
                            accelBadge = `<span style="color:var(--text-muted); font-size:0.6rem; margin-left:0.3rem;">■ STABLE (${(a.acceleration * 10).toFixed(2)}/h²)</span>`;
                        }
                    }
                    return `
                        <div style="font-size: 0.7rem; background: rgba(255,255,255,0.02); border-left: 2px solid ${a.color}; padding: 0.3rem 0.5rem; margin-bottom: 0.35rem;">
                            <div style="display:flex; justify-content:space-between; font-weight:bold; color:#fff; font-family:'Share Tech Mono';">
                                <span>@${escapeHTML(a.disp_a)} ⇄ @${escapeHTML(a.disp_b)}</span>
                                <span style="color:${a.direction === 'converging' ? 'var(--accent-cyan)' : 'var(--accent-pink)'};">${a.direction.toUpperCase()}</span>
                            </div>
                            <div style="color:var(--text-muted); font-size:0.65rem; font-family:'Share Tech Mono'; display:flex; align-items:center; justify-content:space-between; margin-top:0.15rem;">
                                <span>Velocity: ${(a.velocity * 10).toFixed(1)}/h</span>
                                ${accelBadge}
                            </div>
                        </div>
                    `;
                }).join('');
                
                if (!bellwethersHTML) bellwethersHTML = '<div style="color:var(--text-muted); text-align:center; font-family:\'Share Tech Mono\';">No bellwethers computed.</div>';
                if (!alertsHTML) alertsHTML = '<div style="color:var(--text-muted); text-align:center; font-family:\'Share Tech Mono\';">No active convergence alerts.</div>';

                sideOutput.innerHTML = `
                    <div style="font-size: 0.75rem; border: 1px solid rgba(0,240,255,0.15); padding: 0.5rem; background: rgba(0,240,255,0.02); margin-bottom: 1rem; line-height: 1.4;">
                        <span style="color: var(--accent-cyan); font-weight:bold;">WOR-ACLE GALAXY:</span> Detected <strong style="color:#fff;">${starmapData.galaxy.tribes.length} Vibe Tribes</strong> with dynamic connection vectors. Select a tribe to query synergy.
                        <div style="font-size: 0.62rem; color: var(--text-muted); border-top: 1px dashed rgba(0,240,255,0.1); margin-top: 0.4rem; padding-top: 0.4rem;">
                            * Galaxy coordinates are anchored by the 100 high-density Sentinel cohort nodes. Micro-streamers are dynamically projected within individual clusters.
                        </div>
                    </div>
                    
                    <div style="margin-bottom: 1rem;">
                        <div style="font-size: 0.7rem; color: var(--accent-yellow); font-weight:bold; margin-bottom: 0.4rem; letter-spacing:0.05em;">[ INFLUENCE LEADERBOARD ]</div>
                        <div style="max-height: 200px; overflow-y: auto; padding-right: 0.35rem;">
                            ${bellwethersHTML}
                        </div>
                    </div>
                    
                    <div>
                        <div style="font-size: 0.7rem; color: var(--accent-pink); font-weight:bold; margin-bottom: 0.4rem; letter-spacing:0.05em;">[ ACTIVE CONVERGENCE VECTORS ]</div>
                        ${alertsHTML}
                    </div>
                `;
            }
            
            const tribes = starmapData.galaxy.tribes;
            const links = starmapData.galaxy.inter_tribe_links || [];
            
            // Map tribes to screen coordinates using project3D
            const projectedTribes = tribes.map(t => {
                const proj = project3D(t.x, t.y, t.z || 0.0, width, height);
                return {
                    ...t,
                    px: proj.x,
                    py: proj.y,
                    depth: proj.depth,
                    perspective: proj.perspective
                };
            });

            // Sort tribes by depth desc (painter's algorithm)
            projectedTribes.sort((a, b) => b.depth - a.depth);

            // Draw links
            links.forEach(link => {
                const fromTribe = projectedTribes.find(t => t.id === String(link.from));
                const toTribe = projectedTribes.find(t => t.id === String(link.to));
                if (fromTribe && toTribe) {
                    const x1 = fromTribe.px;
                    const y1 = fromTribe.py;
                    const x2 = toTribe.px;
                    const y2 = toTribe.py;
                    
                    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
                    line.setAttribute("x1", x1);
                    line.setAttribute("y1", y1);
                    line.setAttribute("x2", x2);
                    line.setAttribute("y2", y2);
                    
                    // Vary opacity based on depth to show 3D separation
                    const avgDepth = (fromTribe.depth + toTribe.depth) / 2;
                    const opacity = Math.max(0.05, Math.min(0.4, 0.2 - avgDepth * 0.1));
                    line.setAttribute("stroke", `rgba(0, 240, 255, ${opacity})`);
                    line.setAttribute("stroke-width", Math.max(1.5, link.strength * 8 * ((fromTribe.perspective + toTribe.perspective) / 2)));
                    line.setAttribute("stroke-dasharray", "4,4");
                    svg.appendChild(line);
                }
            });
            
            // Draw tribe nodes
            projectedTribes.forEach(t => {
                const x = t.px;
                const y = t.py;
                const size = Math.max(10, Math.min(80, (14 + t.member_count * 1.5) * t.perspective));
                
                const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
                group.setAttribute("data-node-id", t.id);
                group.style.cursor = "grab";
                
                // Clicking a node (without dragging much) zooms to cluster
                let mousedownX = 0;
                let mousedownY = 0;
                group.onmousedown = (e) => {
                    mousedownX = e.clientX;
                    mousedownY = e.clientY;
                };
                group.onmouseup = (e) => {
                    const dist = Math.hypot(e.clientX - mousedownX, e.clientY - mousedownY);
                    if (dist < 5) {
                        const rect = svg.getBoundingClientRect();
                        const clickX = e.clientX - rect.left;
                        const clickY = e.clientY - rect.top;
                        zoomToCluster(t.id, clickX, clickY);
                    }
                };
                
                const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                circle.setAttribute("cx", x);
                circle.setAttribute("cy", y);
                circle.setAttribute("r", size);
                circle.setAttribute("fill", "transparent");
                circle.setAttribute("stroke", t.color);
                circle.setAttribute("stroke-width", "3");
                circle.style.filter = `drop-shadow(0 0 8px ${t.color})`;
                circle.setAttribute("stroke-opacity", Math.max(0.2, Math.min(1.0, t.perspective)));
                
                const inner = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                inner.setAttribute("cx", x);
                inner.setAttribute("cy", y);
                inner.setAttribute("r", Math.max(2, size - 4));
                inner.setAttribute("fill", t.color);
                inner.setAttribute("fill-opacity", Math.max(0.05, 0.2 * t.perspective));
                
                // Clamp label text coordinates to borders to prevent leakage
                const clampedLabelX = Math.max(80, Math.min(width - 80, x));
                const clampedLabelY = Math.max(30, Math.min(height - 40, y + size + 15));

                const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
                text.setAttribute("x", clampedLabelX);
                text.setAttribute("y", clampedLabelY);
                text.setAttribute("text-anchor", "middle");
                text.setAttribute("fill", "#fff");
                text.setAttribute("font-family", "'Share Tech Mono', monospace");
                text.setAttribute("font-size", `${Math.max(0.72, Math.min(1.6, 0.88 * t.perspective))}rem`);
                text.setAttribute("fill-opacity", Math.max(0.3, Math.min(1.0, t.perspective)));
                text.textContent = `${t.label} (×${t.member_count})`;
                
                const sub = document.createElementNS("http://www.w3.org/2000/svg", "text");
                sub.setAttribute("x", clampedLabelX);
                sub.setAttribute("y", clampedLabelY + 13);
                sub.setAttribute("text-anchor", "middle");
                sub.setAttribute("fill", "var(--text-muted)");
                sub.setAttribute("font-family", "'Share Tech Mono', monospace");
                sub.setAttribute("font-size", `${Math.max(0.6, Math.min(1.2, 0.68 * t.perspective))}rem`);
                sub.setAttribute("fill-opacity", Math.max(0.3, Math.min(1.0, t.perspective)));
                sub.textContent = `HUB: @${t.top_bellwether}`;
                
                group.appendChild(circle);
                group.appendChild(inner);
                group.appendChild(text);
                group.appendChild(sub);

                group.addEventListener("mouseenter", () => {
                    if (hud) {
                        hud.innerHTML = `<span style="color:${t.color}; font-weight:bold;">VIBE TRIBE:</span> <strong style="color:#fff;">${escapeHTML(t.label)}</strong> | ` +
                                        `Members: <strong style="color:#fff;">${t.member_count}</strong> | ` +
                                        `Hub: <strong style="color:#fff;">@${escapeHTML(t.top_bellwether)}</strong><br/>` +
                                        `<span style="color:var(--text-muted); font-size:0.65rem;">Vibe Profile:</span> <span style="font-style:italic;">"${escapeHTML(t.description || 'A dynamic faction of streamers bound by similar chat rhythms and viewer flows.')}"</span>`;
                        hud.style.display = "block";
                    }
                });
                
                group.addEventListener("mouseleave", () => {
                    if (hud) hud.style.display = "none";
                });

                group.addEventListener("touchstart", (e) => {
                    e.stopPropagation();
                    if (hud) {
                        hud.innerHTML = `<span style="color:${t.color}; font-weight:bold;">VIBE TRIBE:</span> <strong style="color:#fff;">${escapeHTML(t.label)}</strong> | ` +
                                        `Members: <strong style="color:#fff;">${t.member_count}</strong> | ` +
                                        `Hub: <strong style="color:#fff;">@${escapeHTML(t.top_bellwether)}</strong><br/>` +
                                        `<span style="color:var(--text-muted); font-size:0.65rem;">Vibe Profile:</span> <span style="font-style:italic;">"${escapeHTML(t.description || 'A dynamic faction of streamers bound by similar chat rhythms and viewer flows.')}"</span>`;
                        hud.style.display = "block";
                    }
                }, { passive: true });

                svg.appendChild(group);
            });
        }

        function renderClusterView(clusterId) {
            isNebulaActive = false;
            activeNebulaMembers = null;
            activeNebulaClusterId = null;
            nebulaLoadingPromise = null;
            const svg = document.getElementById("starmap-svg");
            const width = svg.clientWidth || svg.parentElement.clientWidth || 800;
            const height = svg.clientHeight || svg.parentElement.clientHeight || 500;
            svg.innerHTML = "";
            
            let hud = document.getElementById("starmap-hud");
            if (!hud) {
                hud = document.createElement("div");
                hud.id = "starmap-hud";
                hud.style.position = "absolute";
                hud.style.bottom = "10px";
                hud.style.left = "10px";
                hud.style.right = "10px";
                hud.style.background = "rgba(2, 2, 5, 0.95)";
                hud.style.border = "1px solid var(--accent-cyan)";
                hud.style.padding = "0.5rem 0.75rem";
                hud.style.fontFamily = "'Share Tech Mono', monospace";
                hud.style.fontSize = "0.72rem";
                hud.style.color = "#fff";
                hud.style.pointerEvents = "none";
                hud.style.display = "none";
                hud.style.zIndex = "100";
                hud.style.boxShadow = "0 0 10px rgba(0, 240, 255, 0.15)";
                svg.parentElement.appendChild(hud);
            } else {
                hud.style.display = "none";
            }
            
            svg.onclick = (e) => {
                if (e.target === svg) {
                    if (hud) hud.style.display = "none";
                    const allLines = svg.querySelectorAll("line");
                    allLines.forEach(l => {
                        const origOpacity = l.getAttribute("data-original-opacity");
                        const origWidth = l.getAttribute("data-original-width");
                        l.setAttribute("stroke-opacity", origOpacity || "0.2");
                        l.setAttribute("stroke-width", origWidth || "1.5");
                        l.style.filter = "none";
                    });
                }
            };
            
            const backBtn = document.getElementById("starmap-back-btn");
            if (backBtn) {
                backBtn.style.display = "inline-block";
                backBtn.onclick = () => zoomToGalaxy();
                backBtn.textContent = "← BACK TO GALAXY";
            }
            
            if (!starmapData) return;
            
            const cluster = starmapData.clusters[clusterId];
            if (!cluster) return;
            
            document.getElementById("starmap-title").textContent = `⭐ STAR MAP: ${cluster.label.toUpperCase()}`;
            
            const sideHeader = document.getElementById("starmap-side-header");
            const sideInputBar = document.getElementById("starmap-input-bar");
            const sideOutput = document.getElementById("starmap-chat-output");
            
            const expectedHeader = `░ QUERY TRIBE: ${cluster.label.toUpperCase()}`;
            if (sideHeader) {
                sideHeader.textContent = expectedHeader;
                sideHeader.style.color = cluster.color;
                sideHeader.style.borderBottomColor = cluster.color + "40";
            }
            if (sideInputBar) {
                sideInputBar.style.display = "flex";
                sideInputBar.style.borderTopColor = cluster.color;
                const querySpan = sideInputBar.querySelector("span");
                if (querySpan) querySpan.style.color = cluster.color;
            }
            if (sideOutput) {
                if (sideHeader && sideHeader.getAttribute("data-loaded-cluster") !== clusterId) {
                    sideHeader.setAttribute("data-loaded-cluster", clusterId);
                    sideOutput.style.display = "block";
                    sideOutput.innerHTML = `
                        <div style="font-size: 0.75rem; border: 1px solid ${cluster.color}; padding: 0.5rem; background: ${cluster.color}0a; color: #cbd5e1; font-family:'Share Tech Mono';">
                            Welcome to the <strong style="color:${cluster.color};">${escapeHTML(cluster.label)}</strong> console.
                            <div style="margin-top:0.35rem; font-size:0.7rem;">
                                <strong>Members:</strong> ${cluster.members.map(m => `@${escapeHTML(m.display_name || m.handle)}`).join(', ')}
                            </div>
                            ${cluster.description ? `
                            <div style="margin-top:0.5rem; border-top: 1px dashed rgba(255,255,255,0.1); padding-top: 0.4rem; font-size:0.7rem; line-height: 1.3; font-style: italic; color: #94a3b8;">
                                "${escapeHTML(cluster.description)}"
                            </div>` : ''}
                            
                            <div style="margin-top:0.75rem; border-top: 1px dashed rgba(255,255,255,0.15); padding-top: 0.5rem;">
                                <button class="btn" style="width:100%; font-size:0.7rem; padding:0.25rem 0.5rem; border:1px solid ${cluster.color}; background: ${cluster.color}15; color: ${cluster.color}; cursor:pointer; font-family:'Share Tech Mono'; font-weight:bold;" onclick="runTribeForecast('${clusterId}')">RUN TRIBE PREDICTIVE ENGINE</button>
                                <div id="tribe-forecast-container" style="display:none; margin-top:0.5rem; border: 1px solid rgba(255,255,255,0.05); padding: 0.5rem; background: rgba(0,0,0,0.3);">
                                    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px dashed rgba(255,255,255,0.15); padding-bottom:0.25rem; margin-bottom:0.4rem;">
                                        <span style="font-size:0.6rem; font-weight:bold; color:${cluster.color}; font-family:'Press Start 2P';">[ TRIBE FORECAST ]</span>
                                        <select id="tribe-forecast-metric-selector" style="background:#000; border:1px solid rgba(255,255,255,0.2); color:#fff; font-family:'Share Tech Mono'; font-size:0.65rem; padding:0.05rem;" onchange="updateTribeForecastChart()">
                                            <option value="viewer_count">VIEWERS</option>
                                            <option value="msg_per_minute">CHAT SPEED</option>
                                            <option value="rolling_sentiment_score">VIBE SENTIMENT</option>
                                        </select>
                                    </div>
                                    <div id="tribe-forecast-svg-wrapper" style="text-align:center;"></div>
                                    <div id="tribe-forecast-stats" style="margin-top:0.4rem; display:flex; flex-wrap:wrap; justify-content:space-between; font-size:0.6rem; color:#94a3b8;"></div>
                                </div>
                            </div>
                        </div>
                        <div style="color: var(--text-muted); text-align: center; margin-top: 2rem; font-size: 0.8rem; font-family:'Share Tech Mono';">
                            ░ Ask anything about this cluster's synergy or raid flows below.
                        </div>
                    `;
                }
                document.getElementById("starmap-chat-input").value = "";
            }
            
            const members = cluster.members;
            const links = cluster.intra_links || [];

            const bellwetherMembers = members.filter(m => !m.custom_injected);
            const microStreamers = members.filter(m => m.custom_injected);
            
            // Map members to screen coordinates using project3D
            const nodes = bellwetherMembers.map(m => {
                const proj = project3D(m.x, m.y, m.z || 0.0, width, height);
                const alignment = m.tribe_alignment !== undefined ? m.tribe_alignment : 1.0;
                const size = Math.max(7, Math.min(24, (5 + (m.bellwether_score || 0.0) * 12 + alignment * 7) * proj.perspective));
                return {
                    handle: m.handle,
                    x: proj.x,
                    y: proj.y,
                    depth: proj.depth,
                    perspective: proj.perspective,
                    size: size,
                    bellwether_score: m.bellwether_score,
                    tribe_alignment: alignment,
                    raw: m
                };
            });

            // Sort nodes by depth desc (painter's algorithm)
            nodes.sort((a, b) => b.depth - a.depth);

            // Draw links using projected node coordinates
            let effectiveLinks = [...links];
            if (effectiveLinks.length === 0 && nodes.length > 1) {
                const linksDrawn = new Set();
                nodes.forEach(nodeA => {
                    const targets = nodes
                        .filter(nodeB => nodeB.handle !== nodeA.handle)
                        .map(nodeB => {
                            const dist = Math.hypot(
                                nodeA.raw.x - nodeB.raw.x,
                                nodeA.raw.y - nodeB.raw.y,
                                (nodeA.raw.z || 0.0) - (nodeB.raw.z || 0.0)
                            );
                            return { node: nodeB, dist: dist };
                        });
                    targets.sort((a, b) => a.dist - b.dist);
                    const maxLinkDist = 1.35;
                    targets.slice(0, 2).forEach(t => {
                        if (t.dist < maxLinkDist) {
                            const linkKey = [nodeA.handle, t.node.handle].sort().join("-");
                            if (!linksDrawn.has(linkKey)) {
                                linksDrawn.add(linkKey);
                                effectiveLinks.push({
                                    a: nodeA.handle,
                                    b: t.node.handle,
                                    velocity: 0.15,
                                    acceleration: 0.0,
                                    direction: "converging"
                                });
                            }
                        }
                    });
                });
            }

            effectiveLinks.forEach(link => {
                const fromNode = nodes.find(n => n.handle === link.a);
                const toNode = nodes.find(n => n.handle === link.b);
                if (fromNode && toNode) {
                    const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
                    line.setAttribute("x1", fromNode.x);
                    line.setAttribute("y1", fromNode.y);
                    line.setAttribute("x2", toNode.x);
                    line.setAttribute("y2", toNode.y);
                    
                    const strokeColor = link.direction === "converging" ? "var(--accent-cyan)" : "var(--accent-pink)";
                    line.setAttribute("stroke", strokeColor);
                    
                    const avgDepth = (fromNode.depth + toNode.depth) / 2;
                    // Boost baseline opacity
                    const opacity = (Math.max(0.35, Math.min(0.95, 0.8 - avgDepth * 0.15)) * 0.7).toFixed(3);
                    line.setAttribute("stroke-opacity", opacity);
                    line.setAttribute("data-original-opacity", opacity);
                    line.setAttribute("data-from", link.a);
                    line.setAttribute("data-to", link.b);
                    
                    // Add constellation-link class and configure CSS variables for pulsing
                    line.classList.add("constellation-link");
                    const pulseDur = Math.max(1.0, Math.min(6.0, 4.0 - link.velocity * 12.0));
                    line.style.setProperty("--pulse-dur", `${pulseDur.toFixed(2)}s`);
                    const maxOpacity = Math.max(0.65, Math.min(0.95, 0.85 - avgDepth * 0.1));
                    const minOpacity = Math.max(0.25, maxOpacity * 0.45);
                    line.style.setProperty("--max-opacity", maxOpacity.toFixed(3));
                    line.style.setProperty("--min-opacity", minOpacity.toFixed(3));
                    
                    const strokeWidth = Math.max(1.5, link.velocity * 15 * ((fromNode.perspective + toNode.perspective) / 2));
                    line.setAttribute("stroke-width", strokeWidth);
                    line.setAttribute("data-original-width", strokeWidth);
                    
                    // Add hover tooltip to the connection line
                    const lineTitle = document.createElementNS("http://www.w3.org/2000/svg", "title");
                    lineTitle.textContent = `@${link.a} ⇄ @${link.b}\nDirection: ${link.direction.toUpperCase()}\nVelocity: ${(link.velocity * 10).toFixed(2)}/h\nAcceleration: ${(link.acceleration * 10).toFixed(2)}/h²`;
                    line.appendChild(lineTitle);
                    
                    const showLinkHud = () => {
                        if (hud) {
                            hud.innerHTML = `<span style="color:var(--accent-cyan); font-weight:bold;">CONNECTION METRICS:</span> @${escapeHTML(link.a)} ⇄ @${escapeHTML(link.b)} | <span style="color:${link.direction === 'converging' ? 'var(--accent-cyan)' : 'var(--accent-pink)'}; font-weight:bold;">${link.direction.toUpperCase()}</span><br/>` +
                                            `Velocity: <strong style="color:#fff;">${(link.velocity * 10).toFixed(2)}/h</strong> | ` +
                                            `Acceleration: <strong style="color:#fff;">${(link.acceleration * 10).toFixed(2)}/h²</strong>`;
                            hud.style.display = "block";
                        }
                    };
                    
                    const highlightLink = () => {
                        const allLines = svg.querySelectorAll("line");
                        allLines.forEach(l => {
                            if (l === line) {
                                l.setAttribute("stroke-opacity", "0.95");
                                l.setAttribute("stroke-width", strokeWidth * 1.5);
                                l.style.filter = "drop-shadow(0 0 3px var(--accent-cyan))";
                            } else {
                                l.setAttribute("stroke-opacity", "0.03");
                            }
                        });
                    };

                    // Interactive link hover/touch highlighting
                    line.addEventListener("mouseenter", () => {
                        highlightLink();
                        showLinkHud();
                    });
                    line.addEventListener("mouseleave", () => {
                        if (hud) hud.style.display = "none";
                        const allLines = svg.querySelectorAll("line");
                        allLines.forEach(l => {
                            const origOpacity = l.getAttribute("data-original-opacity");
                            const origWidth = l.getAttribute("data-original-width");
                            l.setAttribute("stroke-opacity", origOpacity || "0.2");
                            l.setAttribute("stroke-width", origWidth || "1.5");
                            l.style.filter = "none";
                        });
                    });
                    line.addEventListener("click", (e) => {
                        e.stopPropagation();
                        highlightLink();
                        showLinkHud();
                    });
                    
                    // Visual flow animation representing velocity and direction
                    if (link.velocity > 0.03) {
                        line.setAttribute("stroke-dasharray", "4,4");
                        const animate = document.createElementNS("http://www.w3.org/2000/svg", "animate");
                        animate.setAttribute("attributeName", "stroke-dashoffset");
                        const directionMultiplier = link.direction === "converging" ? 1 : -1;
                        animate.setAttribute("values", directionMultiplier === 1 ? "16;0" : "0;16");
                        const dur = Math.max(0.4, 3.5 - link.velocity * 18);
                        animate.setAttribute("dur", `${dur.toFixed(2)}s`);
                        animate.setAttribute("repeatCount", "indefinite");
                        line.appendChild(animate);
                    }
                    
                    svg.appendChild(line);
                }
            });
            
            // Build a list of rendered label coordinates to avoid overlaps
            const renderedLabels = [];

            nodes.forEach(n => {
                const x = n.x;
                const y = n.y;
                const size = n.size;
                const m = n.raw;
                
                const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
                group.setAttribute("data-member-handle", m.handle);
                group.style.cursor = "grab";
                
                // Interactive node hover focal highlighting
                const highlightNode = () => {
                    const allLines = svg.querySelectorAll("line");
                    allLines.forEach(l => {
                        const from = l.getAttribute("data-from");
                        const to = l.getAttribute("data-to");
                        if (from === m.handle || to === m.handle) {
                            l.setAttribute("stroke-opacity", "0.95");
                            l.style.filter = "drop-shadow(0 0 3px var(--accent-cyan))";
                            const origWidth = parseFloat(l.getAttribute("data-original-width") || "1.5");
                            l.setAttribute("stroke-width", origWidth * 1.5);
                        } else {
                            l.setAttribute("stroke-opacity", "0.03");
                        }
                    });
                };
                
                const showNodeHud = () => {
                    if (hud) {
                        let vectorsList = "";
                        if (cluster.intra_links) {
                            const activeLinks = cluster.intra_links.filter(l => l.a === m.handle || l.b === m.handle);
                            if (activeLinks.length > 0) {
                                vectorsList = "<br/><span style=\"color:var(--text-muted); font-size:0.65rem;\">Active Convergence:</span> " + 
                                    activeLinks.map(l => {
                                        const peerHandle = l.a === m.handle ? l.b : l.a;
                                        const peerMember = cluster.members.find(mem => mem.handle === peerHandle);
                                        const peerName = peerMember ? (peerMember.display_name || peerMember.handle) : peerHandle;
                                        return `@${escapeHTML(peerName)} (${l.direction === 'converging' ? '▲' : '▼'} ${(l.velocity * 10).toFixed(1)}/h)`;
                                    }).join(", ");
                            }
                        }
                        const alignment = m.tribe_alignment !== undefined ? m.tribe_alignment : 1.0;
                        const isIsland = alignment < 0.25;
                        const alignmentPercent = (alignment * 100).toFixed(1);
                        const alignmentStatus = isIsland ? "Island Outlier 🏝️" : "Tribe Core";
                        hud.innerHTML = `<span style="color:var(--accent-yellow); font-weight:bold;">STREAMER PROFILE:</span> @${escapeHTML(m.display_name || m.handle)} | ` +
                                        `Bellwether: <strong style="color:#fff;">${m.bellwether_score.toFixed(4)}</strong> | ` +
                                        `Tribe Alignment: <strong style="color:${isIsland ? 'var(--accent-pink)' : 'var(--accent-cyan)'};">${alignmentPercent}% (${alignmentStatus})</strong>` + vectorsList;
                        hud.style.display = "block";
                    }
                };

                group.addEventListener("mouseenter", () => {
                    highlightNode();
                    showNodeHud();
                });
                group.addEventListener("mouseleave", () => {
                    if (hud) hud.style.display = "none";
                    const allLines = svg.querySelectorAll("line");
                    allLines.forEach(l => {
                        const origOpacity = l.getAttribute("data-original-opacity");
                        const origWidth = l.getAttribute("data-original-width");
                        l.setAttribute("stroke-opacity", origOpacity || "0.2");
                        l.setAttribute("stroke-width", origWidth || "1.5");
                        l.style.filter = "none";
                    });
                });
                group.addEventListener("touchstart", (e) => {
                    e.stopPropagation();
                    highlightNode();
                    showNodeHud();
                });
                
                // Clicking opens drawer
                let mousedownX = 0;
                let mousedownY = 0;
                group.onmousedown = (e) => {
                    mousedownX = e.clientX;
                    mousedownY = e.clientY;
                };
                group.onmouseup = (e) => {
                    const dist = Math.hypot(e.clientX - mousedownX, e.clientY - mousedownY);
                    if (dist < 5) {
                        openStreamerProfileDrawer(m.handle);
                    }
                };
                
                const alignment = m.tribe_alignment !== undefined ? m.tribe_alignment : 1.0;
                const isIsland = alignment < 0.25;
                const circle = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                circle.setAttribute("cx", x);
                circle.setAttribute("cy", y);
                circle.setAttribute("r", size);
                circle.setAttribute("fill", cluster.color);
                circle.setAttribute("stroke", isIsland ? "#94a3b8" : "#fff");
                circle.setAttribute("stroke-width", isIsland ? "0.75" : "1.5");
                if (isIsland) {
                    circle.style.filter = "none";
                } else {
                    const glowRadius = Math.max(2, Math.min(10, 3 + alignment * 8));
                    circle.style.filter = `drop-shadow(0 0 ${glowRadius}px ${cluster.color})`;
                }
                const baseOpacity = isIsland ? 0.35 : Math.max(0.3, Math.min(1.0, n.perspective));
                circle.setAttribute("fill-opacity", baseOpacity);
                circle.setAttribute("stroke-opacity", baseOpacity);
                
                if (m.bellwether_score > 0.7) {
                    const pulseRing = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                    pulseRing.setAttribute("cx", x);
                    pulseRing.setAttribute("cy", y);
                    pulseRing.setAttribute("r", size + 4);
                    pulseRing.setAttribute("fill", "none");
                    pulseRing.setAttribute("stroke", cluster.color);
                    pulseRing.setAttribute("stroke-opacity", Math.max(0.1, 0.4 * n.perspective));
                    pulseRing.setAttribute("stroke-width", "1");
                    
                    const animate = document.createElementNS("http://www.w3.org/2000/svg", "animate");
                    animate.setAttribute("attributeName", "r");
                    animate.setAttribute("values", `${size + 1};${size + 8}`);
                    animate.setAttribute("dur", "2s");
                    animate.setAttribute("repeatCount", "indefinite");
                    
                    const animateOpacity = document.createElementNS("http://www.w3.org/2000/svg", "animate");
                    animateOpacity.setAttribute("attributeName", "stroke-opacity");
                    animateOpacity.setAttribute("values", "0.6;0");
                    animateOpacity.setAttribute("dur", "2s");
                    animateOpacity.setAttribute("repeatCount", "indefinite");
                    
                    pulseRing.appendChild(animate);
                    pulseRing.appendChild(animateOpacity);
                    group.appendChild(pulseRing);
                }
                
                // Label Collision Resolution Heuristic with clamping to borders
                let labelY = y + size + 12;
                let labelX = x;
                let collisionDetected = true;
                let attempts = 0;
                while (collisionDetected && attempts < 4) {
                    collisionDetected = false;
                    for (const rl of renderedLabels) {
                        const dx = Math.abs(rl.x - labelX);
                        const dy = Math.abs(rl.y - labelY);
                        if (dx < 55 && dy < 14) {
                            collisionDetected = true;
                            if (attempts === 0) {
                                labelY = y - size - 8;
                            } else if (attempts === 1) {
                                labelX = x - 25;
                                labelY = y + size + 12;
                            } else if (attempts === 2) {
                                labelX = x + 25;
                                labelY = y + size + 12;
                            } else {
                                labelY = y + size + 24;
                            }
                            break;
                        }
                    }
                    attempts++;
                }

                // Clamp label text coordinates to borders
                labelX = Math.max(60, Math.min(width - 60, labelX));
                labelY = Math.max(30, Math.min(height - 30, labelY));

                renderedLabels.push({ x: labelX, y: labelY });

                const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
                text.setAttribute("x", labelX);
                text.setAttribute("y", labelY);
                text.setAttribute("text-anchor", "middle");
                text.setAttribute("fill", "#fff");
                text.setAttribute("font-family", "'Share Tech Mono', monospace");
                text.setAttribute("font-size", `${Math.max(0.7, Math.min(1.5, 0.78 * n.perspective))}rem`);
                text.setAttribute("font-weight", "600");
                text.setAttribute("fill-opacity", Math.max(0.4, Math.min(1.0, n.perspective)));
                text.innerHTML = `<tspan fill="var(--accent-cyan)">@</tspan>${escapeHTML(m.display_name || m.handle)}`;
                
                // Compile active convergence vectors involving this streamer
                let connectionStats = "";
                if (cluster.intra_links) {
                    const activeLinks = cluster.intra_links.filter(l => l.a === m.handle || l.b === m.handle);
                    if (activeLinks.length > 0) {
                        connectionStats = "\n\nActive Convergence Vectors:\n" + 
                            activeLinks.map(l => {
                                const peerHandle = l.a === m.handle ? l.b : l.a;
                                const peerMember = cluster.members.find(mem => mem.handle === peerHandle);
                                const peerName = peerMember ? (peerMember.display_name || peerMember.handle) : peerHandle;
                                const arrow = l.direction === "converging" ? "▲" : "▼";
                                return `  ⇄ @${peerName} (${l.direction.toUpperCase()} ${arrow} | Vel: ${(l.velocity * 10).toFixed(1)}/h | Accel: ${(l.acceleration * 10).toFixed(2)}/h²)`;
                            }).join("\n");
                    }
                }

                const title = document.createElementNS("http://www.w3.org/2000/svg", "title");
                title.textContent = `${m.display_name || m.handle}\nBellwether Score: ${m.bellwether_score.toFixed(4)}${connectionStats}`;
                group.appendChild(title);
                
                group.appendChild(circle);
                group.appendChild(text);
                svg.appendChild(group);
            });

            if (microStreamers.length > 0) {
                const nx = 0.55;
                const ny = -0.55;
                const nz = 0.15;
                const nProj = project3D(nx, ny, nz, width, height);
                const nSize = Math.max(24, Math.min(50, 18 + Math.log(microStreamers.length) * 7.0));
                
                const nGroup = document.createElementNS("http://www.w3.org/2000/svg", "g");
                nGroup.style.cursor = "pointer";
                
                nGroup.addEventListener("mouseenter", () => {
                    if (hud) {
                        hud.innerHTML = `<span style="color:var(--accent-pink); font-weight:bold;">MICRO-STREAMER NEBULA:</span> Contains <strong style="color:#fff;">${microStreamers.length}</strong> dynamic micro-streamers aligned with this tribe's vibe.<br/><span style="color:var(--text-muted); font-size:0.65rem;">Click to zoom into the Nebula Constellation point-cloud.</span>`;
                        hud.style.display = "block";
                    }
                });
                nGroup.addEventListener("mouseleave", () => {
                    if (hud) hud.style.display = "none";
                });
                
                let mousedownX = 0;
                let mousedownY = 0;
                nGroup.onmousedown = (e) => {
                    mousedownX = e.clientX;
                    mousedownY = e.clientY;
                };
                nGroup.onmouseup = (e) => {
                    const dist = Math.hypot(e.clientX - mousedownX, e.clientY - mousedownY);
                    if (dist < 5) {
                        runWarpAnimation(nProj.x, nProj.y, "in", () => {
                            renderNebulaView(clusterId);
                        });
                    }
                };
                
                const nOuter = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                nOuter.setAttribute("cx", nProj.x);
                nOuter.setAttribute("cy", nProj.y);
                nOuter.setAttribute("r", nSize + 6);
                nOuter.setAttribute("fill", "none");
                nOuter.setAttribute("stroke", "var(--accent-pink)");
                nOuter.setAttribute("stroke-width", "2");
                nOuter.setAttribute("stroke-dasharray", "4,4");
                nOuter.setAttribute("stroke-opacity", "0.8");
                nOuter.style.filter = "drop-shadow(0 0 8px var(--accent-pink))";
                
                const nAnimate = document.createElementNS("http://www.w3.org/2000/svg", "animate");
                nAnimate.setAttribute("attributeName", "stroke-dashoffset");
                nAnimate.setAttribute("values", "0;20");
                nAnimate.setAttribute("dur", "4s");
                nAnimate.setAttribute("repeatCount", "indefinite");
                nOuter.appendChild(nAnimate);
                
                const nInner = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                nInner.setAttribute("cx", nProj.x);
                nInner.setAttribute("cy", nProj.y);
                nInner.setAttribute("r", nSize);
                nInner.setAttribute("fill", "url(#nebula-gradient)");
                nInner.setAttribute("fill-opacity", "0.25");
                nInner.setAttribute("stroke", "#fff");
                nInner.setAttribute("stroke-width", "1.5");
                nInner.style.filter = "drop-shadow(0 0 12px var(--accent-pink))";
                
                let defs = svg.querySelector("defs");
                if (!defs) {
                    defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
                    svg.appendChild(defs);
                }
                if (!document.getElementById("nebula-gradient")) {
                    const radialGrad = document.createElementNS("http://www.w3.org/2000/svg", "radialGradient");
                    radialGrad.setAttribute("id", "nebula-gradient");
                    radialGrad.innerHTML = `
                        <stop offset="0%" stop-color="var(--accent-pink)" stop-opacity="1"/>
                        <stop offset="70%" stop-color="#a855f7" stop-opacity="0.5"/>
                        <stop offset="100%" stop-color="transparent" stop-opacity="0"/>
                    `;
                    defs.appendChild(radialGrad);
                }
                
                const nText = document.createElementNS("http://www.w3.org/2000/svg", "text");
                nText.setAttribute("x", nProj.x);
                nText.setAttribute("y", nProj.y + nSize + 15);
                nText.setAttribute("text-anchor", "middle");
                nText.setAttribute("fill", "#fff");
                nText.setAttribute("font-family", "'Share Tech Mono', monospace");
                nText.setAttribute("font-size", "0.75rem");
                nText.setAttribute("font-weight", "bold");
                nText.style.filter = "drop-shadow(0 0 3px #000)";
                nText.innerHTML = `<tspan fill="var(--accent-pink)">✨</tspan> NEBULA (×${microStreamers.length})`;
                
                nGroup.appendChild(nOuter);
                nGroup.appendChild(nInner);
                nGroup.appendChild(nText);
                svg.appendChild(nGroup);
            }
        }

        async function renderNebulaView(clusterId) {
            isNebulaActive = true;
            const svg = document.getElementById("starmap-svg");
            const width = svg.clientWidth || svg.parentElement.clientWidth || 800;
            const height = svg.clientHeight || svg.parentElement.clientHeight || 500;
            svg.innerHTML = "";
            
            let hud = document.getElementById("starmap-hud");
            if (!hud) {
                hud = document.createElement("div");
                hud.id = "starmap-hud";
                hud.style.position = "absolute";
                hud.style.bottom = "10px";
                hud.style.left = "10px";
                hud.style.right = "10px";
                hud.style.background = "rgba(2, 2, 5, 0.95)";
                hud.style.border = "1px solid var(--accent-cyan)";
                hud.style.padding = "0.5rem 0.75rem";
                hud.style.fontFamily = "'Share Tech Mono', monospace";
                hud.style.fontSize = "0.72rem";
                hud.style.color = "#fff";
                hud.style.pointerEvents = "none";
                hud.style.display = "none";
                hud.style.zIndex = "100";
                hud.style.boxShadow = "0 0 10px rgba(0, 240, 255, 0.15)";
                svg.parentElement.appendChild(hud);
            } else {
                hud.style.display = "none";
            }
            
            const cluster = starmapData.clusters[clusterId];
            if (!cluster) return;
            
            document.getElementById("starmap-title").textContent = `✨ STAR MAP: ${cluster.label.toUpperCase()} NEBULA`;
            
            const backBtn = document.getElementById("starmap-back-btn");
            if (backBtn) {
                backBtn.style.display = "inline-block";
                backBtn.onclick = () => {
                    activeNebulaMembers = null;
                    activeNebulaClusterId = null;
                    nebulaLoadingPromise = null;
                    runWarpAnimation(null, null, "out", () => {
                        renderClusterView(clusterId);
                    });
                };
                backBtn.textContent = "← BACK TO TRIBE";
            }
            
            const sideHeader = document.getElementById("starmap-side-header");
            const sideInputBar = document.getElementById("starmap-input-bar");
            const sideOutput = document.getElementById("starmap-chat-output");
            if (sideHeader) {
                sideHeader.textContent = `░ NEBULA CONSTELLATION: ${cluster.label.toUpperCase()}`;
                sideHeader.style.color = cluster.color;
                sideHeader.style.borderBottomColor = cluster.color + "40";
            }
            if (sideInputBar) {
                sideInputBar.style.display = "flex";
                sideInputBar.style.borderTopColor = cluster.color;
                const querySpan = sideInputBar.querySelector("span");
                if (querySpan) querySpan.style.color = cluster.color;
            }
            
            if (nebulaLoadingPromise) {
                svg.innerHTML = `
                    <defs>
                        <radialGradient id="nebula-gradient" cx="50%" cy="50%" r="50%">
                            <stop offset="0%" stop-color="${cluster.color}" stop-opacity="1" />
                            <stop offset="100%" stop-color="var(--accent-cyan)" stop-opacity="0" />
                        </radialGradient>
                    </defs>
                    <g transform="translate(${width/2}, ${height/2})">
                        <circle r="60" fill="none" stroke="${cluster.color}" stroke-width="1.5" stroke-dasharray="15, 10" stroke-opacity="0.6">
                            <animateTransform 
                                attributeName="transform" 
                                type="rotate" 
                                from="0" to="360" 
                                dur="6s" 
                                repeatCount="indefinite" />
                        </circle>
                        <circle r="40" fill="none" stroke="var(--accent-cyan)" stroke-width="1" stroke-dasharray="8, 6" stroke-opacity="0.8">
                            <animateTransform 
                                attributeName="transform" 
                                type="rotate" 
                                from="360" to="0" 
                                dur="4s" 
                                repeatCount="indefinite" />
                        </circle>
                        <circle r="15" fill="url(#nebula-gradient)">
                            <animate 
                                attributeName="r" 
                                values="12;18;12" 
                                dur="2s" 
                                repeatCount="indefinite" />
                            <animate 
                                attributeName="fill-opacity" 
                                values="0.6;1;0.6" 
                                dur="2s" 
                                repeatCount="indefinite" />
                        </circle>
                        <text y="90" text-anchor="middle" fill="#cbd5e1" font-family="'Share Tech Mono', monospace" font-size="0.72rem" letter-spacing="2px">
                            INITIALIZING COHORT PCA SPACE...
                        </text>
                    </g>
                `;
                return;
            }
            
            if (!activeNebulaMembers || activeNebulaClusterId !== clusterId) {
                if (sideOutput) {
                    sideOutput.innerHTML = `
                        <div style="font-size: 0.72rem; border: 1px solid ${cluster.color}; padding: 0.5rem; background: ${cluster.color}0a; color: #cbd5e1; font-family:'Share Tech Mono';">
                            Loading local cohort PCA projection space for <strong>${escapeHTML(cluster.label)}</strong> micro-streamers...
                        </div>
                    `;
                }
                
                nebulaLoadingPromise = fetch(`/api/starmap/nebula/${clusterId}`)
                    .then(res => res.json())
                    .then(data => {
                        activeNebulaMembers = data.members || [];
                        activeNebulaClusterId = clusterId;
                        nebulaLoadingPromise = null;
                        renderNebulaView(clusterId);
                    })
                    .catch(err => {
                        console.error("Failed to fetch nebula cohort:", err);
                        nebulaLoadingPromise = null;
                        if (sideOutput) {
                            sideOutput.innerHTML = `<div style="color:var(--accent-red); font-family:'Share Tech Mono';">Error loading nebula cohort PCA space.</div>`;
                        }
                    });
                
                renderNebulaView(clusterId);
                return;
            }
            
            if (sideOutput && activeNebulaMembers) {
                const sortedNebula = [...activeNebulaMembers].sort((a, b) => {
                    const alignA = a.tribe_alignment !== undefined ? a.tribe_alignment : 1.0;
                    const alignB = b.tribe_alignment !== undefined ? b.tribe_alignment : 1.0;
                    return alignB - alignA;
                });
                sideOutput.innerHTML = `
                    <div style="font-size: 0.72rem; border: 1px solid ${cluster.color}; padding: 0.5rem; background: ${cluster.color}0a; color: #cbd5e1; font-family:'Share Tech Mono';">
                        Tribe <strong style="color:${cluster.color};">${escapeHTML(cluster.label)}</strong> Micro-streamer Cohort loaded.
                        <div style="margin-top:0.35rem; font-size:0.68rem; max-height: 250px; overflow-y: auto;">
                            <strong>Members (×${sortedNebula.length}) sorted by Alignment:</strong><br/>
                            ${sortedNebula.map((m, idx) => {
                                const alignVal = m.tribe_alignment !== undefined ? m.tribe_alignment : 1.0;
                                const alignPct = (alignVal * 100).toFixed(0);
                                return `<span style="display:block; padding: 0.15rem 0; border-bottom: 1px solid rgba(255,255,255,0.03); cursor:pointer; text-decoration:underline;" onclick="openStreamerProfileDrawer('${escapeHTML(m.handle)}')">⚡ #${idx+1} @${escapeHTML(m.display_name || m.handle)} [${alignPct}%] (${escapeHTML(m.primary_game)})</span>`;
                            }).join('')}
                        </div>
                    </div>
                    <div style="color: var(--text-muted); text-align: center; margin-top: 2rem; font-size: 0.75rem; font-family:'Share Tech Mono';">
                        ░ Hover over or click star nodes to inspect micro-streamer profiles.
                    </div>
                `;
            }
            
            const nodes = activeNebulaMembers.map(m => {
                const proj = project3D(m.x, m.y, m.z || 0.0, width, height);
                const alignment = m.tribe_alignment !== undefined ? m.tribe_alignment : 1.0;
                const size = Math.max(5, Math.min(18, (4 + alignment * 8) * proj.perspective));
                return {
                    handle: m.handle,
                    x: proj.x,
                    y: proj.y,
                    depth: proj.depth,
                    perspective: proj.perspective,
                    size: size,
                    tribe_alignment: alignment,
                    is_island: m.is_island || false,
                    raw: m
                };
            });
            
            nodes.sort((a, b) => b.depth - a.depth);

            // Draw geometric constellation links for Nebula View
            const linksDrawn = new Set();
            nodes.forEach(nodeA => {
                const targets = nodes
                    .filter(nodeB => nodeB.handle !== nodeA.handle)
                    .map(nodeB => {
                        const dist = Math.hypot(
                            nodeA.raw.x - nodeB.raw.x,
                            nodeA.raw.y - nodeB.raw.y,
                            (nodeA.raw.z || 0.0) - (nodeB.raw.z || 0.0)
                        );
                        return { node: nodeB, dist: dist };
                    });
                
                targets.sort((a, b) => a.dist - b.dist);
                
                const maxLinkDist = 0.85;
                targets.slice(0, 2).forEach(t => {
                    if (t.dist < maxLinkDist) {
                        const linkKey = [nodeA.handle, t.node.handle].sort().join("-");
                        if (!linksDrawn.has(linkKey)) {
                            linksDrawn.add(linkKey);
                            
                            const line = document.createElementNS("http://www.w3.org/2000/svg", "line");
                            line.setAttribute("x1", nodeA.x);
                            line.setAttribute("y1", nodeA.y);
                            line.setAttribute("x2", t.node.x);
                            line.setAttribute("y2", t.node.y);
                            
                            line.setAttribute("stroke", cluster.color);
                            line.setAttribute("stroke-width", "0.75");
                            line.setAttribute("stroke-dasharray", "3,3");
                            
                            const avgDepth = (nodeA.depth + t.node.depth) / 2;
                            line.classList.add("constellation-link");
                            line.style.setProperty("--pulse-dur", "5s");
                            const maxOpacity = Math.max(0.5, Math.min(0.85, 0.72 - avgDepth * 0.1));
                            line.style.setProperty("--max-opacity", maxOpacity.toFixed(3));
                            line.style.setProperty("--min-opacity", Math.max(0.22, (maxOpacity * 0.4)).toFixed(3));
                            
                            svg.appendChild(line);
                        }
                    }
                });
            });
            
            nodes.forEach(n => {
                const x = n.x;
                const y = n.y;
                const size = n.size;
                const m = n.raw;
                
                const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
                group.setAttribute("data-member-handle", m.handle);
                group.style.cursor = "pointer";
                
                group.addEventListener("mouseenter", () => {
                    if (hud) {
                        const alignment = m.tribe_alignment !== undefined ? m.tribe_alignment : 1.0;
                        const isIsland = m.is_island || false;
                        const alignmentPercent = (alignment * 100).toFixed(1);
                        const alignmentStatus = isIsland ? "Island Outlier 🏝️" : "Tribe Core";
                        hud.innerHTML = `<span style="color:${cluster.color}; font-weight:bold;">NEBULA STREAMER:</span> @${escapeHTML(m.display_name || m.handle)} | Game: <strong style="color:#fff;">${escapeHTML(m.primary_game)}</strong> | ` +
                                        `Tribe Alignment: <strong style="color:${isIsland ? 'var(--accent-pink)' : 'var(--accent-cyan)'};">${alignmentPercent}% (${alignmentStatus})</strong><br/>` +
                                        `<span style="color:var(--text-muted); font-size:0.65rem;">Tags:</span> ${m.tags.join(", ") || "None"}<br/>` +
                                        `<span style="color:var(--text-muted); font-size:0.65rem;">Bio:</span> <span style="font-style:italic;">"${escapeHTML(m.bio || 'No description provided')}"</span>`;
                        hud.style.display = "block";
                    }
                });
                
                group.addEventListener("mouseleave", () => {
                    if (hud) hud.style.display = "none";
                });
                
                group.onclick = (e) => {
                    e.stopPropagation();
                    openStreamerProfileDrawer(m.handle);
                };
                
                const alignment = m.tribe_alignment !== undefined ? m.tribe_alignment : 1.0;
                const isIsland = m.is_island || false;
                const star = document.createElementNS("http://www.w3.org/2000/svg", "circle");
                star.setAttribute("cx", x);
                star.setAttribute("cy", y);
                star.setAttribute("r", size);
                star.setAttribute("fill", cluster.color);
                star.setAttribute("stroke", isIsland ? "#94a3b8" : "#fff");
                star.setAttribute("stroke-width", isIsland ? "0.5" : "1");
                if (isIsland) {
                    star.style.filter = "none";
                } else {
                    const glowRadius = Math.max(2, Math.min(8, 2 + alignment * 6));
                    star.style.filter = `drop-shadow(0 0 ${glowRadius}px ${cluster.color})`;
                }
                const baseOpacity = isIsland ? 0.35 : Math.max(0.4, Math.min(1.0, n.perspective));
                star.setAttribute("fill-opacity", baseOpacity);
                
                const text = document.createElementNS("http://www.w3.org/2000/svg", "text");
                text.setAttribute("x", x);
                text.setAttribute("y", y + size + 10);
                text.setAttribute("text-anchor", "middle");
                text.setAttribute("fill", "#e2e8f0");
                text.setAttribute("font-family", "'Share Tech Mono', monospace");
                text.setAttribute("font-size", "0.62rem");
                text.setAttribute("fill-opacity", Math.max(0.4, Math.min(1.0, n.perspective)));
                text.textContent = m.display_name || m.handle;
                
                group.appendChild(star);
                group.appendChild(text);
                svg.appendChild(group);
            });
        }


        async function handleStarmapChatKey(event) {
            if (event.key !== "Enter") return;
            
            const key = checkKey();
            if (!key && !serverKeyConfigured) {
                logout();
                return;
            }

            const input = document.getElementById("starmap-chat-input");
            const query = input.value.trim();
            if (!query || !starmapData || currentTribeId === null) return;
            const tribe = starmapData.clusters[currentTribeId];
            const tribeColor = (tribe && tribe.color) || "var(--accent-cyan)";
            
            input.value = "";
            input.disabled = true;
            
            const output = document.getElementById("starmap-chat-output");
            
            // Clean up help text on first message if present
            const helpTexts = output.querySelectorAll('div[style*="text-align: center"]');
            helpTexts.forEach(el => el.remove());
            
            // Append User query
            const userMsgDiv = document.createElement("div");
            userMsgDiv.style.borderLeft = `2px solid ${tribeColor}`;
            userMsgDiv.style.paddingLeft = "0.5rem";
            userMsgDiv.style.marginBottom = "0.75rem";
            userMsgDiv.innerHTML = `
                <div style="color: ${tribeColor}; font-family: 'Share Tech Mono', monospace; font-size: 0.72rem; font-weight: bold; margin-bottom: 0.15rem;">░ USER_QUERY:</div>
                <div style="color: #fff; font-family: 'Share Tech Mono', monospace; font-size: 0.85rem;">${escapeHTML(query)}</div>
            `;
            output.appendChild(userMsgDiv);
            
            // Append loader block
            const loaderDiv = document.createElement("div");
            loaderDiv.style.borderLeft = `2px solid ${tribeColor}`;
            loaderDiv.style.paddingLeft = "0.5rem";
            loaderDiv.style.marginBottom = "1.25rem";
            output.appendChild(loaderDiv);
            renderAgentDiagnosticLoader(loaderDiv, "chatbot", "Decrypting intra-cluster synergy vector");
            output.scrollTop = output.scrollHeight;
            
            const tribeContext = `The user is querying Vibe Tribe cluster: "${tribe.label}" (color: ${tribe.color}, members: ${tribe.members.map(m => `@${m.handle}`).join(", ")}, bellwether rankings: ${tribe.members.map(m => `@${m.handle}: ${m.bellwether_score.toFixed(3)}`).join(", ")}). Intra-cluster convergence velocity signals: ${tribe.intra_links.map(l => `@${l.a} <-> @${l.b}: ${l.velocity.toFixed(3)} (${l.direction})`).join(", ")}. `;
            
            try {
                const analysisModel = localStorage.getItem('gemini_model_analysis') || 'gemma-4-31b-it';
                const response = await fetch("/api/recommend", {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json",
                        "X-Gemini-Chat-Model": analysisModel
                    },
                    body: JSON.stringify({
                        query: tribeContext + query
                    })
                });
                
                if (response.status === 401) {
                    logout();
                    return;
                }

                if (!response.ok) throw new Error("Chat request failed");
                const resData = await response.json();
                
                const html = marked.parse(resData.recommendation || "No response received.");
                
                // Replace loader with the real response
                loaderDiv.innerHTML = `
                    <div style="color: ${tribeColor}; font-family: 'Share Tech Mono', monospace; font-size: 0.72rem; font-weight: bold; margin-bottom: 0.15rem;">░ WOR-ACLE_SYNERGY_DECRYPTED:</div>
                    <div class="starmap-chat-response" style="color: #cbd5e1; font-family: 'Outfit', 'Inter', sans-serif; font-size: 0.82rem; line-height: 1.45;">
                        ${html}
                    </div>
                `;
            } catch (err) {
                console.error(err);
                loaderDiv.style.borderLeft = "2px solid var(--accent-red)";
                loaderDiv.innerHTML = `
                    <div style="color: var(--accent-red); font-family: 'Share Tech Mono', monospace; font-size: 0.72rem; font-weight: bold; margin-bottom: 0.15rem;">░ TRANSMISSION_SHIELDED:</div>
                    <div style="color: var(--accent-red); font-size: 0.8rem; font-family: 'Share Tech Mono', monospace;">
                        ERROR: TRANSMISSION SHIELDED. PLEASE ENSURE API KEY IS ACTIVE.
                    </div>
                `;
            } finally {
                input.disabled = false;
                input.focus();
                output.scrollTop = output.scrollHeight;
            }
        }

        let activeForecastData = null;
        let isForecastCollapsed = false;

        function toggleForecastCollapse() {
            const container = document.getElementById('forecast-controls-container');
            const indicator = document.getElementById('forecast-collapse-indicator');
            if (!container || !indicator) return;
            
            isForecastCollapsed = !isForecastCollapsed;
            if (isForecastCollapsed) {
                container.style.display = 'none';
                indicator.textContent = '▼';
            } else {
                container.style.display = 'flex';
                indicator.textContent = '▲';
            }
        }

        function runForecast() {
            const handle = currentDrawerStreamer;
            if (!handle) return;

            const statusEl = document.getElementById('forecast-status');
            const chartContainer = document.getElementById('forecast-chart-container');
            const svgWrapper = document.getElementById('forecast-svg-wrapper');
            const statsEl = document.getElementById('forecast-stats');
            const horizon = document.getElementById('forecast-horizon-selector').value;

            if (statusEl) statusEl.textContent = 'CALCULATING...';
            if (chartContainer) chartContainer.style.display = 'block';
            if (svgWrapper) {
                svgWrapper.innerHTML = `
                    <div style="padding: 1.5rem; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.5rem;">
                        <div class="spinner" style="width: 24px; height: 24px; border: 2px solid rgba(181, 23, 158, 0.2); border-top-color: var(--accent-purple); border-radius: 50%; animation: spin 1s linear infinite;"></div>
                        <span style="font-size: 0.72rem; color: var(--accent-purple); letter-spacing: 0.05em; font-family: 'Press Start 2P';">CALCULATING FORECAST...</span>
                    </div>
                `;
            }
            if (statsEl) statsEl.innerHTML = '';

            fetch(`/api/streamers/${encodeURIComponent(handle)}/forecast?horizon=${horizon}`)
                .then(res => {
                    if (res.status === 429) {
                        throw new Error("Rate limit exceeded. Max 2 requests per minute.");
                    }
                    if (!res.ok) {
                        throw new Error(`Server returned status ${res.status}`);
                    }
                    return res.json();
                })
                .then(data => {
                    if (statusEl) statusEl.textContent = 'READY';
                    if (data.status === 'insufficient_data') {
                        activeForecastData = null;
                        if (svgWrapper) {
                            svgWrapper.innerHTML = `
                                <div style="font-size: 0.72rem; color: var(--accent-pink); font-style: italic; padding: 0.5rem; border: 1px dashed rgba(255, 0, 127, 0.2); background: rgba(255, 0, 127, 0.02); text-align: left; line-height: 1.45;">
                                    ⚠️ <strong>INSUFFICIENT HISTORY DATA</strong><br>
                                    ${escapeHTML(data.message)}<br>
                                    Data is automatically collected hourly. Run the Realtime Chat Radar to add instant telemetry checkpoints.
                                </div>
                            `;
                        }
                        return;
                    }

                    activeForecastData = data;
                    updateForecastChart();
                })
                .catch(err => {
                    console.error(err);
                    if (statusEl) statusEl.textContent = 'ERROR';
                    if (svgWrapper) {
                        svgWrapper.innerHTML = `
                            <div style="font-size: 0.72rem; color: var(--accent-pink); font-style: italic; padding: 0.5rem; border: 1px dashed rgba(255, 0, 127, 0.2); background: rgba(255, 0, 127, 0.02); text-align: left;">
                                ❌ <strong>FORECAST ENGINE ERROR</strong><br>
                                ${escapeHTML(err.message)}
                            </div>
                        `;
                    }
                });
        }

        function updateForecastChart() {
            if (!activeForecastData || !activeForecastData.predictions) return;

            const svgWrapper = document.getElementById('forecast-svg-wrapper');
            const statsEl = document.getElementById('forecast-stats');
            const metric = document.getElementById('forecast-metric-selector').value;

            if (!svgWrapper || !statsEl) return;

            const data = activeForecastData.predictions[metric];
            if (!data) return;

            const history = data.history || [];
            const forecast = data.forecast || [];
            const ciUpper = data.ci_upper || [];
            const ciLower = data.ci_lower || [];

            const allVals = [...history, ...forecast, ...ciUpper, ...ciLower];
            const minVal = Math.min(...allVals);
            const maxVal = Math.max(...allVals);

            let finalMin = minVal;
            let finalRange = maxVal - minVal;

            if (metric === 'rolling_sentiment_score') {
                finalMin = -1.0;
                finalRange = 2.0;
            } else {
                if (finalRange === 0) finalRange = 1.0;
                finalMin = Math.max(0.0, finalMin - 0.05 * finalRange);
                finalRange = finalRange * 1.1;
            }

            const width = 310;
            const height = 80;
            const H = history.length;
            const F = forecast.length;
            const T = H + F;

            function getX(idx) {
                return (idx / (T - 1)) * width;
            }

            function getY(val) {
                if (finalRange <= 0) return height / 2;
                return height - ((val - finalMin) / finalRange) * (height - 12) - 6;
            }

            let polyPoints = [];
            for (let i = 0; i < F; i++) {
                const idx = H + i;
                polyPoints.push(`${getX(idx).toFixed(1)},${getY(ciUpper[i]).toFixed(1)}`);
            }
            for (let i = F - 1; i >= 0; i--) {
                const idx = H + i;
                polyPoints.push(`${getX(idx).toFixed(1)},${getY(ciLower[i]).toFixed(1)}`);
            }
            const junctionX = getX(H - 1);
            const junctionY = getY(history[H - 1]);
            polyPoints.unshift(`${junctionX.toFixed(1)},${junctionY.toFixed(1)}`);
            polyPoints.push(`${junctionX.toFixed(1)},${junctionY.toFixed(1)}`);

            const polyPointsStr = polyPoints.join(' ');

            let color = 'var(--accent-purple)';
            if (metric === 'viewer_count') color = 'var(--accent-green)';
            else if (metric === 'msg_per_minute') color = 'var(--accent-cyan)';
            else if (metric === 'rolling_sentiment_score') color = 'var(--accent-yellow)';

            let histPathPoints = [];
            for (let i = 0; i < H; i++) {
                histPathPoints.push(`${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(history[i]).toFixed(1)}`);
            }
            const histPathStr = histPathPoints.join(' ');

            let forePathPoints = [`M ${junctionX.toFixed(1)} ${junctionY.toFixed(1)}`];
            for (let i = 0; i < F; i++) {
                forePathPoints.push(`L ${getX(H + i).toFixed(1)} ${getY(forecast[i]).toFixed(1)}`);
            }
            const forePathStr = forePathPoints.join(' ');

            svgWrapper.innerHTML = `
                <svg width="${width}" height="${height}" style="background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(255,255,255,0.05); box-shadow: inset 0 0 10px rgba(0,0,0,0.8); overflow: visible;">
                    <line x1="${junctionX}" y1="0" x2="${junctionX}" y2="${height}" stroke="rgba(255,255,255,0.15)" stroke-dasharray="2,2" />
                    <line x1="0" y1="${height/2}" x2="${width}" y2="${height/2}" stroke="rgba(255,255,255,0.05)" stroke-dasharray="1,4" />
                    <polygon points="${polyPointsStr}" fill="${color}" opacity="0.12" />
                    <path d="${histPathStr}" fill="none" stroke="${color}" stroke-width="2" />
                    <path d="${forePathStr}" fill="none" stroke="${color}" stroke-width="2" stroke-dasharray="2,3" />
                    <circle cx="${junctionX}" cy="${junctionY}" r="4.5" fill="${color}" style="filter: drop-shadow(0 0 4px ${color});">
                        <animate attributeName="r" values="3.5;6;3.5" dur="2s" repeatCount="indefinite" />
                        <animate attributeName="opacity" values="1;0.3;1" dur="2s" repeatCount="indefinite" />
                    </circle>
                </svg>
            `;

            const latestVal = history[H - 1];
            const nextVal = forecast[0];
            const direction = nextVal > latestVal ? '▲ UPWARD' : '▼ DOWNWARD';
            const dirColor = nextVal > latestVal ? 'var(--accent-green)' : 'var(--accent-pink)';

            statsEl.innerHTML = `
                <div style="flex: 1 1 45%; display: flex; flex-direction: column;">
                    <span>TRAJECTORY: <strong style="color: ${dirColor};">${direction}</strong></span>
                    <span>FIT (R2): <strong style="color: #fff;">${data.r2_score >= 0 ? data.r2_score.toFixed(3) : 'N/A'}</strong></span>
                </div>
                <div style="flex: 1 1 45%; display: flex; flex-direction: column; align-items: flex-end;">
                    <span>SAMPLES (N): <strong style="color: #fff;">${activeForecastData.sample_count} (df: ${activeForecastData.degrees_of_freedom})</strong></span>
                    <span>STD ERROR: <strong style="color: #fff;">${data.std_error.toFixed(2)}</strong></span>
                </div>
            `;
        }

        let activeTribeForecastData = null;
        let activeTribeColor = '#00f0ff';

        function runTribeForecast(clusterId) {
            const container = document.getElementById('tribe-forecast-container');
            const svgWrapper = document.getElementById('tribe-forecast-svg-wrapper');
            const statsEl = document.getElementById('tribe-forecast-stats');
            
            if (!starmapData || !starmapData.clusters[clusterId]) return;
            activeTribeColor = starmapData.clusters[clusterId].color || '#00f0ff';

            if (container) container.style.display = 'block';
            if (svgWrapper) {
                svgWrapper.innerHTML = `
                    <div style="padding: 1rem; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 0.35rem;">
                        <div class="spinner" style="width: 16px; height: 16px; border: 2px solid rgba(255, 255, 255, 0.1); border-top-color: ${activeTribeColor}; border-radius: 50%; animation: spin 1s linear infinite;"></div>
                        <span style="font-size: 0.6rem; color: ${activeTribeColor}; letter-spacing: 0.05em; font-family: 'Press Start 2P';">PREDICTING...</span>
                    </div>
                `;
            }
            if (statsEl) statsEl.innerHTML = '';

            fetch(`/api/tribes/${encodeURIComponent(clusterId)}/forecast?horizon=3`)
                .then(res => {
                    if (res.status === 429) {
                        throw new Error("Rate limit exceeded. Max 2 requests per minute.");
                    }
                    if (!res.ok) {
                        throw new Error(`Server status ${res.status}`);
                    }
                    return res.json();
                })
                .then(data => {
                    if (data.status === 'insufficient_data') {
                        activeTribeForecastData = null;
                        if (svgWrapper) {
                            svgWrapper.innerHTML = `
                                <div style="font-size: 0.65rem; color: var(--accent-pink); font-style: italic; padding: 0.25rem;">
                                    ⚠️ <strong>INSUFFICIENT TELEMETRY</strong><br>
                                    Tribe members require at least 2 database entries total.
                                </div>
                            `;
                        }
                        return;
                    }

                    activeTribeForecastData = data;
                    updateTribeForecastChart();
                })
                .catch(err => {
                    console.error(err);
                    if (svgWrapper) {
                        svgWrapper.innerHTML = `
                            <div style="font-size: 0.65rem; color: var(--accent-pink); font-style: italic; padding: 0.25rem;">
                                ❌ ERROR: ${escapeHTML(err.message)}
                            </div>
                        `;
                    }
                });
        }

        function updateTribeForecastChart() {
            if (!activeTribeForecastData || !activeTribeForecastData.predictions) return;

            const svgWrapper = document.getElementById('tribe-forecast-svg-wrapper');
            const statsEl = document.getElementById('tribe-forecast-stats');
            const metric = document.getElementById('tribe-forecast-metric-selector').value;

            if (!svgWrapper || !statsEl) return;

            const data = activeTribeForecastData.predictions[metric];
            if (!data) return;

            const history = data.history || [];
            const forecast = data.forecast || [];
            const ciUpper = data.ci_upper || [];
            const ciLower = data.ci_lower || [];

            const allVals = [...history, ...forecast, ...ciUpper, ...ciLower];
            const minVal = Math.min(...allVals);
            const maxVal = Math.max(...allVals);

            let finalMin = minVal;
            let finalRange = maxVal - minVal;

            if (metric === 'rolling_sentiment_score') {
                finalMin = -1.0;
                finalRange = 2.0;
            } else {
                if (finalRange === 0) finalRange = 1.0;
                finalMin = Math.max(0.0, finalMin - 0.05 * finalRange);
                finalRange = finalRange * 1.1;
            }

            const width = 240;
            const height = 65;
            const H = history.length;
            const F = forecast.length;
            const T = H + F;

            function getX(idx) {
                return (idx / (T - 1)) * width;
            }

            function getY(val) {
                if (finalRange <= 0) return height / 2;
                return height - ((val - finalMin) / finalRange) * (height - 8) - 4;
            }

            let polyPoints = [];
            for (let i = 0; i < F; i++) {
                const idx = H + i;
                polyPoints.push(`${getX(idx).toFixed(1)},${getY(ciUpper[i]).toFixed(1)}`);
            }
            for (let i = F - 1; i >= 0; i--) {
                const idx = H + i;
                polyPoints.push(`${getX(idx).toFixed(1)},${getY(ciLower[i]).toFixed(1)}`);
            }
            const junctionX = getX(H - 1);
            const junctionY = getY(history[H - 1]);
            polyPoints.unshift(`${junctionX.toFixed(1)},${junctionY.toFixed(1)}`);
            polyPoints.push(`${junctionX.toFixed(1)},${junctionY.toFixed(1)}`);

            const polyPointsStr = polyPoints.join(' ');

            let histPathPoints = [];
            for (let i = 0; i < H; i++) {
                histPathPoints.push(`${i === 0 ? 'M' : 'L'} ${getX(i).toFixed(1)} ${getY(history[i]).toFixed(1)}`);
            }
            const histPathStr = histPathPoints.join(' ');

            let forePathPoints = [`M ${junctionX.toFixed(1)} ${junctionY.toFixed(1)}`];
            for (let i = 0; i < F; i++) {
                forePathPoints.push(`L ${getX(H + i).toFixed(1)} ${getY(forecast[i]).toFixed(1)}`);
            }
            const forePathStr = forePathPoints.join(' ');

            svgWrapper.innerHTML = `
                <svg width="100%" height="${height}" viewBox="0 0 240 ${height}" style="background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(255,255,255,0.05); box-shadow: inset 0 0 10px rgba(0,0,0,0.8); overflow: visible;">
                    <line x1="${junctionX}" y1="0" x2="${junctionX}" y2="${height}" stroke="rgba(255,255,255,0.15)" stroke-dasharray="2,2" />
                    <line x1="0" y1="${height/2}" x2="${width}" y2="${height/2}" stroke="rgba(255,255,255,0.05)" stroke-dasharray="1,4" />
                    <polygon points="${polyPointsStr}" fill="${activeTribeColor}" opacity="0.12" />
                    <path d="${histPathStr}" fill="none" stroke="${activeTribeColor}" stroke-width="1.5" />
                    <path d="${forePathStr}" fill="none" stroke="${activeTribeColor}" stroke-width="1.5" stroke-dasharray="2,2" />
                    <circle cx="${junctionX}" cy="${junctionY}" r="3.5" fill="${activeTribeColor}">
                        <animate attributeName="r" values="2.5;4.5;2.5" dur="2s" repeatCount="indefinite" />
                    </circle>
                </svg>
            `;

            const latestVal = history[H - 1];
            const nextVal = forecast[0];
            const direction = nextVal > latestVal ? '▲ UP' : '▼ DOWN';
            const dirColor = nextVal > latestVal ? 'var(--accent-green)' : 'var(--accent-pink)';

            statsEl.innerHTML = `
                <div style="flex: 1 1 50%; display: flex; flex-direction: column; align-items: flex-start; font-size: 0.72rem;">
                    <span>DIR: <strong style="color: ${dirColor};">${direction}</strong></span>
                    <span>FIT (R2): <strong style="color: #fff;">${data.r2_score >= 0 ? data.r2_score.toFixed(2) : 'N/A'}</strong></span>
                </div>
                <div style="flex: 1 1 50%; display: flex; flex-direction: column; align-items: flex-end; font-size: 0.72rem;">
                    <span>SAMPLES: <strong style="color: #fff;">${activeTribeForecastData.sample_count}</strong></span>
                    <span>ERR: <strong style="color: #fff;">${data.std_error.toFixed(1)}</strong></span>
                </div>
            `;
        }

        // --- Community Vibe Matchmaker & Orbit Console Helpers ---
        const AGENT_DIAGNOSTIC_REGISTRY = {
            chatbot: {
                agent: "WOR-ACLE Core",
                color: "var(--accent-green)",
                logs: [
                    "Querying vector database context...",
                    "Consulting live Google Search indices...",
                    "Analyzing channel convergence drift...",
                    "Synthesizing strategic consensus..."
                ]
            },
            playbooks: {
                agent: "Strategy Planner",
                color: "var(--accent-pink)",
                logs: [
                    "Analyzing stream duration constraints...",
                    "Fetching category player counts...",
                    "Calculating process control thresholds...",
                    "Compiling prep strategies & chat hooks..."
                ]
            },
            radar: {
                agent: "RaidSentinel Uplink",
                color: "var(--accent-cyan)",
                logs: [
                    "Connecting to Twitch IRC sockets...",
                    "Measuring message frequency spikes...",
                    "Plotting active sentiment polarity..."
                ]
            },
            matchmaker: {
                agent: "Vibe Scout",
                color: "var(--accent-purple)",
                logs: [
                    "Parsing custom channel metadata...",
                    "Evaluating Jaccard token similarities...",
                    "Mapping nearest Bellwether gravity well...",
                    "Determining 3D starfield coordinates..."
                ]
            }
        };

        function renderAgentDiagnosticLoader(container, key, textLabel = "") {
            const config = AGENT_DIAGNOSTIC_REGISTRY[key] || { agent: "System", color: "var(--text-color)", logs: ["Loading..."] };
            const canvasId = `loader-canvas-${Math.floor(Math.random() * 100000)}`;
            const textId = `loader-text-${Math.floor(Math.random() * 100000)}`;
            
            container.innerHTML = `
                <div class="agent-diagnostic-loader" style="padding: 1rem; text-align: center; font-family: 'Share Tech Mono', monospace; border: 1px dashed rgba(255,255,255,0.06); background: rgba(0,0,0,0.2);">
                    <div style="font-size: 0.75rem; font-weight: bold; color: ${config.color}; margin-bottom: 0.35rem; text-transform: uppercase; letter-spacing: 0.05em;">
                        📡 ${config.agent} Active
                    </div>
                    <canvas id="${canvasId}" width="280" height="35" style="width: 100%; max-width: 280px; height: 35px; margin: 0.4rem auto; display: block; border: 1px solid rgba(255,255,255,0.03); background: rgba(0,0,0,0.3);"></canvas>
                    <div id="${textId}" style="font-size: 0.68rem; color: var(--text-muted); min-height: 1.1rem; margin-top: 0.2rem; line-height: 1.3;">
                        ${config.logs[0]}
                    </div>
                    ${textLabel ? `<div style="font-size: 0.65rem; color: rgba(255,255,255,0.35); margin-top: 0.35rem;">${textLabel}</div>` : ''}
                </div>
            `;
            
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            let phase = 0;
            let animId;
            
            function drawWave() {
                if (!document.body.contains(canvas)) {
                    cancelAnimationFrame(animId);
                    return;
                }
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                
                // Draw grid lines
                ctx.strokeStyle = 'rgba(255, 255, 255, 0.01)';
                ctx.lineWidth = 1;
                for (let x = 0; x < canvas.width; x += 30) {
                    ctx.beginPath();
                    ctx.moveTo(x, 0);
                    ctx.lineTo(x, canvas.height);
                    ctx.stroke();
                }
                
                // Draw wave line
                ctx.strokeStyle = config.color;
                ctx.shadowColor = config.color;
                ctx.shadowBlur = 3;
                ctx.lineWidth = 1.2;
                ctx.beginPath();
                
                for (let x = 0; x < canvas.width; x++) {
                    const y = canvas.height / 2 + 
                              Math.sin(x * 0.06 + phase) * 6 * Math.sin(x * 0.01) + 
                              Math.cos(x * 0.15 - phase * 0.8) * 2 * Math.random();
                    if (x === 0) {
                        ctx.moveTo(x, y);
                    } else {
                        ctx.lineTo(x, y);
                    }
                }
                ctx.stroke();
                ctx.shadowBlur = 0;
                
                phase += 0.15;
                animId = requestAnimationFrame(drawWave);
            }
            drawWave();
            
            let logIndex = 0;
            const intervalId = setInterval(() => {
                const textEl = document.getElementById(textId);
                if (!textEl || !document.body.contains(textEl)) {
                    clearInterval(intervalId);
                    return;
                }
                logIndex = (logIndex + 1) % config.logs.length;
                textEl.innerText = config.logs[logIndex];
            }, 3000);
        }

        let selectedVibeTags = new Set();
        
        function toggleVibeTag(btn) {
            const tag = btn.getAttribute('data-tag');
            if (selectedVibeTags.has(tag)) {
                selectedVibeTags.delete(tag);
                btn.style.background = 'transparent';
                btn.style.color = 'var(--text-color)';
                btn.style.border = '1px solid var(--border-color)';
            } else {
                selectedVibeTags.add(tag);
                btn.style.background = 'var(--accent-pink)';
                btn.style.color = '#000';
                btn.style.border = '1px solid var(--accent-pink)';
            }
        }
        
        async function loadEcosystemOverview() {
            try {
                const res = await fetch('/api/starmap');
                const data = await res.json();
                
                const wellsContainer = document.getElementById('gravity-wells-list');
                const tribesContainer = document.getElementById('vibe-tribes-list');
                
                if (data.clusters && wellsContainer && tribesContainer) {
                    wellsContainer.innerHTML = '';
                    tribesContainer.innerHTML = '';
                    
                    Object.entries(data.clusters).forEach(([tribeId, tribeInfo]) => {
                        const members = tribeInfo.members || [];
                        const label = tribeInfo.label || `Tribe ${tribeId}`;
                        const color = tribeInfo.color || 'var(--accent-cyan)';
                        
                        const mainMember = tribeInfo.top_bellwether || 'Unknown';
                        let displayName = mainMember;
                        const matchedMember = members.find(m => m.handle === mainMember);
                        if (matchedMember && matchedMember.display_name) {
                            displayName = matchedMember.display_name;
                        }
                        
                        const wellEl = document.createElement('div');
                        wellEl.className = 'interactive-well-item';
                        wellEl.style.display = 'flex';
                        wellEl.style.justifyContent = 'space-between';
                        wellEl.style.alignItems = 'center';
                        wellEl.style.padding = '0.3rem 0.5rem';
                        wellEl.style.background = 'rgba(255,255,255,0.02)';
                        wellEl.style.border = '1px solid rgba(255,255,255,0.05)';
                        wellEl.style.cursor = 'pointer';
                        wellEl.style.transition = 'all 0.2s ease-in-out';
                        wellEl.innerHTML = `
                            <span style="color: #fff; font-weight: bold; font-family: 'Share Tech Mono';">⚡ @${displayName}</span>
                            <span style="font-size: 0.65rem; color: ${color}; font-family: 'Press Start 2P'; font-size: 0.55rem; letter-spacing: 0.05em;">[${label}]</span>
                        `;
                        wellEl.onmouseover = () => {
                            wellEl.style.background = 'rgba(0, 240, 255, 0.04)';
                            wellEl.style.borderColor = 'var(--accent-cyan)';
                            wellEl.style.boxShadow = '0 0 6px rgba(0, 240, 255, 0.15)';
                        };
                        wellEl.onmouseout = () => {
                            wellEl.style.background = 'rgba(255,255,255,0.02)';
                            wellEl.style.borderColor = 'rgba(255,255,255,0.05)';
                            wellEl.style.boxShadow = 'none';
                        };
                        wellEl.onclick = () => openStreamerProfileDrawer(mainMember);
                        wellsContainer.appendChild(wellEl);
                        
                        const tribeEl = document.createElement('div');
                        tribeEl.className = 'interactive-tribe-item';
                        tribeEl.style.display = 'flex';
                        tribeEl.style.justifyContent = 'space-between';
                        tribeEl.style.alignItems = 'center';
                        tribeEl.style.padding = '0.3rem 0.5rem';
                        tribeEl.style.cursor = 'pointer';
                        tribeEl.style.transition = 'all 0.2s ease-in-out';
                        tribeEl.innerHTML = `
                            <span style="color: ${color}; font-weight: bold; font-family: 'Share Tech Mono'; display: flex; align-items: center;"><span style="display:inline-block; width:6px; height:6px; border-radius:50%; background:${color}; margin-right:8px;"></span>${label}</span>
                            <span style="font-size: 0.68rem; color: var(--text-muted); font-family: 'Share Tech Mono';">${members.length} orbits</span>
                        `;
                        tribeEl.onmouseover = () => {
                            tribeEl.style.background = 'rgba(255, 0, 127, 0.03)';
                            tribeEl.style.boxShadow = `0 0 5px ${color}`;
                        };
                        tribeEl.onmouseout = () => {
                            tribeEl.style.background = 'transparent';
                            tribeEl.style.boxShadow = 'none';
                        };
                        tribeEl.onclick = () => switchToTribe(tribeId);
                        tribesContainer.appendChild(tribeEl);
                    });
                }
            } catch (err) {
                console.error("Failed to load ecosystem overview:", err);
            }
        }

        function switchToTribe(tribeId) {
            pendingTribeId = tribeId;
            currentTribeId = tribeId;
            switchTab('starmap');
            if (starmapData && starmapData.clusters && starmapData.clusters[tribeId]) {
                pendingTribeId = null;
                zoomToCluster(tribeId, null, null);
            }
        }
        
         async function runScanProfile() {
            const handleInput = document.getElementById('matchmaker-handle');
            const handle = handleInput ? handleInput.value.trim() : '';
            if (!handle) {
                alert("Please enter a streamer handle first.");
                return;
            }
            
            const bioInput = document.getElementById('matchmaker-bio');
            const bio = bioInput ? bioInput.value.trim() : '';
            const gameInput = document.getElementById('matchmaker-game');
            const game = gameInput ? gameInput.value.trim() : '';
            
            const isBootstrapping = (bio !== "" || selectedVibeTags.size > 0 || game !== "");
            
            const btn = document.getElementById('btn-scan-profile');
            const resultsEl = document.getElementById('matchmaker-results-display');
            
            btn.disabled = true;
            if (matchmakerBtnInterval) {
                clearInterval(matchmakerBtnInterval);
            }
            const matchmakerBtnText = isBootstrapping ? 'Bootstrapping' : 'Scanning';
            let matchmakerBtnPhase = 0;
            const matchmakerBtnIndicators = ['[ \\ ]', '[ | ]', '[ / ]', '[ - ]'];
            btn.innerHTML = `${matchmakerBtnIndicators[0]} ${matchmakerBtnText}...`;
            matchmakerBtnInterval = setInterval(() => {
                matchmakerBtnPhase = (matchmakerBtnPhase + 1) % matchmakerBtnIndicators.length;
                btn.innerHTML = `${matchmakerBtnIndicators[matchmakerBtnPhase]} ${matchmakerBtnText}...`;
            }, 250);
            resultsEl.style.display = 'block';
            
            try {
                const regRes = await fetch('/api/matchmaker/register', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        streamer_handle: handle,
                        bio_description: bio || "Live channel scan initiated.",
                        vibe_tags: isBootstrapping ? Array.from(selectedVibeTags) : ["Live Scan"],
                        primary_game: game || "General (No top game registered)",
                        is_bootstrap: isBootstrapping
                    })
                });
                
                if (!regRes.ok) {
                    throw new Error("Failed to register streamer profile");
                }
                
                startMatchmakerSSE(handle, resultsEl, btn, "Scan & Connect");
            } catch (err) {
                console.error(err);
                if (matchmakerBtnInterval) {
                    clearInterval(matchmakerBtnInterval);
                    matchmakerBtnInterval = null;
                }
                resultsEl.innerHTML = `<p style="color: var(--accent-pink); font-size: 0.75rem; text-align: center;">Error: ${err.message}</p>`;
                btn.disabled = false;
                btn.innerHTML = 'Scan & Connect';
            }
        }

        function drawLiveIDRHeartline(canvas, history) {
            const ctx = canvas.getContext('2d');
            ctx.clearRect(0, 0, canvas.width, canvas.height);
            
            // Draw grid lines
            ctx.strokeStyle = 'rgba(34, 197, 94, 0.04)';
            ctx.lineWidth = 1;
            for (let x = 0; x < canvas.width; x += 20) {
                ctx.beginPath();
                ctx.moveTo(x, 0);
                ctx.lineTo(x, canvas.height);
                ctx.stroke();
            }
            for (let y = 0; y < canvas.height; y += 10) {
                ctx.beginPath();
                ctx.moveTo(0, y);
                ctx.lineTo(canvas.width, y);
                ctx.stroke();
            }

            if (history.length === 0) return;

            // Plot sparkline
            ctx.strokeStyle = '#22c55e';
            ctx.lineWidth = 1.8;
            ctx.shadowColor = '#22c55e';
            ctx.shadowBlur = 4;
            ctx.beginPath();

            const maxVal = Math.max(...history, 0.05);
            const stepX = canvas.width / Math.max(history.length - 1, 1);

            for (let i = 0; i < history.length; i++) {
                const x = i * stepX;
                const y = canvas.height - 4 - ((history[i] / maxVal) * (canvas.height - 8));
                if (i === 0) {
                    ctx.moveTo(x, y);
                } else {
                    ctx.lineTo(x, y);
                }
            }
            ctx.stroke();
            ctx.shadowBlur = 0;
            
            ctx.fillStyle = 'rgba(34, 197, 94, 0.03)';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
        }
        
        function startMatchmakerSSE(handle, resultsEl, btn, btnLabel) {
            const hasKey = checkKey();
            const analysisModel = localStorage.getItem('gemini_model_analysis') || 'gemma-4-31b-it';
            let url = `/api/matchmaker/stream/${encodeURIComponent(handle)}`;
            url += `?model=${encodeURIComponent(analysisModel)}`;
            
            resultsEl.innerHTML = `
                <div class="agent-diagnostic-loader" style="padding: 1rem; font-family: 'Share Tech Mono', monospace; border: 1px dashed rgba(255,255,255,0.06); background: rgba(0,0,0,0.2);">
                    <div style="font-size: 0.85rem; font-weight: bold; color: var(--accent-pink); margin-bottom: 0.75rem; text-transform: uppercase; letter-spacing: 0.05em; display: flex; justify-content: space-between; align-items: center;">
                        <span>📡 VIBE SCOUT ONLINE</span>
                        <span id="scan-status-badge" style="background: var(--accent-green); color: #000; padding: 0.05rem 0.35rem; font-size: 0.55rem; font-family: 'Press Start 2P'; font-weight: bold;">CRAWLING</span>
                    </div>
                    
                    <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.4rem; margin-bottom: 0.75rem; font-size: 0.68rem; text-align: left; background: rgba(0,0,0,0.4); padding: 0.45rem; border: 1px solid rgba(255,255,255,0.03);">
                        <div>Status: <span id="scan-online-status" style="color: var(--text-muted);">Checking...</span></div>
                        <div>Category: <span id="scan-category" style="color: var(--accent-cyan);">Detecting...</span></div>
                        <div>Elapsed: <span id="scan-elapsed" style="color: var(--accent-pink);">0.0s / 120s</span></div>
                        <div>Viewers: <span id="scan-viewers" style="color: var(--accent-green);">1</span></div>
                        <div>Messages: <span id="scan-messages" style="color: var(--accent-green);">0</span></div>
                        <div>IDR Ratio: <span id="scan-idr" style="color: var(--accent-cyan);">0.0 MPM / IDR: 0.000</span></div>
                    </div>

                    <div style="font-size: 0.65rem; color: var(--text-muted); text-align: left; margin-bottom: 0.2rem; letter-spacing: 0.05em;">LIVE CHAT VOLATILITY HEARTBEAT (IDR)</div>
                    <canvas id="scan-idr-sparkline" width="300" height="70" style="width: 100%; height: 70px; display: block; border: 1px solid rgba(255,255,255,0.05); background: rgba(0,0,0,0.5); margin-bottom: 0.75rem;"></canvas>

                    <div id="scan-log-text" style="font-size: 0.68rem; color: var(--text-muted); min-height: 1.2rem; border-top: 1px dashed rgba(255,255,255,0.05); padding-top: 0.4rem; line-height: 1.3;">
                        Establishing secure connection to Twitch API...
                    </div>
                </div>
            `;

            const canvas = document.getElementById('scan-idr-sparkline');
            const idrHistory = [];
            let isOnline = false;
            let viewerCount = 1;
            let recommendationBuffer = "";
            let oscAnimId = null;
            
            const cleanUpMatchmakerBtn = () => {
                if (matchmakerBtnInterval) {
                    clearInterval(matchmakerBtnInterval);
                    matchmakerBtnInterval = null;
                }
                btn.disabled = false;
                btn.innerHTML = btnLabel;
            };

            const closeSSE = () => {
                evtSource.close();
                if (oscAnimId) {
                    cancelAnimationFrame(oscAnimId);
                    oscAnimId = null;
                }
            };

            const startOscilloscope = () => {
                let oscPhase = 0;
                const draw = () => {
                    if (!document.body.contains(canvas) || isOnline) {
                        if (oscAnimId) cancelAnimationFrame(oscAnimId);
                        return;
                    }
                    const ctx = canvas.getContext('2d');
                    ctx.clearRect(0, 0, canvas.width, canvas.height);
                    
                    // Draw grid lines
                    ctx.strokeStyle = 'rgba(34, 197, 94, 0.04)';
                    ctx.lineWidth = 1;
                    for (let x = 0; x < canvas.width; x += 20) {
                        ctx.beginPath();
                        ctx.moveTo(x, 0);
                        ctx.lineTo(x, canvas.height);
                        ctx.stroke();
                    }
                    for (let y = 0; y < canvas.height; y += 10) {
                        ctx.beginPath();
                        ctx.moveTo(0, y);
                        ctx.lineTo(canvas.width, y);
                        ctx.stroke();
                    }
                    
                    // Draw oscilloscope neon green sine wave
                    ctx.strokeStyle = '#22c55e';
                    ctx.lineWidth = 2.0;
                    ctx.shadowColor = '#22c55e';
                    ctx.shadowBlur = 6;
                    ctx.beginPath();
                    for (let x = 0; x < canvas.width; x++) {
                        const y = canvas.height / 2 + 
                                  Math.sin(x * 0.05 + oscPhase) * 15 * Math.sin(x * 0.01) + 
                                  Math.cos(x * 0.02 - oscPhase * 0.5) * 3;
                        if (x === 0) {
                            ctx.moveTo(x, y);
                        } else {
                            ctx.lineTo(x, y);
                        }
                    }
                    ctx.stroke();
                    ctx.shadowBlur = 0;
                    
                    ctx.fillStyle = 'rgba(34, 197, 94, 0.02)';
                    ctx.fillRect(0, 0, canvas.width, canvas.height);
                    
                    oscPhase += 0.08;
                    oscAnimId = requestAnimationFrame(draw);
                };
                draw();
            };

            const evtSource = new EventSource(url, { withCredentials: true });
            
            evtSource.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    
                    if (data.status === 'setup') {
                        isOnline = data.is_online;
                        viewerCount = data.viewer_count;
                        document.getElementById('scan-online-status').innerHTML = isOnline ? 
                            '<span style="color: var(--accent-green);">LIVE</span>' : 
                            '<span style="color: var(--accent-pink);">OFFLINE</span>';
                        document.getElementById('scan-category').innerHTML = isOnline ? 
                            escapeHTML(data.game_name) : 
                            '<span style="color: var(--accent-pink);">OFFLINE</span>';
                        document.getElementById('scan-viewers').innerText = isOnline ? viewerCount : '0 (offline)';
                        document.getElementById('scan-log-text').innerText = isOnline ?
                            `[Vibe Scout] Connected to @${handle}'s live stream.` :
                            `[Vibe Scout] @${handle} is offline. Initializing simulated telemetry...`;
                        
                        if (!isOnline && canvas) {
                            startOscilloscope();
                        }
                    }
                    else if (data.status === 'offline_msg') {
                        document.getElementById('scan-log-text').innerText = data.message;
                    }
                    else if (data.status === 'crawling') {
                        const targetLimit = isOnline ? 120 : 15;
                        document.getElementById('scan-elapsed').innerText = `${data.elapsed.toFixed(1)}s / ${targetLimit}s`;
                        document.getElementById('scan-messages').innerText = data.msg_count;
                        document.getElementById('scan-idr').innerText = `${data.mpm.toFixed(1)} MPM / IDR: ${data.idr.toFixed(3)}`;
                        
                        idrHistory.push(data.idr);
                        if (canvas && isOnline) {
                            drawLiveIDRHeartline(canvas, idrHistory);
                        }
                        
                        // Rotate themed logs periodically
                        const logs = AGENT_DIAGNOSTIC_REGISTRY.matchmaker.logs;
                        const phaseIndex = Math.floor(data.elapsed / 10) % logs.length;
                        document.getElementById('scan-log-text').innerText = `[Vibe Scout] ${logs[phaseIndex]}`;
                    }
                    else if (data.status === 'generating_start') {
                        document.getElementById('scan-status-badge').innerText = 'GENERATING';
                        document.getElementById('scan-status-badge').style.background = 'var(--accent-pink)';
                        document.getElementById('scan-log-text').innerText = '[Memetic Bridger] Uplink established. Stream-writing recommendation cards...';
                        
                        // Create streaming output container below telemetry
                        const streamDiv = document.createElement('div');
                        streamDiv.id = 'streaming-cards-container';
                        streamDiv.style.marginTop = '1rem';
                        streamDiv.style.borderTop = '1px dashed rgba(255,255,255,0.08)';
                        streamDiv.style.paddingTop = '0.75rem';
                        streamDiv.innerHTML = `
                            <div style="font-size: 0.65rem; color: var(--accent-pink); font-family: 'Press Start 2P'; margin-bottom: 0.4rem; letter-spacing: 0.05em; text-align: left;">[ ALLIANCE ARCS CRAWL ]</div>
                            <pre id="typing-pre" style="white-space: pre-wrap; font-family: 'Share Tech Mono', monospace; font-size: 0.68rem; color: var(--accent-green); background: rgba(0,0,0,0.3); padding: 0.45rem; border: 1px solid rgba(255,255,255,0.04); max-height: 120px; overflow-y: auto; text-align: left; margin: 0;"></pre>
                        `;
                        resultsEl.querySelector('.agent-diagnostic-loader').appendChild(streamDiv);
                    }
                    else if (data.status === 'generating') {
                        recommendationBuffer += data.chunk;
                        const pre = document.getElementById('typing-pre');
                        if (pre) {
                            pre.innerText = recommendationBuffer;
                            pre.scrollTop = pre.scrollHeight;
                        }
                    }
                    else if (data.status === 'done') {
                        closeSSE();
                        cleanUpMatchmakerBtn();
                        
                        try {
                            const data = JSON.parse(recommendationBuffer);
                            renderFinalMatchmakerCards(data, resultsEl, recommendationBuffer);
                        } catch (parseErr) {
                            console.error("Failed to parse recommendations JSON buffer:", parseErr);
                            resultsEl.innerHTML = `<p style="color: var(--accent-pink); font-size: 0.75rem; text-align: center;">Error rendering matches.</p>`;
                        }
                    }
                    else if (data.status === 'error') {
                        closeSSE();
                        cleanUpMatchmakerBtn();
                        resultsEl.innerHTML = `<p style="color: var(--accent-pink); font-size: 0.75rem; text-align: center;">Matchmaker error: ${data.message}</p>`;
                    }
                } catch (err) {
                    console.error("SSE parse error:", err);
                }
            };
            
            evtSource.onerror = function(err) {
                console.error("SSE connection lost:", err);
                closeSSE();
                cleanUpMatchmakerBtn();
                resultsEl.innerHTML = `<p style="color: var(--accent-pink); font-size: 0.75rem; text-align: center;">Matchmaker connection lost.</p>`;
            };
        }

        function findTribeForMember(handle) {
            if (!starmapData || !handle) return null;
            const cleanHandle = handle.replace(/^@/, '').toLowerCase().trim();
            
            if (starmapData.clusters) {
                for (const [tribeId, tribeInfo] of Object.entries(starmapData.clusters)) {
                    const members = tribeInfo.members || [];
                    const matched = members.find(m => m.handle.toLowerCase() === cleanHandle);
                    if (matched) {
                        return {
                            label: tribeInfo.label,
                            color: tribeInfo.color,
                            description: tribeInfo.description,
                            display_name: matched.display_name
                        };
                    }
                }
            }
            if (starmapData.galaxy && starmapData.galaxy.tribes) {
                for (const tribe of starmapData.galaxy.tribes) {
                    if (tribe.top_bellwether && tribe.top_bellwether.toLowerCase() === cleanHandle) {
                        return {
                            label: tribe.label,
                            color: tribe.color,
                            description: tribe.description,
                            display_name: tribe.top_bellwether
                        };
                    }
                }
            }
            return null;
        }

        function renderFinalMatchmakerCards(data, resultsEl, rawBuffer = '') {
            if (data.alliance_arcs && data.alliance_arcs.length > 0) {
                const wellHandleRaw = data.closest_gravity_well || '';
                const cleanWellHandle = wellHandleRaw.replace(/^@+/, '').trim();
                const matchedTribe = findTribeForMember(cleanWellHandle);
                
                let tribeInfoHTML = '';
                if (matchedTribe) {
                    tribeInfoHTML = `
                        <div style="font-size: 0.72rem; color: var(--text-muted); margin-bottom: 0.8rem; font-family: 'Share Tech Mono'; text-align: left; padding: 0.2rem 0.5rem; border-left: 2px solid ${matchedTribe.color}; background: rgba(255, 255, 255, 0.01);">
                            Tribe: <strong style="color: ${matchedTribe.color};">${escapeHTML(matchedTribe.label)}</strong><br/>
                            Vibe Profile: <span style="font-style: italic; color: #cbd5e1;">"${escapeHTML(matchedTribe.description || 'A dynamic faction of streamers bound by similar chat rhythms.')}"</span>
                        </div>
                    `;
                }

                const displayCentroid = (matchedTribe && matchedTribe.display_name) || cleanWellHandle;

                let cardsHTML = `
                    <div style="font-size: 0.75rem; font-weight: bold; color: #fff; margin-bottom: 0.4rem; font-family: 'Share Tech Mono'; text-align: left;">
                        Tribe Centroid: <span style="color: var(--accent-cyan); cursor: pointer; text-decoration: underline;" onclick="openStreamerProfileDrawer('${escapeHTML(cleanWellHandle)}')">@${escapeHTML(displayCentroid || 'unknown')}</span>
                    </div>
                    ${tribeInfoHTML}
                `;
                
                if (data.alignment_breakdown) {
                    const ab = data.alignment_breakdown;
                    cardsHTML += `
                        <div style="background: rgba(0, 240, 255, 0.03); border: 1px solid rgba(0, 240, 255, 0.15); padding: 0.5rem 0.6rem; font-size: 0.7rem; color: #cbd5e1; margin-bottom: 0.8rem; font-family: 'Share Tech Mono'; text-align: left;">
                            <span style="font-family: 'Press Start 2P'; font-size: 0.52rem; color: var(--accent-cyan); display: block; margin-bottom: 0.35rem; letter-spacing: 0.05em;">[ METRIC ALIGNMENT BREAKDOWN ]</span>
                            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 0.25rem 0.5rem;">
                                <div>Time Alignment: <strong style="color: #fff;">${escapeHTML(ab.time_alignment || 'N/A')}</strong></div>
                                <div>Game Alignment: <strong style="color: #fff;">${escapeHTML(ab.game_alignment || 'N/A')}</strong></div>
                                <div>Vibe Alignment: <strong style="color: #fff;">${escapeHTML(ab.vibe_alignment || 'N/A')}</strong></div>
                                <div>Language: <strong style="color: #fff;">${escapeHTML(ab.language_alignment || 'N/A')}</strong></div>
                            </div>
                        </div>
                    `;
                }
                
                if (data.reasoning) {
                    cardsHTML += `
                        <div style="background: rgba(168, 85, 247, 0.05); border: 1px solid rgba(168, 85, 247, 0.2); padding: 0.6rem; font-size: 0.72rem; color: #cbd5e1; margin-bottom: 0.8rem; line-height: 1.35; font-family: 'Share Tech Mono'; text-align: left;">
                            <span style="font-family: 'Press Start 2P'; font-size: 0.52rem; color: #c084fc; display: block; margin-bottom: 0.35rem; letter-spacing: 0.05em;">[ MATCHMAKER COGNITIVE REASONING ]</span>
                            ${escapeHTML(data.reasoning)}
                        </div>
                    `;
                }
                
                cardsHTML += `<div id="matchmaker-carousel" style="display: flex; flex-direction: column; gap: 0.75rem;">`;
                
                data.alliance_arcs.forEach((arc, idx) => {
                    let playbookHTML = '';
                    if (arc.raid_playbook) {
                        const rp = arc.raid_playbook;
                        playbookHTML = `
                            <div style="margin-top: 0.6rem; margin-bottom: 0.6rem; border: 1px solid rgba(0, 240, 255, 0.2); background: rgba(0, 240, 255, 0.01); padding: 0.6rem; font-family: 'Share Tech Mono';">
                                <div style="display: flex; justify-content: space-between; align-items: center; border-bottom: 1px dashed rgba(0, 240, 255, 0.2); padding-bottom: 0.25rem; margin-bottom: 0.4rem;">
                                    <span style="font-family: 'Press Start 2P'; font-size: 0.52rem; color: var(--accent-cyan);">[ ⚔️ RAID PLAYBOOK ]</span>
                                    <span style="font-size: 0.65rem; color: var(--accent-green); font-weight: bold; background: rgba(34, 197, 94, 0.1); padding: 0.05rem 0.25rem;">${escapeHTML(rp.meta_vibe)}</span>
                                </div>
                                
                                <div style="margin-bottom: 0.45rem;">
                                    <span style="font-size: 0.65rem; color: var(--text-muted); text-transform: uppercase; display: block; margin-bottom: 0.15rem;">Group Copypasta (Copy to Chat)</span>
                                    <div style="background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.06); padding: 0.3rem; display: flex; align-items: center; gap: 0.35rem;">
                                        <input type="text" readonly value="${escapeHTML(rp.copypasta)}" style="flex: 1; background: transparent; border: none; color: #fff; font-size: 0.68rem; font-family: 'Share Tech Mono';" id="raid-copypasta-${idx}">
                                        <button class="btn" style="padding: 0.1rem 0.35rem; font-size: 0.58rem; border-radius: 0px !important; font-family: 'Share Tech Mono';" onclick="copyToClipboard('raid-copypasta-${idx}', this)">Copy</button>
                                    </div>
                                </div>
                                
                                <div style="display: flex; flex-direction: column; gap: 0.35rem; font-size: 0.7rem; color: #e2e8f0; line-height: 1.35;">
                                    <div><strong>💥 Opener:</strong> <em>"${escapeHTML(rp.opener)}"</em></div>
                                    <div><strong>🎥 Clip Challenge:</strong> ${escapeHTML(rp.clip_challenge)}</div>
                                    <div><strong>👋 Sign-Off:</strong> ${escapeHTML(rp.sign_off)}</div>
                                </div>
                                
                                ${rp.why_it_works ? `
                                <div style="margin-top: 0.45rem; padding-top: 0.35rem; border-top: 1px dashed rgba(255,255,255,0.08); font-size: 0.65rem; color: var(--text-muted);">
                                    <strong style="color: var(--accent-pink);">Why it works:</strong> ${escapeHTML(rp.why_it_works)}
                                </div>
                                ` : ''}
                            </div>
                        `;
                    }

                    cardsHTML += `
                        <div class="glass-card" style="margin-bottom: 0px; padding: 0.75rem; border-left: 3px solid var(--accent-pink); background: rgba(255,255,255,0.01); border-radius: 0px !important; text-align: left;">
                            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.35rem;">
                                <span style="font-weight: bold; color: var(--accent-pink); font-size: 0.8rem; font-family: 'Share Tech Mono';">${idx + 1}. ${escapeHTML(arc.arc_type)}</span>
                                <span style="font-size: 0.7rem; color: var(--accent-cyan); cursor: pointer; font-family: 'Share Tech Mono';" onclick="openStreamerProfileDrawer('${escapeHTML(arc.peer_handle)}')">🔗 @${escapeHTML(arc.peer_handle)}</span>
                            </div>
                            <p style="font-size: 0.72rem; color: #cbd5e1; margin-bottom: 0.5rem; line-height: 1.3; font-family: 'Share Tech Mono';">${escapeHTML(arc.story)}</p>
                            
                            ${arc.why_match ? `
                            <div style="margin-bottom: 0.5rem; font-size: 0.68rem; color: var(--text-muted); font-family: 'Share Tech Mono';">
                                <strong style="color: var(--accent-green);">Match Reason:</strong> ${escapeHTML(arc.why_match)}
                            </div>
                            ` : ''}
                            
                            ${playbookHTML}

                            <div style="background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.06); padding: 0.4rem; display: flex; align-items: center; gap: 0.4rem;">
                                <input type="text" readonly value="${escapeHTML(arc.raid_script)}" style="flex: 1; background: transparent; border: none; color: var(--accent-green); font-size: 0.65rem; font-family: 'Share Tech Mono';" id="raid-script-${idx}">
                                <button class="btn" style="padding: 0.15rem 0.4rem; font-size: 0.6rem; border-radius: 0px !important; font-family: 'Share Tech Mono';" onclick="copyRaidScript(${idx}, this)">Copy</button>
                            </div>
                        </div>
                    `;
                });
                
                cardsHTML += `</div>`;
                
                if (rawBuffer) {
                    cardsHTML += `
                        <details style="margin-top: 0.8rem; border-top: 1px dashed rgba(255,255,255,0.06); padding-top: 0.4rem;">
                            <summary style="font-size: 0.62rem; color: var(--text-muted); cursor: pointer; font-family: 'Press Start 2P'; letter-spacing: 0.05em; outline: none; list-style: none;">[ VIEW DIAGNOSTIC LOGS ]</summary>
                            <pre style="white-space: pre-wrap; font-family: 'Share Tech Mono', monospace; font-size: 0.65rem; color: var(--text-muted); background: rgba(0,0,0,0.25); padding: 0.4rem; border: 1px solid rgba(255,255,255,0.03); max-height: 120px; overflow-y: auto; margin-top: 0.4rem; text-align: left;">${escapeHTML(rawBuffer)}</pre>
                        </details>
                    `;
                }
                
                resultsEl.innerHTML = cardsHTML;
                
                if (typeof loadStarfieldData === 'function') {
                    loadStarfieldData();
                }
            } else {
                resultsEl.innerHTML = '<p style="color: var(--text-muted); font-size: 0.75rem; text-align: center;">No matches found. Ensure other streamers are profiled.</p>';
            }
        }
        
        function copyRaidScript(idx, btn) {
            const copyText = document.getElementById(`raid-script-${idx}`);
            if (copyText) {
                copyText.select();
                copyText.setSelectionRange(0, 99999);
                navigator.clipboard.writeText(copyText.value);
                btn.innerHTML = 'Copied!';
                setTimeout(() => { btn.innerHTML = 'Copy'; }, 2000);
            }
        }

        function copyToClipboard(id, btn) {
            const copyText = document.getElementById(id);
            if (copyText) {
                copyText.select();
                copyText.setSelectionRange(0, 99999);
                navigator.clipboard.writeText(copyText.value);
                btn.innerHTML = 'Copied!';
                setTimeout(() => { btn.innerHTML = 'Copy'; }, 2000);
            }
        }

        // Handle window resizing and redraw Star Map to prevent overruns
        window.addEventListener('resize', () => {
            const activeTab = document.querySelector('.tab-btn.active');
            if (activeTab && activeTab.textContent.toLowerCase().includes('star')) {
                if (starmapData) {
                    const backBtn = document.getElementById("starmap-back-btn");
                    if (backBtn && backBtn.style.display === "none") {
                        loadStarMap();
                    } else if (isNebulaActive && currentTribeId) {
                        renderNebulaView(currentTribeId);
                    } else if (currentTribeId) {
                        renderClusterView(currentTribeId);
                    } else {
                        loadStarMap();
                    }
                }
            }
        });
