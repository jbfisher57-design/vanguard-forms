from celery.schedules import crontab
from app.workers.celery_app import celery_app

celery_app.conf.beat_schedule = {
    "nightly-sync": {
        "task": "app.workers.sync_tasks.nightly_sync_task",
        "schedule": crontab(hour=2, minute=0),  # 2am UTC daily
    },
}
