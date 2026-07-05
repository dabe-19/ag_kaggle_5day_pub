import asyncio
import logging
import os
import time

from ag_kaggle_5day.agents.advisor import refresh_hourly_cache
from ag_kaggle_5day.agents.gcp_storage import get_app_cache_state, store_app_cache_state
from ag_kaggle_5day.agents.scraper import TwitchAPIClient, YouTubeAPIClient
from ag_kaggle_5day.app import get_effective_key, query_remote_agent
from ag_kaggle_5day.logging_config import setup_logging

try:
    from ag_kaggle_5day.agents.scraper import start_raid_sentinel, stop_raid_sentinel
except ImportError:

    async def start_raid_sentinel(key: str):
        logger.info("RaidSentinel: Stubs active (not yet implemented in scraper.py)")

    async def stop_raid_sentinel(key=None):
        logger.info("RaidSentinel: Stubs active (not yet implemented in scraper.py)")


logger = logging.getLogger("streamer_advisor.cron")


def load_env():
    """Loads environment variables from .env file for local run support."""
    # Find .env by traversing up to the project root
    current = os.path.abspath(__file__)
    for _ in range(4):
        current = os.path.dirname(current)
        env_path = os.path.join(current, ".env")
        if os.path.exists(env_path):
            logger.info(f"Loading environment variables from: {env_path}")
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    stripped = line.strip()
                    if "=" in stripped and not stripped.startswith("#"):
                        k, v = stripped.split("=", 1)
                        os.environ[k.strip()] = v.strip().strip('"').strip("'")
            break


async def run_cron_refresh():
    """Executes the hourly metrics scraping and playbook generation tasks
    sequentially.
    """
    setup_logging()
    load_env()
    logger.info("Cron: Starting scheduled hourly metrics refresh...")

    key = get_effective_key()
    if not key:
        logger.error("Cron: GEMINI_API_KEY environment variable is not set. Aborting.")
        raise ValueError("GEMINI_API_KEY environment variable is required.")

    twitch = TwitchAPIClient()
    youtube = YouTubeAPIClient()

    sentinel_start_time = time.time()
    # Start the RaidSentinel background listener task concurrently
    logger.info("Cron: Starting RaidSentinel background listener...")
    sentinel_task = asyncio.create_task(start_raid_sentinel(key))

    try:
        # 1. Run scraping and streamer aggregation in parallel
        logger.info(
            "Cron: Running metrics scraping and streamer aggregation in parallel..."
        )
        start_time = time.time()
        try:
            from ag_kaggle_5day.agents.advisor import run_daily_analytics_aggregation

            loop = asyncio.get_running_loop()
            scrape_fut = loop.run_in_executor(
                None,
                refresh_hourly_cache,
                key,
                twitch,
                youtube,
                None,
                None,
                True,
            )
            agg_fut = loop.run_in_executor(
                None,
                run_daily_analytics_aggregation,
                key,
            )
            await asyncio.gather(scrape_fut, agg_fut)
            duration = time.time() - start_time
            logger.info(f"Cron: Scraping and aggregation completed in {duration:.2f}s")
        except Exception as e:
            logger.error(
                f"Cron: Parallel scraping or aggregation failed: {e}", exc_info=True
            )
            raise

        # 2. Run scheduled agent playbooks generation task if stale (24h)
        playbook_stale = True
        try:
            status = get_app_cache_state("daily_playbooks_status")
            if status:
                latest_ts = status.get("last_run", 0.0)
                age = time.time() - latest_ts
                if age <= 24 * 3600:
                    playbook_stale = False
                    logger.info(
                        f"Cron: Playbooks cache is fresh (age: {age:.2f}s). "
                        "Skipping scheduled generation."
                    )
        except Exception as check_err:
            logger.warning(f"Cron: Error checking playbooks cache status: {check_err}")

        if playbook_stale:
            logger.info("Cron: Triggering agent playbook generation...")
            playbook_start = time.time()
            try:
                prompt = (
                    "Perform scheduled database updates: generate "
                    "and store playbooks for "
                    "standard profiles. Execute playbook generation for the following: "
                    "1. vibe='chill', scale='starting', duration=3.0 "
                    "2. vibe='competitive', scale='affiliate', duration=4.0 "
                    "3. vibe='community', scale='partner', duration=2.5"
                )
                await query_remote_agent(
                    prompt,
                    user_id="scheduled_system_task",
                    session_id=f"scheduled_session_{int(time.time())}",
                    api_key=key,
                )
                try:
                    store_app_cache_state(
                        "daily_playbooks_status", {"last_run": time.time()}
                    )
                except Exception as save_err:
                    logger.warning(
                        f"Cron: Error saving playbooks cache status: {save_err}"
                    )
                p_duration = time.time() - playbook_start
                logger.info(f"Cron: Playbook generation completed in {p_duration:.2f}s")
            except Exception as e:
                logger.error(f"Cron: Playbook generation failed: {e}", exc_info=True)

        # 3. Calculate hourly correlation matrix using the updated telemetry
        logger.info(
            "Cron: Triggering hourly streamer correlation matrix calculation..."
        )
        try:
            from ag_kaggle_5day.agents.scraper import calculate_hourly_correlation

            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, calculate_hourly_correlation, key)
        except Exception as cov_err:
            logger.error(
                f"Cron: Correlation calculation failed: {cov_err}", exc_info=True
            )

        # 4. Check and run daily exposes if stale
        logger.info("Cron: Checking daily expose status...")
        try:
            from ag_kaggle_5day.agents.advisor import trigger_daily_expose_job

            await trigger_daily_expose_job(api_key=key, check_24h_interval=True)
        except Exception as daily_err:
            logger.warning(
                f"Cron: Daily expose checks failed (proceeding anyway): {daily_err}"
            )

    finally:
        # Keep the sentinel active until the target run duration
        # (default: 15 minutes / 900s) is satisfied
        import sys

        default_duration = 0 if "pytest" in sys.modules else 600
        sentinel_duration = int(
            os.environ.get("SENTINEL_RUN_DURATION", str(default_duration))
        )
        elapsed = time.time() - sentinel_start_time
        if elapsed < sentinel_duration:
            sleep_time = sentinel_duration - elapsed
            logger.info(
                f"Cron: Sentinel has been active for {elapsed:.2f}s. "
                f"Keeping sentinel active for another {sleep_time:.2f}s "
                "to monitor chat events..."
            )
            await asyncio.sleep(sleep_time)

        # Stop the RaidSentinel task gracefully
        logger.info("Cron: Stopping RaidSentinel background listener...")
        try:
            await stop_raid_sentinel(key)
            await sentinel_task
        except Exception as sentinel_err:
            logger.warning(
                f"Cron: RaidSentinel task completed with error: {sentinel_err}"
            )

    total_duration = time.time() - sentinel_start_time
    logger.info(
        f"Cron: All scheduled tasks completed successfully in {total_duration:.2f}s"
    )


async def run_daily_expose():
    """Executes the daily selection and longform expose generation task."""
    setup_logging()
    load_env()
    logger.info("Cron: Starting scheduled daily expose generation...")
    key = get_effective_key()
    if not key:
        logger.error("Cron: GEMINI_API_KEY environment variable is not set. Aborting.")
        raise ValueError("GEMINI_API_KEY environment variable is required.")

    try:
        from ag_kaggle_5day.agents.advisor import (
            check_and_run_daily_analytics_if_stale,
            trigger_daily_expose_job,
        )

        # 1. Run daily analytics aggregation if stale (ensure fabric is fresh)
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                check_and_run_daily_analytics_if_stale,
                key,
            )
        except Exception as analytic_err:
            logger.warning(
                "Cron: Analytics pre-requisite check failed "
                f"(proceeding anyway): {analytic_err}"
            )

        # 2. Run the daily expose generation
        start_time = time.time()
        await trigger_daily_expose_job(api_key=key)
        duration = time.time() - start_time
        logger.info(f"Cron: Daily expose completed in {duration:.2f}s")
    except Exception as e:
        logger.error(f"Cron: Daily expose failed: {e}", exc_info=True)
        raise


async def run_daily_analytics():
    """Executes the daily streamer analytics aggregation and profile fabric build."""
    setup_logging()
    load_env()
    logger.info("Cron: Starting daily analytics aggregation and clustering...")
    key = get_effective_key()
    if not key:
        logger.error("Cron: GEMINI_API_KEY environment variable is not set. Aborting.")
        raise ValueError("GEMINI_API_KEY environment variable is required.")

    try:
        from ag_kaggle_5day.agents.advisor import run_daily_analytics_aggregation

        start_time = time.time()
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            run_daily_analytics_aggregation,
            key,
        )

        logger.info(
            "Cron: Daily analytics: triggering daily ecosystem/starmap analytics..."
        )
        from ag_kaggle_5day.agents.scraper import calculate_daily_ecosystem_analytics

        await loop.run_in_executor(
            None,
            calculate_daily_ecosystem_analytics,
            key,
        )

        duration = time.time() - start_time
        logger.info(
            f"Cron: Daily analytics aggregation and ecosystem mapping "
            f"completed in {duration:.2f}s"
        )
    except Exception as e:
        logger.error(f"Cron: Daily analytics aggregation failed: {e}", exc_info=True)
        raise


async def run_db_seed():
    """Executes the Firestore cache database seeding manually."""
    setup_logging()
    load_env()
    logger.info("Cron: Starting database seeding...")
    try:
        from ag_kaggle_5day.agents.advisor import seed_firestore_cache_if_empty

        seed_firestore_cache_if_empty(force=True)
        logger.info("Cron: Database seeding completed successfully.")
    except Exception as e:
        logger.error(f"Cron: Database seeding failed: {e}", exc_info=True)
        raise


def main():
    """Main CLI entry point for the cron job."""
    import sys

    task = "hourly"
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ("daily-expose", "--task=daily-expose"):
            task = "daily-expose"
        elif arg in ("daily-analytics", "--task=daily-analytics"):
            task = "daily-analytics"
        elif arg in ("seed", "--task=seed"):
            task = "seed"

    if task == "daily-expose":
        asyncio.run(run_daily_expose())
    elif task == "daily-analytics":
        asyncio.run(run_daily_analytics())
    elif task == "seed":
        asyncio.run(run_db_seed())
    else:
        asyncio.run(run_cron_refresh())


if __name__ == "__main__":
    main()
