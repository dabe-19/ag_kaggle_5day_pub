import logging
import math
import urllib.parse
from typing import Optional

logger = logging.getLogger("streamer_advisor.scraper")


class DynamicSponsoredGames(list):
    """A list proxy that dynamically accesses sponsored games from
    load_model_config().
    """

    def __init__(self):
        super().__init__()

    @property
    def _games(self) -> list[dict]:
        default_sponsored = [
            {
                "title": "Minecraft",
                "category": "Sandbox",
                "avg_viewers": 125000,
                "avg_length_hours": 3.2,
                "score": 92,
            },
            {
                "title": "Elden Ring",
                "category": "RPG",
                "avg_viewers": 85000,
                "avg_length_hours": 4.5,
                "score": 88,
            },
            {
                "title": "VALORANT",
                "category": "FPS",
                "avg_viewers": 140000,
                "avg_length_hours": 2.8,
                "score": 95,
            },
            {
                "title": "Hades II",
                "category": "Roguelike",
                "avg_viewers": 45000,
                "avg_length_hours": 3.8,
                "score": 82,
            },
            {
                "title": "League of Legends",
                "category": "MOBA",
                "avg_viewers": 210000,
                "avg_length_hours": 3.5,
                "score": 96,
            },
            {
                "title": "Grand Theft Auto V",
                "category": "Action-Adventure",
                "avg_viewers": 115000,
                "avg_length_hours": 4.1,
                "score": 90,
            },
        ]
        from ag_kaggle_5day.agents.scraper import load_model_config

        config = load_model_config()
        return config.get(
            "sponsored_games", config.get("staple_games", default_sponsored)
        )

    def __len__(self):
        return len(self._games)

    def __iter__(self):
        return iter(self._games)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return self._games[index]
        return self._games[index]

    def __repr__(self):
        return repr(self._games)


# ---------------------------------------------------------------------------
# Sponsored reference games — dynamically loaded list proxy.
# ---------------------------------------------------------------------------


SPONSORED_GAMES = DynamicSponsoredGames()
STAPLE_GAMES = SPONSORED_GAMES
DEFAULT_GAMES = SPONSORED_GAMES

# Twitch streams pagination cap (100 streams/page × 3 pages = 300 streams max)
_TWITCH_STREAM_PAGE_CAP = 3


# ---------------------------------------------------------------------------
# JSON parsing helper (unchanged)
# ---------------------------------------------------------------------------


def _build_canonical_game(
    title: str,
    category: str,
    twitch_viewers: int,
    youtube_viewers: int,
    avg_length_hours: float,
    score: int,
    source: str,
    source_url: str,
    tier: str = "staple",
    custom: bool = False,
    data_quality: str = "live",
    youtube_fetched_at: Optional[float] = None,
    top_streamers: Optional[list] = None,
    stream_count: int = 0,
    genres: Optional[list[str]] = None,
    themes: Optional[list[str]] = None,
    cover_url: Optional[str] = None,
) -> dict:
    """Assembles a fully-populated game dict in the canonical shape.

    data_quality values:
      "live"       — numbers come from Twitch Helix API or YouTube Data API v3
      "estimated"  — numbers come from Gemini Search Grounding (synthesised)
      "no_live_data" — numbers come from the STAPLE_GAMES constant
      (no live call succeeded)
    """
    avg_viewers = twitch_viewers + youtube_viewers
    if not source_url or not source_url.startswith("http"):
        source_url = f"https://www.twitch.tv/directory/game/{urllib.parse.quote(title)}"

    # Try resolving/enriching from Firestore category cache if missing
    if not genres or not themes or not cover_url:
        try:
            from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

            db = get_firestore_client()
            if db:
                name_lower = title.lower().strip().replace("/", "-")
                doc = (
                    db.collection("resolved_game_categories").document(name_lower).get()
                )
                if doc.exists:
                    doc_data = doc.to_dict()
                    if not genres:
                        genres = doc_data.get("genres")
                    if not themes:
                        themes = doc_data.get("themes")
                    if not cover_url:
                        cover_url = doc_data.get("cover_url")
        except Exception as e:
            logger.warning(f"Failed to enrich game '{title}' from Firestore cache: {e}")

    # Override category representation with the top 2 IGDB genres if present
    if genres:
        unique_genres = []
        for g in genres:
            g_clean = g.strip()
            if g_clean and g_clean not in unique_genres:
                unique_genres.append(g_clean)
        if unique_genres:
            category = ", ".join(unique_genres[:2])

    res = {
        "title": title,
        "category": category,
        "avg_viewers": avg_viewers,
        "twitch_viewers": twitch_viewers,
        "youtube_viewers": youtube_viewers,
        "avg_length_hours": avg_length_hours,
        "score": score,
        "source": source,
        "source_url": source_url,
        "custom": custom,
        "tier": tier,
        "data_quality": data_quality,
        "top_streamers": top_streamers or [],
        "stream_count": stream_count,
        "genres": genres or [],
        "themes": themes or [],
        "cover_url": cover_url,
    }
    if youtube_fetched_at is not None:
        res["youtube_fetched_at"] = youtube_fetched_at
    return res


# ---------------------------------------------------------------------------
# Twitch Categories Mapping
# ---------------------------------------------------------------------------


TWITCH_CATEGORIES = {
    "irl": [
        "Just Chatting",
        "Talk Shows & Podcasts",
        "Travel & Outdoors",
        "Art",
        "Food & Drink",
        "ASMR",
        "Pools, Hot Tubs, and Beaches",
        "Sports",
        "Tabletop RPGs",
        "Retro",
    ],
    "music": [
        "Music",
        "DJ",
        "Retro",
    ],
    "creative": [
        "Software and Game Development",
        "Makers & Crafting",
        "Beauty & Body Art",
        "Art",
        "Food & Drink",
        "ASMR",
    ],
    "esports": [
        "VALORANT",
        "League of Legends",
        "Counter-Strike",
        "Dota 2",
        "Apex Legends",
        "Overwatch 2",
        "Fortnite",
        "PUBG: BATTLEGROUNDS",
        "Tom Clancy's Rainbow Six Siege",
        "Rocket League",
    ],
}


# ---------------------------------------------------------------------------
# Twitch Helix API client
# ---------------------------------------------------------------------------


def _infer_category(
    game_name: str, staple: Optional[dict], box_art_url: Optional[str] = None
) -> str:
    """Returns the category from the staple list if known,
    else infers via keyword rules.
    """
    if staple:
        return staple["category"]

    name_lower = game_name.lower().strip().replace("/", "-")
    if not name_lower:
        return "Unknown"

    from ag_kaggle_5day.agents.gcp_storage import get_firestore_client

    db = get_firestore_client()

    # Step 1: Check Firestore cache
    if db:
        try:
            doc = db.collection("resolved_game_categories").document(name_lower).get()
            if doc.exists:
                doc_data = doc.to_dict()
                cached_cat = doc_data.get("category")
                cached_cover = doc_data.get("cover_url")
                # Update cache cover if missing but caller provided one
                if box_art_url and not cached_cover:
                    try:
                        db.collection("resolved_game_categories").document(
                            name_lower
                        ).update({"cover_url": box_art_url})
                    except Exception:
                        pass
                if cached_cat:
                    return cached_cat
        except Exception as fe:
            logger.warning(f"Failed to read resolved category from Firestore: {fe}")

    # Step 2: Query IGDB via Twitch API
    genres = None
    themes = None
    try:
        from ag_kaggle_5day.agents.scraper.twitch import TwitchAPIClient

        twitch_client = TwitchAPIClient()
        if twitch_client.is_configured:
            meta = twitch_client.query_igdb_metadata(game_name)
            if meta:
                genres = meta.get("genres")
                themes = meta.get("themes")
    except Exception as ie:
        logger.warning(f"Failed to query IGDB metadata for '{game_name}': {ie}")

    # Step 3: Map genres to standard categories
    category = None
    if genres:
        genres_lower = [g.lower() for g in genres]
        if any("role-playing" in g or "rpg" in g for g in genres_lower):
            category = "RPG"
        elif any("shooter" in g or "fps" in g for g in genres_lower):
            category = "FPS"
        elif any("moba" in g or "tactical" in g for g in genres_lower):
            category = "MOBA"
        elif any("strategy" in g or "rts" in g for g in genres_lower):
            category = "Strategy"
        elif any("simulator" in g or "simulation" in g for g in genres_lower):
            category = "Simulation"
        elif any("sport" in g for g in genres_lower):
            category = "Sports"
        elif any(
            "platform" in g or "puzzle" in g or "arcade" in g for g in genres_lower
        ):
            category = "Puzzle"
        elif any("indie" in g for g in genres_lower):
            category = "Indie"
        elif any("sandbox" in g or "open world" in g for g in genres_lower):
            category = "Sandbox"

    if category:
        if db:
            try:
                import time

                db.collection("resolved_game_categories").document(name_lower).set(
                    {
                        "category": category,
                        "resolved_at": time.time(),
                        "genres": genres,
                        "themes": themes or [],
                        "cover_url": box_art_url,
                    }
                )
            except Exception as fe:
                logger.warning(f"Failed to write resolved category to Firestore: {fe}")
        return category

    # Step 4: Fallback to naive check rules
    category = _infer_category_naive(name_lower)

    # Save fallback category to cache
    if db and category != "Unknown":
        try:
            import time

            db.collection("resolved_game_categories").document(name_lower).set(
                {
                    "category": category,
                    "resolved_at": time.time(),
                    "genres": [],
                    "themes": [],
                    "cover_url": box_art_url,
                }
            )
        except Exception as fe:
            logger.warning(
                f"Failed to write fallback resolved category to Firestore: {fe}"
            )

    return category


def _infer_category_naive(name_lower: str) -> str:
    """Fallback keyword rules for determining game categories."""
    # 1. MOBA
    moba_keywords = [
        "league of legends",
        "lol",
        "dota",
        "smite",
        "heroes of the storm",
        "arena of valor",
    ]
    if any(k in name_lower for k in moba_keywords):
        return "MOBA"

    # 2. FPS / Shooter
    fps_keywords = [
        "shooter",
        "fps",
        "valorant",
        "counter-strike",
        "cs:go",
        "cs2",
        "apex legends",
        "apex",
        "overwatch",
        "call of duty",
        "cod",
        "warzone",
        "fortnite",
        "pubg",
        "rainbow six",
        "siege",
        "destiny",
        "halo",
        "battlefield",
        "doom",
        "escape from tarkov",
        "tarkov",
        "rust",
        "dayz",
        "team fortress",
        "left 4 dead",
        "payday",
        "metro",
        "wolfenstein",
        "borderlands",
        "crysis",
    ]
    if any(k in name_lower for k in fps_keywords):
        return "FPS"

    # 3. Sandbox
    sandbox_keywords = [
        "sandbox",
        "open world",
        "minecraft",
        "roblox",
        "terraria",
        "garry's mod",
        "gmod",
        "satisfactory",
        "rimworld",
        "sims",
        "cities: skylines",
        "subnautica",
        "astroneer",
        "valheim",
        "factorio",
        "animal crossing",
        "stardew",
        "lego",
        "scrap mechanic",
        "teardown",
        "no man's sky",
    ]
    if any(k in name_lower for k in sandbox_keywords):
        return "Sandbox"

    # 4. RPG
    rpg_keywords = [
        "rpg",
        "role-playing",
        "souls",
        "elden ring",
        "diablo",
        "final fantasy",
        "cyberpunk",
        "world of warcraft",
        "wow",
        "baldur",
        "path of exile",
        "poe",
        "starfield",
        "witcher",
        "skyrim",
        "fallout",
        "persona",
        "monster hunter",
        "genshin",
        "honkai",
        "star rail",
        "lost ark",
        "runescape",
        "dark souls",
        "bloodborne",
        "sekiro",
        "pokemon",
        "dragon quest",
        "kingdom hearts",
        "dragons dogma",
        "mass effect",
        "dragon age",
        "xenoblade",
    ]
    if any(k in name_lower for k in rpg_keywords):
        return "RPG"

    # 5. Roguelike
    roguelike_keywords = [
        "rogue",
        "roguelike",
        "roguelite",
        "hades",
        "slay the spire",
        "dead cells",
        "binding of isaac",
        "isaac",
        "vampire survivors",
        "risk of rain",
        "noita",
        "cult of the lamb",
        "balatro",
        "ftl",
        "spelunky",
        "darkest dungeon",
        "enter the dungeon",
        "gungeon",
        "loop hero",
    ]
    if any(k in name_lower for k in roguelike_keywords):
        return "Roguelike"

    # 6. Action-Adventure
    action_adventure_keywords = [
        "action",
        "adventure",
        "grand theft auto",
        "gta",
        "red dead",
        "rdr",
        "assassin",
        "zelda",
        "spider-man",
        "tomb raider",
        "god of war",
        "last of us",
        "uncharted",
        "horizon zero",
        "ghost of tsushima",
        "star wars",
        "dying light",
        "resident evil",
        "silent hill",
        "outlast",
        "batman",
        "arkham",
        "devil may cry",
        "yakuza",
        "like a dragon",
        "tales of",
        "alan wake",
        "control",
    ]
    if any(k in name_lower for k in action_adventure_keywords):
        return "Action-Adventure"

    # 7. IRL / Non-gaming
    irl_keywords = [
        "irl",
        "just chatting",
        "talk shows",
        "podcast",
        "travel",
        "outdoor",
        "art",
        "food",
        "drink",
        "asmr",
        "pools",
        "hot tub",
        "beach",
        "sports",
        "retro",
        "music",
        "dj",
        "creative",
        "software",
        "development",
        "crafting",
        "beauty",
        "body art",
        "special events",
        "talk shows & podcasts",
        "pools, hot tubs, and beaches",
        "makers & crafting",
        "software and game development",
        "virtual casino",
        "slots",
        "poker",
        "chess",
        "board games",
    ]
    if any(k in name_lower for k in irl_keywords):
        return "IRL"

    # 8. Racing / Driving
    racing_keywords = [
        "forza",
        "racing",
        "driving",
        "f1",
        "mario kart",
        "need for speed",
        "gran turismo",
        "dirt",
        "grid",
        "nascar",
        "wrc",
        "trackmania",
    ]
    if any(k in name_lower for k in racing_keywords):
        return "Racing"

    return "Unknown"


def _calculate_score(twitch_viewers: int, youtube_viewers: int) -> int:
    """
    Computes a streaming viability score (0-100) from real viewer counts.
    Based on total concurrent viewers with a logarithmic scale.
    """
    total = twitch_viewers + youtube_viewers
    if total <= 0:
        return 0

    # log10(100k) ≈ 5.0 → score 100; log10(1k) ≈ 3.0 → score 60
    raw = math.log10(max(total, 1)) * 20
    return max(0, min(100, int(raw)))


def _estimate_avg_length(
    game_name: str, api_key: Optional[str], model: Optional[str] = None
) -> float:
    """
    Estimates average stream session length for a game.
    To avoid slow startup times and reduce token usage/LLM latency, this method returns
    the baseline value from STAPLE_GAMES if available, or a default of 3.0 hours.
    """
    staple = next(
        (g for g in STAPLE_GAMES if g["title"].lower() == game_name.lower()), None
    )
    if staple:
        return float(staple.get("avg_length_hours", 3.0))
    return 3.0
