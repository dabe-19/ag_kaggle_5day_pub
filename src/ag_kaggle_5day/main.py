import argparse

import uvicorn

from ag_kaggle_5day.logging_config import setup_logging


def start():
    # Initialize structured JSON logging
    setup_logging()

    parser = argparse.ArgumentParser(
        description="Streamer Metrics Advisor CLI & Server"
    )
    parser.add_argument(
        "--host", default="0.0.0.0", help="Host address to bind the server to"
    )
    parser.add_argument(
        "--port", type=int, default=8000, help="Port to run the server on"
    )
    args = parser.parse_args()

    print(
        f"Launching Streamer Metrics Advisor server at http://{args.host}:{args.port}"
    )
    import os

    env_file = ".env" if os.path.exists(".env") else None
    uvicorn.run(
        "ag_kaggle_5day.app:app",
        host=args.host,
        port=args.port,
        reload=False,
        env_file=env_file,
    )


if __name__ == "__main__":
    start()
