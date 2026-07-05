import math

# Base Multilingual Vibe / Emotion Word Lexicons
COZY_WORDS = {
    "cozy",
    "chill",
    "comfy",
    "relax",
    "social",
    "friendly",
    "love",
    "cute",
    "nice",
    "wholesome",
    "sweet",
    "tranquilo",
    "relajado",
    "charla",
    "acogedor",
    "amigable",
    "bien",
    "amor",
    "feliz",
    "entspannt",
    "gemütlich",
    "plaudern",
    "nett",
    "ruhig",
    "liebe",
    "détente",
    "chaleureux",
    "calme",
    "amical",
    "discussion",
    "amour",
    "aconchegante",
    "suave",
    "amigável",
    "lindo",
    "maravilhoso",
    "良",
    "好",
}

HYPE_WORDS = {
    "hype",
    "pog",
    "poggers",
    "pogchamp",
    "gg",
    "goated",
    "cracked",
    "epic",
    "clean",
    "insane",
    "win",
    "easy",
    "ez",
    "lol",
    "lmao",
    "haha",
    "hahaha",
    "xd",
    "lfg",
    "omg",
    "wow",
    "great",
    "fun",
    "yes",
    "amazing",
    "clapped",
    "cool",
    "awesome",
    "perfect",
    "bueno",
    "excelente",
    "jaja",
    "jajaja",
    "grande",
    "increible",
    "si",
    "sim",
    "bom",
    "legal",
    "otimo",
    "kkk",
    "kkkk",
    "ja",
    "gut",
    "toll",
    "klasse",
    "super",
    "lustig",
    "oui",
    "bon",
    "genial",
    "草",
    "笑",
    "神",
    "おつ",
    "乙",
    "きた",
    "すご",
    "すごい",
    "うまい",
    "牛",
    "牛逼",
    "强",
    "赞",
    "秀",
    "厉害",
    "666",
    "ㅋ",
    "ㅎ",
    "나이스",
    "대박",
}

POLAR_WORDS = {
    "mad",
    "sad",
    "fail",
    "bad",
    "hate",
    "trash",
    "garbage",
    "toxic",
    "noob",
    "cry",
    "loser",
    "dead",
    "boring",
    "suck",
    "cringe",
    "rip",
    "no",
    "lose",
    "defeat",
    "awful",
    "terrible",
    "worst",
    "wasted",
    "l",
    "bore",
    "annoying",
    "wtf",
    "nerfed",
    "choke",
    "throw",
    "troll",
    "lag",
    "ping",
    "malo",
    "basura",
    "tóxico",
    "odiar",
    "perder",
    "frustrado",
    "mal",
    "aburrido",
    "triste",
    "feo",
    "horrible",
    "schlecht",
    "toxisch",
    "hassen",
    "verlieren",
    "dumm",
    "nein",
    "langweilig",
    "traurig",
    "hass",
    "blöd",
    "mist",
    "mauvais",
    "toxique",
    "détester",
    "perdre",
    "non",
    "ennuyeux",
    "nul",
    "ruim",
    "chato",
    "nao",
    "lixo",
    "feio",
    "horrivel",
    "悲",
    "怒",
    "泣",
    "無理",
    "酷",
    "ひどい",
    "下手",
    "オワタ",
    "最悪",
    "うざ",
    "ウザい",
    "クソ",
    "クソゲー",
    "烂",
    "差",
    "惨",
    "菜",
    "垃圾",
    "哭",
    "死",
    "坑",
    "无聊",
    "傻",
    "笨",
    "演",
    "ㅠㅠ",
    "ㅜㅜ",
    "ㄴㄴ",
    "에바",
    "노잼",
    "극혐",
    "망",
    "최악",
}

# Derived Sentiment Scoring Lexicons (used by sentinel.py for message-level polarity)
positive_words_set = COZY_WORDS.union(HYPE_WORDS)
negative_words_set = POLAR_WORDS

positive_emojis = {
    "🔥",
    "❤️",
    "😂",
    "👑",
    "🎉",
    "👍",
    "🙌",
    "✨",
    "⭐",
    "😍",
    "🥳",
    "😎",
    "🤩",
    "🚀",
}

negative_emojis = {
    "😢",
    "😡",
    "👎",
    "🤮",
    "💩",
    "💀",
    "🤡",
    "😭",
    "😤",
    "🤢",
    "👿",
    "💔",
    "🤦",
}

positive_emotes_set = {
    "kappa",
    "keepo",
    "lul",
    "lulw",
    "kekw",
    "pog",
    "pogchamp",
    "poggers",
    "komodohype",
    "kreygasm",
    "hypers",
    "heyguys",
    "coolcat",
    "koncha",
    "seemsgood",
    "pepega",
}

negative_emotes_set = {
    "biblethump",
    "notlikethis",
    "wutface",
    "residentsleeper",
    "dansgame",
    "failfish",
    "babyrage",
    "smorc",
}


# Expanded Multilingual Vibe Tags (English, German, Spanish, French, Portuguese)
COZY_TAGS = {
    "cozy",
    "chill",
    "comfy",
    "relaxing",
    "social",
    "casual",
    "friendly",
    "wholesome",
    "safe space",
    "tranquilo",
    "relajado",
    "charla",
    "acogedor",
    "amigable",
    "charlas",
    "entspannt",
    "gemütlich",
    "plaudern",
    "nett",
    "ruhig",
    "détente",
    "chaleureux",
    "calme",
    "amical",
    "discussion",
    "aconchegante",
    "suave",
    "amigável",
}

COMPETITIVE_TAGS = {
    "competitive",
    "ranked",
    "tryhard",
    "esports",
    "pvp",
    "tournament",
    "pro",
    "speedrun",
    "hardcore",
    "competitivo",
    "clasificatorio",
    "torneo",
    "profesional",
    "wettbewerb",
    "turnier",
    "profi",
    "rangliste",
    "compétitif",
    "classement",
    "tournoi",
    "campeonato",
    "ranqueado",
}

RETRO_TAGS = {
    "retro",
    "indie",
    "classic",
    "oldschool",
    "nostalgia",
    "pixel",
    "vintage",
    "antiguo",
    "independiente",
    "nostalgico",
    "nostalgie",
    "classique",
    "pixelart",
    "vintage",
    "antigo",
}

VTUBER_TAGS = {
    "vtuber",
    "pngtuber",
    "anime",
    "virtual",
    "vstreamer",
    "envtuber",
    "esvtuber",
    "devtuber",
    "frvtuber",
    "ptvtuber",
}

# Expanded Multilingual Bio Keywords
CHILL_KEYWORDS = {
    "chill",
    "casual",
    "relaxed",
    "comfy",
    "wholesome",
    "friendly",
    "relajado",
    "tranquilo",
    "amigable",
    "entspannt",
    "gemütlich",
    "ruhig",
    "détente",
    "calme",
    "amical",
    "suave",
    "amigável",
}

COMPETITIVE_KEYWORDS = {
    "pro",
    "tournament",
    "competitive",
    "ranked",
    "tryhard",
    "esports",
    "pvp",
    "speedrun",
    "torneo",
    "competitivo",
    "profesional",
    "turnier",
    "profi",
    "rangliste",
    "wettbewerb",
    "tournoi",
    "compétitif",
    "classement",
    "campeonato",
    "ranqueado",
}

RETRO_KEYWORDS = {
    "retro",
    "vintage",
    "indie",
    "pixel",
    "classic",
    "oldschool",
    "nostalgia",
    "antiguo",
    "independiente",
    "nostalgie",
    "classique",
    "antigo",
}


def normalize_language_code(lang_str: str) -> str:
    """
    Normalizes Twitch/YouTube-specific language strings into clean,
    standardized 2-letter ISO 639-1 language codes.
    """
    if not lang_str:
        return "en"

    clean = lang_str.strip().lower()

    # Common 3-letter or locale-specific mappings
    mappings = {
        "ger": "de",
        "deu": "de",
        "de-de": "de",
        "de_de": "de",
        "spa": "es",
        "es-es": "es",
        "es_es": "es",
        "es-mx": "es",
        "es_mx": "es",
        "fra": "fr",
        "fre": "fr",
        "fr-fr": "fr",
        "fr_fr": "fr",
        "por": "pt",
        "pt-br": "pt",
        "pt_br": "pt",
        "pt-pt": "pt",
        "ita": "it",
        "it-it": "it",
        "it_it": "it",
        "rus": "ru",
        "ru-ru": "ru",
        "ru_ru": "ru",
        "kor": "ko",
        "ko-kr": "ko",
        "ko_kr": "ko",
        "jpn": "ja",
        "ja-jp": "ja",
        "ja_jp": "ja",
        "zho": "zh",
        "chi": "zh",
        "zh-cn": "zh",
        "zh_cn": "zh",
        "zh-tw": "zh",
        "eng": "en",
        "en-us": "en",
        "en_us": "en",
        "en-gb": "en",
    }

    if clean in mappings:
        return mappings[clean]

    # Check prefix
    parts = clean.split("-")
    if parts and len(parts[0]) == 2 and parts[0].isalpha():
        return parts[0]

    parts_under = clean.split("_")
    if parts_under and len(parts_under[0]) == 2 and parts_under[0].isalpha():
        return parts_under[0]

    # Fallback to first 2 letters if alphabetic
    prefix = clean[:2]
    if len(prefix) == 2 and prefix.isalpha():
        return prefix

    return "en"


def extract_streamer_features(p_data: dict) -> list[float]:
    """
    Extracts a standardized 13-dimensional feature vector from a streamer profile.
    Returns: [feat_mpm, feat_vol, feat_idr, has_cozy, has_comp, has_retro, has_vtuber,
              bio_chill, bio_comp, bio_retro, is_es, is_de, is_en]
    """
    bio = (
        p_data.get("bootstrap_context", {}).get(
            "bio_description", p_data.get("twitch_description", "")
        )
        or ""
    )
    tags = p_data.get("bootstrap_context", {}).get("vibe_tags", []) or []

    # Extract density metrics
    mpm = (
        p_data.get("interaction_density", {}).get("msg_per_minute", 0.0)
        or p_data.get("average_msg_per_minute", 0.0)
        or 0.0
    )
    vol = (
        p_data.get("interaction_density", {}).get("chat_volatility", 0.0)
        or p_data.get("average_chat_volatility", 0.0)
        or 0.0
    )
    idr = (
        p_data.get("interaction_density", {}).get("interactive_density_rate", 0.0)
        or 0.0
    )

    # Scale density metrics (log-scaled where appropriate)
    feat_mpm = math.log1p(mpm)
    feat_idr = math.log1p(idr)
    feat_vol = vol

    # Match vibe tags
    tags_lower = [t.lower() for t in tags]
    has_cozy = 1.0 if any(t in COZY_TAGS for t in tags_lower) else 0.0
    has_comp = 1.0 if any(t in COMPETITIVE_TAGS for t in tags_lower) else 0.0
    has_retro = 1.0 if any(t in RETRO_TAGS for t in tags_lower) else 0.0
    has_vtuber = 1.0 if any(t in VTUBER_TAGS for t in tags_lower) else 0.0

    # Match bio keywords
    bio_lower = bio.lower()
    bio_chill = 1.0 if any(w in bio_lower for w in CHILL_KEYWORDS) else 0.0
    bio_comp = 1.0 if any(w in bio_lower for w in COMPETITIVE_KEYWORDS) else 0.0
    bio_retro = 1.0 if any(w in bio_lower for w in RETRO_KEYWORDS) else 0.0

    # Match languages
    lang_raw = p_data.get("language", "en")
    lang = normalize_language_code(lang_raw)
    is_es = 1.0 if lang == "es" else 0.0
    is_de = 1.0 if lang == "de" else 0.0
    is_en = 1.0 if lang == "en" else 0.0

    return [
        feat_mpm,
        feat_vol,
        feat_idr,
        has_cozy,
        has_comp,
        has_retro,
        has_vtuber,
        bio_chill,
        bio_comp,
        bio_retro,
        is_es,
        is_de,
        is_en,
    ]


def calculate_multidimensional_sentiment(messages: list[str]) -> dict:
    """
    Computes local, multilingual multi-dimensional sentiment/vibe percentages
    across four dimensions: cozy, competitive_hype, polarization, and spam.
    """
    if not messages:
        return {"cozy": 0.0, "hype": 0.0, "polarization": 0.0, "spam": 0.0}

    cozy_score = 0
    hype_score = 0
    polar_score = 0
    spam_score = 0

    total_checked = 0
    for msg in messages:
        if not msg:
            continue
        msg_lower = msg.lower()
        total_checked += 1

        # 1. Check spam (highly repetitive messages or uppercase ratio)
        char_set = set(msg_lower)
        if len(msg_lower) > 12 and len(char_set) / len(msg_lower) < 0.25:
            spam_score += 1
            continue

        # 2. Check words using global lexicons
        matched_cozy = any(w in msg_lower for w in COZY_WORDS)
        matched_hype = any(w in msg_lower for w in HYPE_WORDS)
        matched_polar = any(w in msg_lower for w in POLAR_WORDS)

        if matched_cozy:
            cozy_score += 1
        if matched_hype:
            hype_score += 1
        if matched_polar:
            polar_score += 1

    if total_checked == 0:
        return {"cozy": 0.0, "hype": 0.0, "polarization": 0.0, "spam": 0.0}

    sum_scores = cozy_score + hype_score + polar_score + spam_score
    if sum_scores == 0:
        return {"cozy": 0.25, "hype": 0.25, "polarization": 0.25, "spam": 0.25}

    return {
        "cozy": float(round(cozy_score / sum_scores, 3)),
        "hype": float(round(hype_score / sum_scores, 3)),
        "polarization": float(round(polar_score / sum_scores, 3)),
        "spam": float(round(spam_score / sum_scores, 3)),
    }
