# worker.py
import os
from apscheduler.schedulers.blocking import BlockingScheduler
from app import check_and_send_reminders, app

if __name__ == "__main__":
    # Use a blocking scheduler in a separate worker service
    scheduler = BlockingScheduler()
    # run every 30 seconds (same as your app’s config)
    scheduler.add_job(check_and_send_reminders, "interval", seconds=30, id="reminder_job", max_instances=1)
    app.logger.info("Background worker started.")
    scheduler.start()
