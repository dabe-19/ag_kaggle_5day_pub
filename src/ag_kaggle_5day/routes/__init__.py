from ag_kaggle_5day.routes.admin import router as admin_router
from ag_kaggle_5day.routes.articles import router as articles_router
from ag_kaggle_5day.routes.auth import router as auth_router
from ag_kaggle_5day.routes.games import router as games_router
from ag_kaggle_5day.routes.matchmaker import router as matchmaker_router
from ag_kaggle_5day.routes.monitoring import router as monitoring_router
from ag_kaggle_5day.routes.news import router as news_router
from ag_kaggle_5day.routes.pages import router as pages_router
from ag_kaggle_5day.routes.recommend import router as recommend_router
from ag_kaggle_5day.routes.streamers import router as streamers_router

__all__ = [
    "pages_router",
    "games_router",
    "recommend_router",
    "news_router",
    "streamers_router",
    "matchmaker_router",
    "articles_router",
    "admin_router",
    "auth_router",
    "monitoring_router",
]
