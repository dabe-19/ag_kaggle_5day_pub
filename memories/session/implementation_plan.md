# Implementation Plan - Handle Query Parameter in Streamer Spotlight

This plan addresses the issue where streamer name tags (peer spotlight links) in the Streamer Spotlight article do not navigate to the linked streamer's profile. Instead, clicking the link changes the URL to `/spotlight?handle=peer_handle` but reloads the page with the default Streamer of the Day article. We will parse the `handle` query parameter on frontend page load, handle it dynamically via `generateMediumForm`, and intercept body clicks to offer seamless, fast transitions.

## User Review Required
- **Interactive Transitions**: Navigation between different streamer profiles will now be dynamic using HTML5 History API (`history.pushState`), avoiding unnecessary page reloads and providing a premium feel.
- **Gemini Key Dependency**: Dynamic generation of a new profile via the backend API still requires a personal Gemini API key if the article is not already cached. Cached profiles do not require a key.

## Open Questions
- None.

## Proposed Changes

### Component: Frontend Layer

#### [MODIFY] [spotlight.html](file:///home/wsl-ops/projects/ag_kaggle_5day/src/ag_kaggle_5day/spotlight.html)
- **Check URL Parameter on DOMContentLoaded**:
  - Parse `handle` query parameter using `URLSearchParams`.
  - If a handle is present, populate the search input box and call `generateMediumForm(handle)`.
  - Otherwise, call `loadStreamerOfDay()` (default behavior).
- **Intercept Body Links**:
  - Attach a click listener to the `#spotlight-body` container.
  - Detect clicks on anchor tags pointing to `/spotlight?handle=...`.
  - Intercept the navigation (`event.preventDefault()`), push the state via `history.pushState`, and fetch/generate the target streamer profile dynamically.
- **Listen to popstate**:
  - Add a `popstate` event listener to window to correctly load the appropriate streamer's profile or default expose when the user clicks the browser's back/forward buttons.

---

## Scope Boundaries
- This change is strictly frontend in `spotlight.html`. No changes are made to the backend routes in `app.py` or the prompt layouts in the advisor agent workflows.

---

## Touched Layers (Handoff Routing)
- **core-specialist**: no
- **scraper-agent-specialist**: no
- **frontend-specialist**: yes — Parse `handle` URL parameter, handle `popstate`, and intercept click events on `#spotlight-body` inside `spotlight.html`.

## Tooling Layer (Provisioning)
- **Tooling**: no

## Functional Verification
- **Verification**: yes — Verify that the application starts, and the unit tests run and pass.

## Security
- **Security**: no — Standard frontend routing and click delegation.

## Style
- **Style**: no

## Verification Plan

### Automated Tests
- Run `poetry run pytest` to ensure the overall application routes and cache features remain unaffected.

### Manual Verification
- Start the server using `poetry run start`.
- Navigate to the Spotlight page.
- Locate a peer link (or manually visit `/spotlight?handle=iti63` or another active streamer).
- Verify the correct streamer's profile or loader is shown.
- Click a peer link within the text and verify it transitions instantly, updating the URL and loading the profile.
- Click the browser's back button and verify it transitions back to the previous profile/page.
