# /scheduler.py

import time
import logging
from datetime import datetime, timedelta 
import pytz
from interview_management_system.services import interview_service
from interview_management_system.config import FEEDBACK_CHECK_INTERVAL_MINUTES, EMAIL_POLL_INTERVAL_MINUTES

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_background_scheduler():
    logger.info("Starting background HR Interview Scheduler tasks...")
    time.sleep(10) 

    last_feedback_check = datetime.now(pytz.utc) - timedelta(minutes=FEEDBACK_CHECK_INTERVAL_MINUTES + 1)
    last_email_poll = datetime.now(pytz.utc) - timedelta(minutes=EMAIL_POLL_INTERVAL_MINUTES + 1)

    while True:
        try:
            current_time = datetime.now(pytz.utc)
            if (current_time - last_feedback_check).total_seconds() >= FEEDBACK_CHECK_INTERVAL_MINUTES * 60:
                logger.info(f"Running scheduled task: Checking for completed interviews at {current_time.isoformat()} UTC...")
                interview_service.check_for_completed_interviews_and_send_reminders()
                last_feedback_check = current_time
            if (current_time - last_email_poll).total_seconds() >= EMAIL_POLL_INTERVAL_MINUTES * 60:
                logger.info(f"Running scheduled task: Polling interviewer feedback emails at {current_time.isoformat()} UTC...")
                interview_service.poll_interviewer_emails_for_feedback()
                last_email_poll = current_time

        except Exception as e:
            logger.error(f"An error occurred in the scheduler loop: {e}", exc_info=True)

        time.sleep(30) 

if __name__ == '__main__':
    run_background_scheduler()