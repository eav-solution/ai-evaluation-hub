from celery import Celery

from app.config import settings

celery_app = Celery(
    "evalhub",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)
celery_app.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    beat_schedule={
        "dispatch-outbox": {
            "task": "app.tasks.dispatch_outbox_events",
            "schedule": 30.0,
        },
        "recover-stale-generation-jobs": {
            "task": "app.tasks.recover_stale_generation_jobs",
            "schedule": 60.0,
        },
    },
)
