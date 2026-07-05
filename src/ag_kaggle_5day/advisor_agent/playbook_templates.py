from typing import Any, Dict, List

# Detailed templates mapped to game category patterns
RAID_PLAYBOOK_TEMPLATES = {
    "racing": {
        "meta_vibe": "Cozy / High-Focus Racing Vibe",
        "copypasta": "🏎️💨 THE RAIDING ROOKIES HAVE ARRIVED! CHILL DRAFT ONLY! 🏎️💨",
        "opener": (
            "We are arguing in Discord: is the manual or automatic clutch "
            "better for drifting in this weather on {game}?"
        ),
        "clip_challenge": (
            "Watch for a clean drift corner or a funny crash, clip it, "
            "and type: 'Just clipped that corner save, that was awesome!'"
        ),
        "sign_off": "Keep up the great work, good luck with the racing lines!",
        "reasoning": (
            "Racing category streams have a highly passionate debate over "
            "transmission types and racing lines, which forces immediate, "
            "interactive gameplay engagement."
        ),
    },
    "sandbox": {
        "meta_vibe": "Creative / Cozy Sandbox Vibe",
        "copypasta": "⛏️🧱 BLOCK BY BLOCK, THE RAID PATROL HAS ARRIVED! 🧱⛏️",
        "opener": (
            "Your build looks amazing! Are you planning to expand this "
            "structure or work on a new redstone contraption next on {game}?"
        ),
        "clip_challenge": (
            "Clip any cool build reveal or accidental lava placement, and "
            "post: 'Just clipped that build moment, absolutely legendary!'"
        ),
        "sign_off": (
            "Keep up the creative builds! Good luck with the resource gathering!"
        ),
        "reasoning": (
            "Sandbox streams are highly collaborative and build-focused. "
            "Asking about construction plans invites the streamer to show "
            "off their designs."
        ),
    },
    "rpg": {
        "meta_vibe": "Immersive Story / Adventure Vibe",
        "copypasta": "⚔️🛡️ THE ADVENTURERS RAID IS HERE! PREPARE YOUR QUESTS! 🛡️⚔️",
        "opener": (
            "That build/setup looks intense! What specific attributes or "
            "gear stats are you prioritizing for this dungeon/boss run "
            "in {game}?"
        ),
        "clip_challenge": (
            "Clip the next boss stagger, clutch victory, or dramatic story "
            "cutscene, and post: 'That boss fight save was clean!'"
        ),
        "sign_off": "May your loot be legendary and your quests successful!",
        "reasoning": (
            "RPG and adventure game players love talking about their custom "
            "builds, specs, and gear. This prompt triggers in-depth "
            "gameplay discussions."
        ),
    },
    "fps": {
        "meta_vibe": "Sweaty / High-Performance FPS Vibe",
        "copypasta": "🎯🔫 CLUTCH OR KICK! THE RAID SQUAD HAS LANDED! 🔫🎯",
        "opener": (
            "We need settle a discord debate: does playing on stretch-res "
            "actually help with target tracking in {game}?"
        ),
        "clip_challenge": (
            "Clip a clean headshot, clutch round win, or a funny miss, "
            "and post: 'That flick was crazy! Clipped it!'"
        ),
        "sign_off": "Good luck with the ranks, get those headshots!",
        "reasoning": (
            "Competitive shooter audiences are obsessed with settings, "
            "resolutions, and crosshairs. An opener challenging their "
            "setup choice sparks instant interest."
        ),
    },
    "strategy": {
        "meta_vibe": "Tactical / High-Brain Strategy Vibe",
        "copypasta": "🧠🃏 200 IQ RAID INBOUND! CALCULATING VIBES! 🃏🧠",
        "opener": (
            "Is this current build/comp the actual meta, or are you "
            "trying a secret off-meta strategy in {game}?"
        ),
        "clip_challenge": (
            "Clip a massive teamfight, high-value card draw, or "
            "huge tactical turn, and post: 'That outplay was actually 200 IQ!'"
        ),
        "sign_off": "Keep out-smarting the lobby, good luck with the wins!",
        "reasoning": (
            "Strategy players love debating meta viability versus "
            "experimental theory-crafting. This question invites them "
            "to explain their strategy."
        ),
    },
    "variety": {
        "meta_vibe": "Chill / Interactive Chatting Vibe",
        "copypasta": "👾🎉 THE WOR-ACLE RAID IS HERE! HELLO WORLD! 🎉👾",
        "opener": (
            "We just dropped in! What has been the absolute highlight "
            "of your stream so far today?"
        ),
        "clip_challenge": (
            "Clip any funny joke, jump-scare, or cozy chatting moment, "
            "and post: 'Clipped that stream highlight, made our day!'"
        ),
        "sign_off": "Keep up the awesome stream, we had a blast hanging out!",
        "reasoning": (
            "Variety and chatting streamers thrive on direct community "
            "interactions. Asking for stream highlights prompts them "
            "to summarize their session and show gratitude."
        ),
    },
}


def generate_raid_playbook(
    target_streamer_meta: Dict[str, Any], trending_tokens: List[str]
) -> Dict[str, str]:
    """
    Combines target streamer category metadata with trending internet tokens
    to output a scannable 3-step actionable icebreaker card for user groups.
    """
    game = target_streamer_meta.get("game") or "General (No top game registered)"
    category = target_streamer_meta.get("category") or "variety"
    streamer_handle = target_streamer_meta.get("streamer_handle") or "Streamer"

    # Resolve genre mapping based on category/game name matching
    category_lower = category.lower()
    game_lower = game.lower()

    if "racing" in category_lower or "forza" in game_lower or "kart" in game_lower:
        genre = "racing"
    elif (
        "sandbox" in category_lower
        or "minecraft" in game_lower
        or "roblox" in game_lower
    ):
        genre = "sandbox"
    elif (
        "rpg" in category_lower
        or "elden" in game_lower
        or "story" in category_lower
        or "adventure" in category_lower
    ):
        genre = "rpg"
    elif (
        "fps" in category_lower
        or "shooter" in category_lower
        or "valorant" in game_lower
        or "counter" in game_lower
    ):
        genre = "fps"
    elif (
        "strategy" in category_lower
        or "card" in category_lower
        or "tft" in game_lower
        or "tactics" in game_lower
        or "chess" in game_lower
    ):
        genre = "strategy"
    else:
        genre = "variety"

    template = RAID_PLAYBOOK_TEMPLATES[genre]

    # Build trending context strings
    trend_context = ""
    if trending_tokens:
        clean_tokens = [t for t in trending_tokens if t.strip()]
        if clean_tokens:
            trend_context = f" (Trending: {', '.join(clean_tokens[:2])})"

    # Resolve templates with specific context
    opener = template["opener"].format(game=game)
    if trend_context and clean_tokens:
        opener += f" Have you checked out the latest {clean_tokens[0]} meta?"

    copypasta = template["copypasta"]
    if clean_tokens:
        # Inject one of the trending tokens into the copypasta for freshness
        copypasta = f"🎉🔥 {clean_tokens[0].upper()} METAS AHEAD! {copypasta}"

    return {
        "target_streamer": streamer_handle,
        "game": game,
        "meta_vibe": f"{template['meta_vibe']}{trend_context}",
        "copypasta": copypasta,
        "opener": opener,
        "clip_challenge": template["clip_challenge"],
        "sign_off": template["sign_off"],
        "why_it_works": (
            f"This playbook works for @{streamer_handle} because "
            f"{template['reasoning'].lower()}"
        ),
    }
