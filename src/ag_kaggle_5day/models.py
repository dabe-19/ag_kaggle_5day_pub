from pydantic import BaseModel


class RecommendRequest(BaseModel):
    query: str


class CollectRequest(BaseModel):
    custom_games: list[str] = []
    category: str = "overall"


class CompareRequest(BaseModel):
    custom_games: list[str] = []
    category: str = "overall"
    force_refresh: bool = False
    visible_games: list[dict] = []


class PlaybookRequest(BaseModel):
    vibe: str
    scale: str
    duration: float
    stream_goal: str
    game: str | None = None
    custom_context: str | None = None


class MediumFormRequest(BaseModel):
    streamer_handle: str
    previous_playbooks: list[dict] | None = None
    model: str | None = None


class LinkStreamerAccountsPayload(BaseModel):
    twitch_handle: str
    youtube_channel_id: str
    display_name: str


class MatchmakerRegisterPayload(BaseModel):
    streamer_handle: str
    bio_description: str
    vibe_tags: list[str]
    is_bootstrap: bool = False


class MatchmakerRecommendPayload(BaseModel):
    streamer_handle: str
    api_key: str | None = None


class ConnectRequest(BaseModel):
    api_key: str
    remember: bool = False
