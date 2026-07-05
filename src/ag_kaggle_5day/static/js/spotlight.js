        function checkKey() {
            let key = sessionStorage.getItem("gemini_api_key");
            if (!key) {
                const storedKey = localStorage.getItem("gemini_api_key");
                const expiry = localStorage.getItem("gemini_key_expiry");
                if (storedKey && expiry) {
                    if (Date.now() < parseInt(expiry)) {
                        key = storedKey;
                        sessionStorage.setItem("gemini_api_key", key);
                    } else {
                        localStorage.removeItem("gemini_api_key");
                        localStorage.removeItem("gemini_key_expiry");
                    }
                }
            }
            return key;
        }

        const AGENT_DIAGNOSTIC_REGISTRY = {
            expose: {
                agent: "Spotlight Research Agent",
                color: "var(--neon-magenta)",
                logs: [
                    "Infiltrating stream archive database...",
                    "Analyzing subscriber/viewer count trends...",
                    "Parsing chat transcription moments...",
                    "Resolving peer similarity alignment vectors...",
                    "Running Gemini spotlight expose model...",
                    "Generating strategic content recommendations..."
                ]
            }
        };

        let activeLoaderInterval = null;
        let activeLoaderAnimation = null;

        function renderAgentDiagnosticLoader(container, key, textLabel = "") {
            const config = AGENT_DIAGNOSTIC_REGISTRY[key] || { agent: "System", color: "var(--text-color)", logs: ["Loading..."] };
            const canvasId = `loader-canvas-${Math.floor(Math.random() * 100000)}`;
            const textId = `loader-text-${Math.floor(Math.random() * 100000)}`;
            
            container.innerHTML = `
                <div class="agent-diagnostic-loader" style="padding: 1.5rem; text-align: center; font-family: 'Share Tech Mono', monospace; border: 1px dashed rgba(255, 0, 127, 0.2); background: rgba(0,0,0,0.3); margin-top: 1rem;">
                    <div style="font-size: 0.85rem; font-weight: bold; color: ${config.color}; margin-bottom: 0.5rem; text-transform: uppercase; letter-spacing: 0.05em; font-family: 'Press Start 2P';">
                        📡 ${config.agent} Active
                    </div>
                    <canvas id="${canvasId}" width="400" height="60" style="width: 100%; max-width: 400px; height: 60px; margin: 0.8rem auto; display: block; border: 1px solid rgba(255, 0, 127, 0.1); background: rgba(0,0,0,0.5);"></canvas>
                    <div id="${textId}" style="font-size: 0.85rem; color: var(--neon-yellow); min-height: 1.3rem; margin-top: 0.5rem; line-height: 1.3;">
                        [ \\ ] ${config.logs[0]}
                    </div>
                    ${textLabel ? `<div style="font-size: 0.75rem; color: #887a9c; margin-top: 0.75rem; border-top: 1px dashed rgba(255,255,255,0.05); padding-top: 0.5rem;">${textLabel}</div>` : ''}
                </div>
            `;
            
            const canvas = document.getElementById(canvasId);
            if (!canvas) return;
            const ctx = canvas.getContext('2d');
            let phase = 0;
            
            function drawWave() {
                if (!document.body.contains(canvas)) {
                    cancelAnimationFrame(activeLoaderAnimation);
                    return;
                }
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                
                // Draw grid lines
                ctx.strokeStyle = 'rgba(255, 0, 127, 0.02)';
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
                ctx.shadowBlur = 4;
                ctx.lineWidth = 1.5;
                ctx.beginPath();
                
                for (let x = 0; x < canvas.width; x++) {
                    const y = canvas.height / 2 + 
                              Math.sin(x * 0.05 + phase) * 10 * Math.sin(x * 0.01) + 
                              Math.cos(x * 0.12 - phase * 0.7) * 3 * Math.random();
                    if (x === 0) {
                        ctx.moveTo(x, y);
                    } else {
                        ctx.lineTo(x, y);
                    }
                }
                ctx.stroke();
                ctx.shadowBlur = 0;
                
                phase += 0.12;
                activeLoaderAnimation = requestAnimationFrame(drawWave);
            }
            drawWave();
            
            let logIndex = 0;
            const cursors = ['\\', '|', '/', '-'];
            let cursorIdx = 0;
            
            if (activeLoaderInterval) clearInterval(activeLoaderInterval);
            activeLoaderInterval = setInterval(() => {
                const textEl = document.getElementById(textId);
                if (!textEl) {
                    clearInterval(activeLoaderInterval);
                    return;
                }
                
                // Rotate spinner faster than text logs
                cursorIdx = (cursorIdx + 1) % cursors.length;
                
                // Only update log text every 2.5s (which is every 10 updates if interval is 250ms)
                if (cursorIdx === 0) {
                    logIndex = (logIndex + 1) % config.logs.length;
                }
                
                textEl.innerHTML = `[ ${cursors[cursorIdx]} ] ${config.logs[logIndex]}`;
            }, 250);
        }

        function showRetroLoader(handle) {
            const input = document.getElementById('streamer-search');
            const button = document.getElementById('btn-generate');
            const status = document.getElementById('streamer-generating-status');
            const body = document.getElementById('spotlight-body');
            const titleEl = document.getElementById('spotlight-title');
            const metaEl = document.getElementById('spotlight-meta');

            if (input) {
                input.disabled = true;
                input.classList.add('generating-pulse');
            }
            if (button) {
                button.disabled = true;
                button.style.opacity = '0.5';
                button.textContent = 'GO...';
            }
            if (status) {
                status.textContent = `Scraping & generating profile for streamer '${handle}'...`;
                status.style.display = 'block';
            }
            
            // Transform the main panel body into the retro diagnostic scan terminal
            if (titleEl) titleEl.textContent = `Scanning: ${handle.toUpperCase()}`;
            if (metaEl) metaEl.innerHTML = `Establishing satellite downlink...`;
            if (body) {
                renderAgentDiagnosticLoader(body, 'expose', `Targeting channel details, stream history, and live chat telemetry for @${handle}`);
            }
        }

        function hideRetroLoader() {
            const input = document.getElementById('streamer-search');
            const button = document.getElementById('btn-generate');
            const status = document.getElementById('streamer-generating-status');
            if (input) {
                input.disabled = false;
                input.classList.remove('generating-pulse');
            }
            if (button) {
                button.disabled = false;
                button.style.opacity = '1';
                button.textContent = 'GO';
            }
            if (status) {
                status.style.display = 'none';
            }
            
            if (activeLoaderInterval) {
                clearInterval(activeLoaderInterval);
                activeLoaderInterval = null;
            }
            if (activeLoaderAnimation) {
                cancelAnimationFrame(activeLoaderAnimation);
                activeLoaderAnimation = null;
            }
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
                    btn.className = 'history-card';
                    btn.style.display = 'block';
                    btn.style.textAlign = 'left';
                    btn.style.width = '100%';
                    btn.style.fontSize = '0.85rem';
                    btn.style.padding = '10px';
                    btn.style.background = 'rgba(0, 240, 255, 0.05)';
                    btn.style.border = '1px solid rgba(0, 240, 255, 0.2)';
                    btn.style.color = '#fff';
                    btn.style.cursor = 'pointer';
                    btn.style.fontFamily = "'Share Tech Mono', monospace";
                    btn.textContent = `🔍 ${item.streamer_handle.toUpperCase()}`;
                    btn.onclick = () => {
                        document.getElementById('streamer-search').value = item.streamer_handle;
                        generateMediumForm(item.streamer_handle);
                    };
                    list.appendChild(btn);
                });
            } else {
                section.style.display = 'none';
            }
        }

        document.addEventListener("DOMContentLoaded", () => {
            if (window.self !== window.top) {
                document.querySelectorAll(".back-link").forEach(link => {
                    link.style.display = "none";
                });
            }

            const urlParams = new URLSearchParams(window.location.search);
            let handleParam = urlParams.get('handle');

            // Parse path parameters /spotlight/{handle} or /expose/{handle}
            const pathParts = window.location.pathname.split('/');
            if (!handleParam && pathParts.length > 2) {
                const section = pathParts[1];
                if (section === 'spotlight' || section === 'expose') {
                    let part = decodeURIComponent(pathParts[2]);
                    if (part.startsWith('handle=')) {
                        part = part.substring(7);
                    }
                    if (part && part.toLowerCase() !== 'latest') {
                        handleParam = part;
                    }
                }
            }

            if (handleParam) {
                document.getElementById("streamer-search").value = handleParam;
                
                const titleEl = document.getElementById("spotlight-title");
                const hasPreRenderedContent = titleEl && 
                    titleEl.textContent !== "Loading Spotlight Expose..." && 
                    !titleEl.textContent.startsWith("Error:") &&
                    titleEl.textContent !== "Daily Expose Archive Empty";
                
                if (!hasPreRenderedContent) {
                    generateMediumForm(handleParam);
                }
            } else {
                loadStreamerOfDay();
            }
            loadHistory();
            setupAutocomplete();
            updateSessionResearchList();

            document.getElementById("btn-generate").addEventListener("click", () => {
                const handle = document.getElementById("streamer-search").value.trim();
                if (handle) {
                    history.pushState({ handle: handle }, "", `/spotlight?handle=${handle}`);
                    generateMediumForm(handle);
                }
            });

            // Intercept clicks on links inside spotlight-body
            document.getElementById("spotlight-body").addEventListener("click", (e) => {
                const a = e.target.closest("a");
                if (a) {
                    const href = a.getAttribute("href");
                    const isSpotlightLink = href && (href.startsWith("/spotlight?handle=") || href.includes("/spotlight/"));
                    const isExposeLink = href && (href.startsWith("/expose?handle=") || href.includes("/expose/"));
                    
                    if (isSpotlightLink || isExposeLink) {
                        e.preventDefault();
                        const url = new URL(a.href, window.location.href);
                        let handle = url.searchParams.get("handle");
                        if (!handle) {
                            const parts = url.pathname.split('/');
                            handle = parts[parts.length - 1];
                        }
                        if (handle) {
                            if (window.parent && typeof window.parent.openStreamerProfileDrawer === "function") {
                                // If inside the dashboard iframe, open the streamer profile drawer on the parent page
                                window.parent.openStreamerProfileDrawer(handle);
                                // Keep the spotlight/expose cabinet open so reader does not lose context
                            } else {
                                // Standalone fallback
                                history.pushState({ handle: handle }, "", a.href);
                                document.getElementById("streamer-search").value = handle;
                                generateMediumForm(handle);
                            }
                        }
                    }
                }
            });

            // Handle popstate for back/forward navigation
            window.addEventListener("popstate", (event) => {
                const urlParams = new URLSearchParams(window.location.search);
                const handleParam = urlParams.get('handle');
                if (handleParam) {
                    document.getElementById("streamer-search").value = handleParam;
                    generateMediumForm(handleParam);
                } else {
                    document.getElementById("streamer-search").value = "";
                    const header = document.getElementById("spotlight-header");
                    if (header) header.textContent = "STREAMER OF THE DAY";
                    loadStreamerOfDay();
                }
            });
        });

        async function loadStreamerOfDay() {
            try {
                const res = await fetch("/api/articles/expose/latest");
                if (res.ok) {
                    const data = await res.json();
                    if (data && data.content) {
                        const header = document.getElementById("spotlight-header");
                        if (header) header.textContent = "STREAMER OF THE DAY";
                        document.getElementById("spotlight-title").textContent = data.title || `Spotlight: ${data.streamer_handle}`;
                        document.getElementById("spotlight-meta").innerHTML = `Published: ${new Date(data.timestamp * 1000).toLocaleString()} | Streamer: <a href="https://twitch.tv/${data.streamer_handle}" target="_blank" style="color: var(--neon-blue); text-decoration: underline; text-shadow: var(--border-glow);">${data.streamer_handle}</a>`;
                        document.getElementById("spotlight-body").innerHTML = data.content;
                        renderArticleLinks(data.associated_links || data.links, data.streamer_handle);
                        return;
                    }
                }
                showFallbackSpotlight();
            } catch (e) {
                showFallbackSpotlight();
            }
        }

        function showFallbackSpotlight() {
            document.getElementById("spotlight-title").textContent = "Daily Expose Archive Empty";
            document.getElementById("spotlight-body").innerHTML = "<p>The daily selection cron job has not generated today's expose yet. Check back later or manually trigger from the dashboard.</p>";
            renderArticleLinks(null);
        }

        async function loadHistory() {
            try {
                const res = await fetch("/api/articles/expose/history");
                if (res.ok) {
                    const list = await res.json();
                    const container = document.getElementById("history-content");
                    if (list && list.length > 0) {
                        container.innerHTML = "";
                        list.forEach(item => {
                            const card = document.createElement("div");
                            card.className = "history-card";
                            const typeLabel = item.type === "medium-form" ? "[PROFILE]" : "[EXPOSE]";
                            card.innerHTML = `
                                <h4>${typeLabel} ${item.title || item.streamer_handle}</h4>
                                <p>Streamer: ${item.streamer_handle} | Date: ${new Date(item.timestamp * 1000).toLocaleDateString()}</p>
                            `;
                            card.onclick = () => {
                                const header = document.getElementById("spotlight-header");
                                if (header) {
                                    header.textContent = item.type === "medium-form" ? "COMMUNITY PROFILE" : "STREAMER OF THE DAY";
                                }
                                document.getElementById("spotlight-title").textContent = item.title || `Spotlight: ${item.streamer_handle}`;
                                document.getElementById("spotlight-meta").innerHTML = `Published: ${new Date(item.timestamp * 1000).toLocaleString()} | Streamer: <a href="https://twitch.tv/${item.streamer_handle}" target="_blank" style="color: var(--neon-blue); text-decoration: underline; text-shadow: var(--border-glow);">${item.streamer_handle}</a>`;
                                document.getElementById("spotlight-body").innerHTML = item.content;
                                renderArticleLinks(item.associated_links || item.links, item.streamer_handle);
                            };
                            container.appendChild(card);
                        });
                    }
                }
            } catch (e) {}
        }

        function renderArticleLinks(links, handle) {
            const container = document.getElementById("spotlight-links");
            if (!container) return;
            container.innerHTML = "";

            let effLinks = links || {};
            if (!effLinks.twitch && handle) {
                effLinks.twitch = `https://twitch.tv/${handle}`;
            }

            let hasLinks = false;
            const types = ["twitch", "youtube", "store", "twitter"];
            types.forEach(type => {
                const url = effLinks[type];
                if (url && typeof url === "string" && url.trim().startsWith("http")) {
                    hasLinks = true;
                    const badge = document.createElement("a");
                    badge.href = url.trim();
                    badge.target = "_blank";
                    badge.className = `social-badge badge-${type}`;
                    badge.textContent = `[${type.toUpperCase()}]`;
                    container.appendChild(badge);
                }
            });

            if (hasLinks) {
                container.style.display = "flex";
            } else {
                container.style.display = "none";
            }
        }

        async function setupAutocomplete() {
            const input = document.getElementById("streamer-search");
            const listContainer = document.getElementById("autocomplete-list");

            input.addEventListener("input", async () => {
                const val = input.value.trim();
                if (!val) {
                    listContainer.style.display = "none";
                    return;
                }

                try {
                    const res = await fetch(`/api/streamers/autocomplete?q=${encodeURIComponent(val)}`);
                    if (res.ok) {
                        const items = await res.json();
                        if (items && items.length > 0) {
                            listContainer.innerHTML = "";
                            listContainer.style.display = "block";
                            items.forEach(item => {
                                const div = document.createElement("div");
                                const isObj = typeof item === 'object' && item !== null;
                                const displayName = isObj ? item.display_name : item;
                                const handle = isObj ? item.handle : item;
                                const platform = isObj ? item.platform : '';

                                const span = document.createElement("span");
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

                                div.onclick = () => {
                                    input.value = handle;
                                    listContainer.style.display = "none";
                                    generateMediumForm(handle);
                                };
                                listContainer.appendChild(div);
                            });
                        } else {
                            listContainer.style.display = "none";
                        }
                    }
                } catch (e) {
                    listContainer.style.display = "none";
                }
            });

            document.addEventListener("click", (e) => {
                if (e.target !== input) {
                    listContainer.style.display = "none";
                }
            });
        }

        async function generateMediumForm(handle) {
            const body = document.getElementById("spotlight-body");
            const titleEl = document.getElementById("spotlight-title");
            const metaEl = document.getElementById("spotlight-meta");
            
            showRetroLoader(handle);

            const key = checkKey() || '';
            const selectedModel = localStorage.getItem('gemini_model_analysis') || '';

            try {
                const res = await fetch("/api/articles/medium-form", {
                    method: "POST",
                    headers: { 
                        "Content-Type": "application/json",
                        "x-gemini-api-key": key
                    },
                    body: JSON.stringify({ 
                        streamer_handle: handle,
                        model: selectedModel
                    })
                });
                
                hideRetroLoader();
                
                if (res.ok) {
                    const data = await res.json();
                    const header = document.getElementById("spotlight-header");
                    if (header) header.textContent = "COMMUNITY PROFILE";
                    titleEl.textContent = data.title || `Spotlight: ${handle}`;
                    metaEl.innerHTML = `Generated Profile | Streamer: <a href="https://twitch.tv/${handle}" target="_blank" style="color: var(--neon-blue); text-decoration: underline; text-shadow: var(--border-glow);">${handle}</a>`;
                    body.innerHTML = data.content;
                    renderArticleLinks(data.associated_links || data.links, handle);

                    // Save to sessionStorage
                    let sessionData = [];
                    try {
                        sessionData = JSON.parse(sessionStorage.getItem('my_generated_streamers') || '[]');
                    } catch (e) {}
                    if (!sessionData.some(item => item.streamer_handle.toLowerCase() === handle.toLowerCase())) {
                        sessionData.push({ streamer_handle: handle.toLowerCase() });
                        sessionStorage.setItem('my_generated_streamers', JSON.stringify(sessionData));
                        updateSessionResearchList();
                    }
                } else {
                    const errData = await res.json();
                    const errMsg = errData.detail || 'Failed to generate profile.';
                    titleEl.textContent = `Error: ${handle}`;
                    body.innerHTML = `<p style="color: var(--neon-magenta)">${errMsg}</p>`;
                    renderArticleLinks(null);
                }
            } catch (e) {
                hideRetroLoader();
                titleEl.textContent = `Error: ${handle}`;
                body.innerHTML = `<p style="color: var(--neon-magenta)">Error: ${e}</p>`;
                renderArticleLinks(null);
            }
        }
