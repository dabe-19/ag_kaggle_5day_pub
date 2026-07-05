import datetime
import logging
import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse

_CURR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TEMPLATES_DIR = os.path.join(_CURR_DIR, "templates")

DASHBOARD_HTML_PATH = os.path.join(_TEMPLATES_DIR, "dashboard.html")
with open(DASHBOARD_HTML_PATH, "r", encoding="utf-8") as f:
    DASHBOARD_HTML = f.read()

SPOTLIGHT_HTML_PATH = os.path.join(_TEMPLATES_DIR, "spotlight.html")
with open(SPOTLIGHT_HTML_PATH, "r", encoding="utf-8") as f:
    SPOTLIGHT_HTML = f.read()

logger = logging.getLogger("streamer_advisor.routes.pages")
router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def get_dashboard():
    return DASHBOARD_HTML


@router.get("/spotlight", response_class=HTMLResponse)
def get_spotlight():
    return SPOTLIGHT_HTML


@router.get("/spotlight/{handle}", response_class=HTMLResponse)
async def get_standalone_spotlight(handle: str):
    """
    Renders a standalone, SEO-friendly Spotlight report for a streamer handle.
    Pre-renders Firestore content statically if it exists.
    """
    h = handle.strip().lower()

    # Check if a link exists to get canonical details
    linked_twitch = h
    linked_youtube = None
    display_name = handle
    try:
        from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

        link_info = resolve_streamer_link(h)
        if link_info:
            linked_twitch = link_info.get("twitch_handle") or h
            linked_youtube = link_info.get("youtube_channel_id")
            display_name = link_info.get("display_name") or handle
    except Exception:
        pass

    # Try to fetch article from Firestore spotlight_medium_articles
    article = None
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        fs = get_firestore_client()
        if fs:
            doc = (
                fs.collection("spotlight_medium_articles")
                .document(linked_twitch.lower())
                .get()
            )
            if doc.exists:
                article = doc.to_dict()
            elif linked_youtube:
                doc = (
                    fs.collection("spotlight_medium_articles")
                    .document(linked_youtube.lower())
                    .get()
                )
                if doc.exists:
                    article = doc.to_dict()
    except Exception as e:
        logger.warning(f"Failed to fetch spotlight article for standalone page: {e}")

    html_str = SPOTLIGHT_HTML

    if article:
        title = article.get("title") or f"Spotlight: {display_name}"
        content = article.get("content") or ""
        ts = article.get("timestamp", 0.0)
        dt_str = (
            datetime.datetime.fromtimestamp(ts).strftime("%B %d, %Y")
            if ts
            else "Recent"
        )
        meta_str = f"WOR-ACLE Spotlight Dossier | Generated on {dt_str}"

        # Replace placeholders for SEO and pre-rendered content
        html_str = html_str.replace(
            "<title>WOR-ACLE: Streamer Spotlight Hub</title>",
            f"<title>WOR-ACLE Spotlight: {title}</title>",
        )
        html_str = html_str.replace(
            '<meta name="description" content="WOR-ACLE: Streamer of the Day '
            "Exposes and Community Profiles. Read in-depth analyses of top "
            'live content creators.">',
            f'<meta name="description" content="Read WOR-ACLE\'s in-depth '
            f'Streamer Spotlight report for {display_name}.">',
        )
        html_str = html_str.replace(
            'id="spotlight-title">Loading Spotlight Expose...</div>',
            f'id="spotlight-title">{title}</div>',
        )
        html_str = html_str.replace(
            'id="spotlight-meta">WOR-ACLE Daily Chronicle</div>',
            f'id="spotlight-meta">{meta_str}</div>',
        )

        # Replace the loading paragraph inside the body
        old_body = (
            "<p>Fetching the latest 24-hour long-form expose from the database...</p>"
        )
        html_str = html_str.replace(old_body, content)

        # Pre-populate search input
        html_str = html_str.replace(
            'id="streamer-search"', f'id="streamer-search" value="{display_name}"'
        )

        # Also render links if present
        links = article.get("associated_links") or {}
        if links:
            links_html = ""
            for platform, url in links.items():
                if url:
                    badge_cls = f"badge-{platform.lower()}"
                    links_html += (
                        f'<a href="{url}" target="_blank" '
                        f'class="social-badge {badge_cls}">'
                        f"{platform.upper()}</a>"
                    )
            if links_html:
                html_str = html_str.replace(
                    '<div id="spotlight-links" style="display: none; '
                    'gap: 10px; margin: 15px 0; flex-wrap: wrap;"></div>',
                    f'<div id="spotlight-links" style="display: flex; '
                    f"gap: 10px; margin: 15px 0; flex-wrap: "
                    f'wrap;">{links_html}</div>',
                )
    else:
        title = f"Dossier Missing: {display_name}"
        meta_str = "No cached dossier found"
        missing_content = (
            '<div style="text-align: center; padding: 2rem; '
            "border: 1px dashed rgba(255, 0, 127, 0.3); "
            'background: rgba(255, 0, 127, 0.02);">'
            '<p style="font-size: 1.2rem; color: var(--neon-yellow); '
            f'margin-bottom: 1.5rem;">⚠️ No Spotlight Dossier has '
            f"been generated for {display_name} yet.</p>"
            '<p style="font-size: 0.95rem; color: #887a9c; '
            'margin-bottom: 2rem;">A personal Gemini API Key is '
            "required to run real-time analysis and compile "
            "streamer data.</p>"
            '<button id="btn-trigger-generation" style="background-color: '
            "var(--neon-magenta); color: #000; font-family: 'Press Start "
            "2P', cursive; font-size: 0.85rem; border: none; padding: "
            '12px 24px; cursor: pointer; font-weight: bold;">⚡ '
            "GENERATE DOSSIER</button>"
            "</div>"
            "<script>"
            'document.addEventListener("DOMContentLoaded", () => {'
            'const btn = document.getElementById("btn-trigger-generation");'
            "if (btn) {"
            'btn.addEventListener("click", async () => {'
            "btn.disabled = true;"
            'btn.textContent = "⚡ GENERATING...";'
            "try {"
            "const searchModel = "
            'localStorage.getItem("gemini_model_search") || '
            '"gemma-4-31b-it";'
            'const res = await fetch("/api/articles/medium-form", {'
            'method: "POST",'
            'headers: {"Content-Type": "application/json"},'
            "body: JSON.stringify({"
            f'streamer_handle: "{display_name}",'
            "model: searchModel"
            "})"
            "});"
            "if (res.ok) {"
            "window.location.reload();"
            "} else {"
            "const err = await res.text();"
            'alert("Failed to generate dossier: " + err);'
            "btn.disabled = false;"
            'btn.textContent = "⚡ GENERATE DOSSIER";'
            "}"
            "} catch (e) {"
            'alert("Error: " + e);'
            "btn.disabled = false;"
            'btn.textContent = "⚡ GENERATE DOSSIER";'
            "}"
            "});"
            "}"
            "});"
            "</script>"
        )
        html_str = html_str.replace(
            "<title>WOR-ACLE: Streamer Spotlight Hub</title>",
            f"<title>WOR-ACLE Spotlight: {title}</title>",
        )
        html_str = html_str.replace(
            'id="spotlight-title">Loading Spotlight Expose...</div>',
            f'id="spotlight-title">{title}</div>',
        )
        html_str = html_str.replace(
            'id="spotlight-meta">WOR-ACLE Daily Chronicle</div>',
            f'id="spotlight-meta">{meta_str}</div>',
        )
        old_body = (
            "<p>Fetching the latest 24-hour long-form expose from the database...</p>"
        )
        html_str = html_str.replace(old_body, missing_content)
        html_str = html_str.replace(
            'id="streamer-search"', f'id="streamer-search" value="{display_name}"'
        )

    return html_str


@router.get("/expose", response_class=HTMLResponse)
async def get_standalone_expose_query(handle: str | None = None):
    """Renders standalone expose page.

    Supports optional handle query param.
    """
    if handle:
        return await get_standalone_expose(handle)

    try:
        from ag_kaggle_5day.agents.gcp_storage import get_latest_expose_article

        article = get_latest_expose_article()
        if article:
            streamer = article.get("streamer_handle")
            if streamer:
                return await get_standalone_expose(streamer)
    except Exception:
        pass

    return SPOTLIGHT_HTML.replace(
        'id="spotlight-header">STREAMER OF THE DAY</h2>',
        'id="spotlight-header">DAILY EXPOSE DOSSIER</h2>',
    )


@router.get("/expose/{handle}", response_class=HTMLResponse)
async def get_standalone_expose(handle: str):
    """
    Renders a standalone, SEO-friendly Daily Expose report for a streamer handle.
    """
    h = handle.strip().lower()

    # Check if a link exists to get canonical details
    linked_twitch = h
    linked_youtube = None
    display_name = handle
    try:
        from ag_kaggle_5day.agents.gcp_storage import resolve_streamer_link

        link_info = resolve_streamer_link(h)
        if link_info:
            linked_twitch = link_info.get("twitch_handle") or h
            linked_youtube = link_info.get("youtube_channel_id")
            display_name = link_info.get("display_name") or handle
    except Exception:
        pass

    article = None
    try:
        from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

        fs = get_firestore_client()
        if fs:
            from google.cloud.firestore_v1.base_query import FieldFilter

            docs = (
                fs.collection("spotlight_expose_articles")
                .where(
                    filter=FieldFilter("streamer_handle", "==", linked_twitch.lower())
                )
                .order_by("timestamp", direction="DESCENDING")
                .limit(1)
                .stream()
            )
            for doc in docs:
                article = doc.to_dict()
                break
            if not article and linked_youtube:
                docs = (
                    fs.collection("spotlight_expose_articles")
                    .where(
                        filter=FieldFilter(
                            "streamer_handle", "==", linked_youtube.lower()
                        )
                    )
                    .order_by("timestamp", direction="DESCENDING")
                    .limit(1)
                    .stream()
                )
                for doc in docs:
                    article = doc.to_dict()
                    break
    except Exception as e:
        logger.warning(f"Failed to fetch expose article for standalone page: {e}")

    html_str = SPOTLIGHT_HTML

    # Re-use spotlight template layout for exposes
    html_str = html_str.replace(
        'id="spotlight-header">STREAMER OF THE DAY</h2>',
        'id="spotlight-header">DAILY EXPOSE DOSSIER</h2>',
    )

    if article:
        title = article.get("title") or f"Daily Expose: {display_name}"
        content = article.get("content") or ""
        ts = article.get("timestamp", 0.0)
        dt_str = (
            datetime.datetime.fromtimestamp(ts).strftime("%B %d, %Y")
            if ts
            else "Recent"
        )
        meta_str = f"WOR-ACLE Long-Form Expose | Published on {dt_str}"

        html_str = html_str.replace(
            "<title>WOR-ACLE: Streamer Spotlight Hub</title>",
            f"<title>WOR-ACLE Expose: {title}</title>",
        )
        html_str = html_str.replace(
            '<meta name="description" content="WOR-ACLE: Streamer of the Day '
            "Exposes and Community Profiles. Read in-depth analyses of top "
            'live content creators.">',
            f'<meta name="description" content="Read WOR-ACLE\'s in-depth '
            f'Daily Expose report for {display_name}.">',
        )
        html_str = html_str.replace(
            'id="spotlight-title">Loading Spotlight Expose...</div>',
            f'id="spotlight-title">{title}</div>',
        )
        html_str = html_str.replace(
            'id="spotlight-meta">WOR-ACLE Daily Chronicle</div>',
            f'id="spotlight-meta">{meta_str}</div>',
        )

        old_body = (
            "<p>Fetching the latest 24-hour long-form expose from the database...</p>"
        )
        html_str = html_str.replace(old_body, content)

        html_str = html_str.replace(
            'id="streamer-search"', f'id="streamer-search" value="{display_name}"'
        )

        links = article.get("associated_links") or {}
        if links:
            links_html = ""
            for platform, url in links.items():
                if url:
                    badge_cls = f"badge-{platform.lower()}"
                    links_html += (
                        f'<a href="{url}" target="_blank" '
                        f'class="social-badge {badge_cls}">'
                        f"{platform.upper()}</a>"
                    )
            if links_html:
                html_str = html_str.replace(
                    '<div id="spotlight-links" style="display: none; '
                    'gap: 10px; margin: 15px 0; flex-wrap: wrap;"></div>',
                    f'<div id="spotlight-links" style="display: flex; '
                    f"gap: 10px; margin: 15px 0; flex-wrap: "
                    f'wrap;">{links_html}</div>',
                )
    else:
        title = f"Expose Missing: {display_name}"
        meta_str = "No cached daily expose found"
        missing_content = (
            '<div style="text-align: center; padding: 2rem; '
            "border: 1px dashed rgba(255, 0, 127, 0.3); "
            'background: rgba(255, 0, 127, 0.02);">'
            '<p style="font-size: 1.2rem; color: var(--neon-yellow); '
            f'margin-bottom: 1.5rem;">⚠️ No Daily Expose has '
            f"been compiled for {display_name} yet.</p>"
            '<p style="font-size: 0.95rem; color: #887a9c; '
            'margin-bottom: 2rem;">Daily exposes are compiled '
            "automatically by the system cron or can be "
            "manually triggered in the background.</p>"
            '<button id="btn-trigger-expose" style="background-color: '
            "var(--neon-magenta); color: #000; font-family: 'Press Start "
            "2P', cursive; font-size: 0.85rem; border: none; padding: "
            '12px 24px; cursor: pointer; font-weight: bold;">⚡ '
            "TRIGGER EXPOSE JOB</button>"
            "</div>"
            "<script>"
            'document.addEventListener("DOMContentLoaded", () => {'
            'const btn = document.getElementById("btn-trigger-expose");'
            "if (btn) {"
            'btn.addEventListener("click", async () => {'
            "btn.disabled = true;"
            'btn.textContent = "⚡ TRIGGERING...";'
            "try {"
            'const res = await fetch("/api/articles/expose/trigger", {'
            'method: "POST"'
            "});"
            "if (res.ok) {"
            'alert("Daily expose background job has been triggered. '
            'Please wait 1-2 minutes and refresh this page.");'
            "} else {"
            "const err = await res.text();"
            'alert("Failed to trigger job: " + err);'
            "btn.disabled = false;"
            'btn.textContent = "⚡ TRIGGER EXPOSE JOB";'
            "}"
            "} catch (e) {"
            'alert("Error: " + e);'
            "btn.disabled = false;"
            'btn.textContent = "⚡ TRIGGER EXPOSE JOB";'
            "}"
            "});"
            "}"
            "});"
            "</script>"
        )
        html_str = html_str.replace(
            "<title>WOR-ACLE: Streamer Spotlight Hub</title>",
            f"<title>WOR-ACLE Expose: {title}</title>",
        )
        html_str = html_str.replace(
            'id="spotlight-title">Loading Spotlight Expose...</div>',
            f'id="spotlight-title">{title}</div>',
        )
        html_str = html_str.replace(
            'id="spotlight-meta">WOR-ACLE Daily Chronicle</div>',
            f'id="spotlight-meta">{meta_str}</div>',
        )
        old_body = (
            "<p>Fetching the latest 24-hour long-form expose from the database...</p>"
        )
        html_str = html_str.replace(old_body, missing_content)
        html_str = html_str.replace(
            'id="streamer-search"', f'id="streamer-search" value="{display_name}"'
        )

    return html_str
