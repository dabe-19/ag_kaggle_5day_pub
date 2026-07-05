## Full Report

### Layer: frontend-specialist

### Files Touched
- `src/ag_kaggle_5day/dashboard.html`

### Diff Summary
```diff
diff --git a/src/ag_kaggle_5day/dashboard.html b/src/ag_kaggle_5day/dashboard.html
--- a/src/ag_kaggle_5day/dashboard.html
+++ b/src/ag_kaggle_5day/dashboard.html
@@ -455,5 +455,6 @@
             display: flex;
             flex-direction: column;
             transform: translateX(100%);
+            visibility: hidden;
-            transition: transform 0.35s cubic-bezier(0.1, 0.9, 0.2, 1);
+            transition: transform 0.35s cubic-bezier(0.1, 0.9, 0.2, 1), visibility 0.35s cubic-bezier(0.1, 0.9, 0.2, 1);
             padding: 1.25rem;
             box-sizing: border-box;
         }
@@ -462,5 +463,6 @@
         .arcade-panel.open {
             transform: translateX(0);
+            visibility: visible;
         }
@@ -1804,4 +1805,4 @@
-        function setButtonCooldown(btn, defaultText, durationMs = 5000) {
-            btn.innerHTML = `Cooldown (${Math.round(durationMs / 1000)}s)`;
+        function setButtonCooldown(btn, defaultText, durationMs = 10000) {
+            btn.innerHTML = `Cooldown (${Math.round(durationMs / 1000)} sec)`;
@@ -1949,15 +1950,21 @@
         function reparentChatTo(targetMountId, inputMountId) {
             const container = document.getElementById('chat-content-container');
             if (!container) return;
-
-            // Save scroll position
-            const msgs = container.querySelector('#chat-messages');
-            const scrollPos = msgs ? msgs.scrollTop : 0;
+
+            // Find elements globally since they might be split and outside container
+            const messagesEl = document.getElementById('chat-messages');
+            const inputWrapper = document.querySelector('.chat-input-wrapper');
+            const suggestions = document.querySelector('.suggestions');
+
+            // Save scroll position
+            const scrollPos = messagesEl ? messagesEl.scrollTop : 0;
 
             if (inputMountId) {
                 // Arcade mode: split messages and input into separate mounts
-                const messagesEl = container.querySelector('#chat-messages');
-                const inputWrapper = container.querySelector('.chat-input-wrapper');
-                const suggestions = container.querySelector('.suggestions');
-
                 const targetMount = document.getElementById(targetMountId);
                 const inputMount = document.getElementById(inputMountId);
                 if (targetMount && messagesEl) {
@@ -1971,6 +1978,10 @@
                 }
             } else {
                 // Panel mode: everything in one mount
+                if (messagesEl) container.appendChild(messagesEl);
+                if (inputWrapper) container.appendChild(inputWrapper);
+                if (suggestions) container.appendChild(suggestions);
+
                 const targetMount = document.getElementById(targetMountId);
                 if (targetMount) {
                     targetMount.innerHTML = '';
@@ -1978,7 +1989,7 @@
             }
 
             // Restore scroll
-            if (msgs) msgs.scrollTop = scrollPos;
+            if (messagesEl) messagesEl.scrollTop = scrollPos;
         }
```

### Commands Run
- `poetry run pytest` -> exit 0 (70 passed, 8 warnings)

### Decisions & Alternatives
- Updated `.arcade-panel` base class with `visibility: hidden;` and transitioned it alongside `transform`. Set `visibility: visible;` on `.arcade-panel.open`. This prevents layout overflow and browser screen-reader visibility bugs when closed.
- Updated `setButtonCooldown` default duration to 10000ms (10 seconds) to match backend rate limits, and formatted the innerHTML to display `sec` (e.g. `Cooldown (10 sec)`) to avoid the retro-font `s` character rendering as `5` (which was causing "10s" or "5s" to look like "105" or "55").
- Overhauled `reparentChatTo` to look up the split elements (`#chat-messages`, `.chat-input-wrapper`, and `.suggestions`) globally. When transitioning back to panel mode, they are appended back to `#chat-content-container` first. This solves the disappearing chat elements bug on subsequent toggles or expands.

### Risks / Follow-ups
- None.
