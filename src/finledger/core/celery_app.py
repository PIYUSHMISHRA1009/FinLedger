"""
FinLedger Celery Application

Background task processing for fraud evaluation, reconciliation, webhooks, etc.
"""

from celery import Celery
from celery.schedules import crontab

from finledger.api.config.settings import get_settings

settings = get_settings()

# Create Celery app
celery_app = Celery(
    "finledger",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=[
        "finledger.core.tasks.fraud",
        "finledger.core.tasks.reconciliation",
        "finledger.core.tasks.webhooks",
        "finledger.core.tasks.cleanup",
    ],
)

# Celery configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    
    # Timezone
    timezone="UTC",
    enable_utc=True,
    
    # Task execution
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
    task_time_limit=300,  # 5 minutes hard limit
    task_soft_time_limit=240,  # 4 minutes soft limit
    
    # Worker configuration
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    worker_disable_rate_limits=False,
    
    # Result backend
    result_expires=3600,  # 1 hour
    result_compression="gzip",
    
    # Beat schedule
    beat_schedule={
        "daily-reconciliation": {
            "task": "finledger.core.tasks.reconciliation.run_daily_reconciliation",
            "schedule": crontab(hour=2, minute=0),  # 2 AM UTC daily
        },
        "cleanup-expired-tokens": {
            "task": "finledger.core.tasks.cleanup.cleanup_expired_tokens",
            "schedule": crontab(hour=3, minute=0),  # 3 AM UTC daily
        },
        "cleanup-idempotency-keys": {
            "task": "finledger.core.tasks.cleanup.cleanup_idempotency_keys",
            "schedule": crontab(hour=4, minute=0),  # 4 AM UTC daily
        },
        "cleanup-velocity-counters": {
            "task": "finledger.core.tasks.cleanup.cleanup_velocity_counters",
            "schedule": crontab(minute=0, hour="*"),  # Every hour
        },
        "send-pending-webhooks": {
            "task": "finledger.core.tasks.webhooks.send_pending_webhooks",
            "schedule": crontab(minute="*/5"),  # Every 5 minutes
        },
    },
    
    # Monitoring
    worker_send_task_events=True,
    task_send_sent_event=True,
    
    # Error handling
    task_autoretry_for=(Exception,),
    task_retry_backoff=True,
    task_retry_backoff_max=600,
    task_retry_jitter=True,
)

# Auto-discover tasks
celery_app.autodiscover_tasks()


@celery_app.task(bind=True, ignore_result=True)
def debug_task(self):
    """Debug task for testing."""
    print(f"Request: {self.request!r}")