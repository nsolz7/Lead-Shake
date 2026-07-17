from celery import Celery

from app.config import get_settings


settings = get_settings()
celery_app = Celery("lead_intelligence", broker=settings.redis_url, backend=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="America/New_York",
    enable_utc=True,
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "refresh-source-health-daily": {
            "task": "app.tasks.refresh_source_health",
            "schedule": 86400.0,
        },
        "rescore-all-nightly": {
            "task": "app.tasks.rescore_all_accounts",
            "schedule": 86400.0,
        },
        "queue-due-research": {
            "task": "app.tasks.queue_due_research",
            "schedule": 900.0,
        },
        "sync-google-calendars": {
            "task": "app.tasks.sync_google_calendars",
            "schedule": float(settings.calendar_sync_interval_seconds),
        },
    },
)
celery_app.autodiscover_tasks(["app"])
