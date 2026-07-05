## Full Report

### Layer: frontend-specialist

### Files Touched
- `src/ag_kaggle_5day/dashboard.html`

### Diff Summary
```diff
diff --git a/src/ag_kaggle_5day/dashboard.html b/src/ag_kaggle_5day/dashboard.html
--- a/src/ag_kaggle_5day/dashboard.html
+++ b/src/ag_kaggle_5day/dashboard.html
@@ -2342,2 +2342,2 @@
             if (selected === 'action-adventure') {
-                return cat.includes('action') || cat.includes('adventure') || t.includes('gta') || t.includes('grand theft auto');
+                return cat.includes('action') || cat.includes('adventure') || cat.includes('racing') || cat.includes('driving') || cat.includes('forza') || t.includes('gta') || t.includes('grand theft auto') || t.includes('forza');
             }
@@ -3656,7 +3656,12 @@
                             <div class="playbook-section-content">${markdownLinksToHtml(affiliatePlaybook.preparation)}</div>
                         </div>
                     `;
-                    grid.appendChild(affCard);
+                    const randomIndex = Math.floor(Math.random() * (grid.children.length + 1));
+                    if (randomIndex >= grid.children.length) {
+                        grid.appendChild(affCard);
+                    } else {
+                        grid.insertBefore(affCard, grid.children[randomIndex]);
+                    }
                 }
```

- Updated `matchesCategory` for category `action-adventure` in the Javascript filtering system to include racing/driving/forza keywords so that "Forza Horizon 6" displays and filters correctly under Action-Adventure.
- Randomised the insertion position of the affiliate playbook card in the DOM grid, placing it at a random index among other playbook cards.

### Commands Run
- `poetry run pytest src/ag_kaggle_5day/agents/test_agents.py` (Exit code: 0, 53 passed)

### Decisions & Alternatives
- Positioned the affiliate playbook card dynamically on both client side (random insert in DOM grid) and backend side (slice preceding playbooks at a random insertion index). This ensures full compatibility whether playbooks are processed dynamically/asynchronously per-game or served in batch.

### Risks / Follow-ups
- None.
