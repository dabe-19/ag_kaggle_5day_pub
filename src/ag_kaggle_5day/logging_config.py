import collections
import datetime
import json
import logging
import time
import traceback

# Custom logging level for agent exposes (severity 25)
EXPOSE_LEVEL_NUM = 25
logging.addLevelName(EXPOSE_LEVEL_NUM, "EXPOSE")


def log_expose(self, message, *args, **kws):
    if self.isEnabledFor(EXPOSE_LEVEL_NUM):
        self._log(EXPOSE_LEVEL_NUM, message, args, **kws)


logging.Logger.expose = log_expose

# Global start time for uptime calculation
APP_START_TIME = time.time()

# Circular buffer to store recent structured logs for agentic checks
LOG_BUFFER = collections.deque(maxlen=500)


class JSONFormatter(logging.Formatter):
    """
    Formatter to output logs in a structured JSON format suitable for Google
    Cloud Logging.
    """

    def format(self, record):
        severity = record.levelname
        if record.levelno == EXPOSE_LEVEL_NUM:
            severity = "NOTICE"

        log_data = {
            "timestamp": datetime.datetime.fromtimestamp(
                record.created, datetime.timezone.utc
            ).isoformat(),
            "level": record.levelname,
            "severity": severity,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Capture custom dictionary keys passed via 'extra'
        if hasattr(record, "event_type"):
            log_data["event_type"] = record.event_type
        if hasattr(record, "latency_ms"):
            log_data["latency_ms"] = record.latency_ms
        if hasattr(record, "status_code"):
            log_data["status_code"] = record.status_code
        if hasattr(record, "route"):
            log_data["route"] = record.route

        # Capture traceback info if an exception occurred
        if record.exc_info:
            log_data["exception"] = "".join(
                traceback.format_exception(*record.exc_info)
            )

        return json.dumps(log_data)


class CircularBufferHandler(logging.Handler):
    """
    Logging handler that appends structured log dictionaries to an in-memory
    circular buffer.
    """

    def emit(self, record):
        try:
            severity = record.levelname
            if record.levelno == EXPOSE_LEVEL_NUM:
                severity = "NOTICE"
            # Create a structured dict for the log
            log_entry = {
                "timestamp": datetime.datetime.fromtimestamp(
                    record.created, datetime.timezone.utc
                ).isoformat(),
                "level": record.levelname,
                "severity": severity,
                "logger": record.name,
                "message": record.getMessage(),
                "event_type": getattr(record, "event_type", "general"),
            }
            if hasattr(record, "latency_ms"):
                log_entry["latency_ms"] = record.latency_ms
            if hasattr(record, "status_code"):
                log_entry["status_code"] = record.status_code
            if hasattr(record, "route"):
                log_entry["route"] = record.route
            if record.exc_info:
                log_entry["exception"] = "".join(
                    traceback.format_exception(*record.exc_info)
                )

            LOG_BUFFER.append(log_entry)
        except Exception:
            self.handleError(record)


def setup_logging(log_level=None):
    """Sets up the centralized structured logging pipeline using dictConfig."""
    import logging.config
    import os

    if log_level is None:
        log_level = os.environ.get("LOG_LEVEL", "INFO")

    numeric_level = getattr(logging, log_level.upper(), logging.INFO)

    logging_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "json": {
                "()": JSONFormatter,
            },
        },
        "handlers": {
            "stdout": {
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
                "formatter": "json",
                "level": numeric_level,
            },
            "buffer": {
                "()": CircularBufferHandler,
                "level": numeric_level,
            },
        },
        "loggers": {
            "": {  # Root logger
                "handlers": ["stdout", "buffer"],
                "level": numeric_level,
            },
            # Subsystem loggers
            "streamer_advisor.twitch": {
                "level": numeric_level,
                "propagate": True,
            },
            "streamer_advisor.youtube": {
                "level": numeric_level,
                "propagate": True,
            },
            "streamer_advisor.agents": {
                "level": numeric_level,
                "propagate": True,
            },
            "streamer_advisor.fastapi": {
                "level": numeric_level,
                "propagate": True,
            },
            # Noisy third-party mutes
            "google.genai": {
                "level": "WARNING",
                "propagate": True,
            },
            "googleapiclient": {
                "level": "WARNING",
                "propagate": True,
            },
            "urllib3": {
                "level": "WARNING",
                "propagate": True,
            },
            "httpx": {
                "level": "WARNING",
                "propagate": True,
            },
            "uvicorn.access": {
                "level": "WARNING",
                "propagate": True,
            },
        },
    }

    logging.config.dictConfig(logging_config)
    logging.getLogger().info("Structured logging pipeline initialized successfully.")


def get_recent_logs(level=None, limit=100):
    """
    Retrieves recent logs from the circular buffer, optionally filtered by
    severity level.
    """
    logs = list(LOG_BUFFER)
    if level:
        logs = [log for log in logs if log["level"].upper() == level.upper()]
    return logs[-limit:]


def get_telemetry_summary():
    """
    Computes health and performance statistics from recent circular log entries.
    """
    uptime = time.time() - APP_START_TIME
    logs = list(LOG_BUFFER)

    # Count errors and exceptions
    total_errors = sum(1 for log in logs if log["level"] in ("ERROR", "CRITICAL"))
    total_warnings = sum(1 for log in logs if log["level"] == "WARNING")

    # API request profiling
    api_logs = [log for log in logs if log["event_type"] == "api_request"]
    total_requests = len(api_logs)

    # Calculate response times
    latencies = [log["latency_ms"] for log in api_logs if "latency_ms" in log]
    avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
    max_latency = max(latencies) if latencies else 0.0

    # Collect statuses
    status_counts = {}
    for log in api_logs:
        sc = log.get("status_code", "unknown")
        status_counts[sc] = status_counts.get(sc, 0) + 1

    return {
        "status": "healthy" if total_errors == 0 else "degraded",
        "uptime_seconds": round(uptime, 2),
        "total_buffered_logs": len(logs),
        "total_requests_recorded": total_requests,
        "average_latency_ms": round(avg_latency, 2),
        "max_latency_ms": round(max_latency, 2),
        "error_count": total_errors,
        "warning_count": total_warnings,
        "status_distribution": status_counts,
    }
