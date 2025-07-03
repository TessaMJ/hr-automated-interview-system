# /interview_management_system/config.py

import os
import logging
from dotenv import load_dotenv
import urllib.parse

load_dotenv(override=True)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

SECRET_KEY = os.getenv('SECRET_KEY', 'a-very-secret-key-that-you-should-change')
PORT = int(os.getenv('PORT', 5001))
DEBUG = os.getenv('DEBUG', 'False').lower() == 'true'
INTERNAL_API_KEY = os.environ.get('INTERNAL_API_KEY')
APP_BASE_URL = os.getenv('APP_BASE_URL', 'https://your-ngrok-url.ngrok-free.app')

if APP_BASE_URL == 'https://your-ngrok-url.ngrok-free.app':
    logger.warning("APP_BASE_URL is not set. Please update it with your ngrok URL or deployment URL.")


TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN')
TWILIO_WHATSAPP_NUMBER = os.getenv('TWILIO_WHATSAPP_NUMBER')

if not all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
    logger.error("Twilio credentials (SID, TOKEN, NUMBER) are not fully set in the .env file.")


SMTP_HOST = os.getenv('SMTP_HOST', 'smtp.gmail.com')
SMTP_PORT = int(os.getenv('SMTP_PORT', 587))
EMAIL_USER = os.getenv('EMAIL_USER')
EMAIL_PASSWORD = "zuvjbdfxrymbvkuu"
IMAP_HOST = os.getenv('IMAP_HOST', 'imap.gmail.com')
IMAP_PORT = int(os.getenv('IMAP_PORT', 993))
HR_EMAIL = os.getenv('HR_EMAIL')

if not all([EMAIL_USER, EMAIL_PASSWORD, HR_EMAIL]):
    logger.warning("Email credentials (USER, PASSWORD) or HR_EMAIL are not fully set. Email functionality may be disabled.")


GROQ_API_KEY = os.getenv('GROQ_API_KEY')
AI_PROMPT_CONTEXT_PATH = os.getenv('AI_PROMPT_CONTEXT_PATH', 'prompts/context.txt') 

if not GROQ_API_KEY:
    logger.warning("GROQ_API_KEY is not set. AI functionality will be severely limited or disabled.")

GOOGLE_CLIENT_SECRET_FILE = os.getenv('GOOGLE_CLIENT_SECRET_FILE', 'client_secret.json')
GOOGLE_API_SCOPES = ['https://www.googleapis.com/auth/calendar']
GOOGLE_TOKEN_FILE = 'token.pickle'


DB_USER = os.getenv('DB_USER')
DB_PASSWORD = os.getenv('DB_PASSWORD')
DB_HOST = os.getenv('DB_HOST')
DB_PORT = os.getenv('DB_PORT', 3002)
DB_NAME = os.getenv('DB_NAME')

if not all([DB_USER, DB_PASSWORD, DB_HOST, DB_NAME]):
    logger.error("Database credentials (USER, PASSWORD, HOST, NAME) are not fully set.")
    DATABASE_URL = None
else:
    encoded_user = urllib.parse.quote_plus(DB_USER)
    encoded_password = urllib.parse.quote_plus(DB_PASSWORD)
    
    
    DATABASE_URL = f"postgresql://{encoded_user}:{encoded_password}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

QA_FILE_PATH = os.getenv('QA_FILE_PATH', 'fallback_responses.txt')

SLOTS_PER_PROPOSAL = int(os.getenv('SLOTS_PER_PROPOSAL', 3))
MAX_INTERVIEWER_REJECTIONS = int(os.getenv('MAX_INTERVIEWER_REJECTIONS', 2))
MAX_CANDIDATE_RESCHEDULE_ATTEMPTS = int(os.getenv('MAX_CANDIDATE_RESCHEDULE_ATTEMPTS', 2))
MINIMUM_SCORE = int(os.getenv('MINIMUM_SCORE', 75))
TOP_N_CANDIDATES = int(os.getenv('TOP_N_CANDIDATES', 3))
FEEDBACK_CHECK_INTERVAL_MINUTES = int(os.getenv('FEEDBACK_CHECK_INTERVAL_MINUTES', 5)) 

FEEDBACK_REMINDER_INITIAL_DELAY_MINUTES = int(os.getenv('FEEDBACK_REMINDER_INITIAL_DELAY_MINUTES', 1))
FEEDBACK_REMINDER_FOLLOW_UP_DELAY_MINUTES = int(os.getenv('FEEDBACK_REMINDER_FOLLOW_UP_DELAY_MINUTES', 120))
MAX_FEEDBACK_REMINDERS = int(os.getenv('MAX_FEEDBACK_REMINDERS', 3))

EMAIL_POLL_INTERVAL_MINUTES = int(os.getenv('EMAIL_POLL_INTERVAL_MINUTES', 1))
GMAIL_FEEDBACK_SUBJECT_KEYWORD = os.getenv('GMAIL_FEEDBACK_SUBJECT_KEYWORD', "Feedback")
MAX_FEEDBACK_EMAIL_POLLS = int(os.getenv('MAX_FEEDBACK_EMAIL_POLLS', 5))