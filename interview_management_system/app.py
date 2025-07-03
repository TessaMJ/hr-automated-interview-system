# /interview_management_system/app.py

import logging
from flask import Flask, request, jsonify

from twilio.twiml.messaging_response import MessagingResponse

from interview_management_system import config
from interview_management_system import database
from interview_management_system.database import init_db
from interview_management_system.services import interview_service
from interview_management_system.utils import normalize_phone_number
from datetime import datetime, timedelta, timezone 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


app = Flask(__name__)
app.config['SECRET_KEY'] = config.SECRET_KEY


@app.route('/webhook/whatsapp', methods=['POST'])
def whatsapp_webhook():
   
    incoming_msg = request.form.get('Body', '').strip()
    from_number_raw = request.form.get('From', '')    
    from_number = from_number_raw.replace('whatsapp:', '')   
    logger.info(f"Received WhatsApp message from {from_number}: '{incoming_msg}'")
    interview_service.handle_incoming_whatsapp(from_number, incoming_msg)
    logger.info(f"--- Received raw WhatsApp message ---") 
    logger.info(f"From: {from_number_raw}, Body: '{incoming_msg}'")

    try:
        logger.info("Manually calling handle_incoming_whatsapp for debug...")
        print(f"DEBUG: Would have called handle_incoming_whatsapp({from_number}, {incoming_msg})")

    except Exception as e:
        logger.error(f"Error during webhook processing: {e}", exc_info=True)
        return str(MessagingResponse()), 500
    return str(MessagingResponse())


@app.route('/api/v1/start-shortlisting', methods=['POST'])
def start_shortlisting_route():

    api_key = request.headers.get('X-API-KEY')
    if not api_key or api_key != config.INTERNAL_API_KEY:
        logger.warning("Unauthorized access attempt to /start-shortlisting.")
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        logger.info("Authorized request received to start shortlisting.")
        result = interview_service.start_shortlisting_and_interview_process()
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error during /start-shortlisting: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500

@app.route('/api/v1/init-db', methods=['POST'])
def run_db_initialization():

    api_key = request.headers.get('X-API-KEY')
    if not api_key or api_key != config.INTERNAL_API_KEY:
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        logger.info("Running database initialization...")
        init_db()
        return jsonify({'message': 'Database initialized successfully.'}), 200
    except Exception as e:
        logger.error(f"Error during database initialization: {e}", exc_info=True)
        return jsonify({'error': 'Database initialization failed.'}), 500

@app.route('/api/v1/debug-create-past-interview', methods=['POST'])
def debug_create_past_interview_route():
   
    api_key = request.headers.get('X-API-KEY')
    if not api_key or api_key != config.INTERNAL_API_KEY:
        logger.warning("Unauthorized access attempt to /debug-create-past-interview.")
        return jsonify({'error': 'Unauthorized'}), 401

    try:
        logger.info("Authorized request received to create a debug past interview.")
        candidate = database.get_top_candidates_for_shortlisting()
        if not candidate:
            return jsonify({"success": False, "message": "No available candidates for debug interview."}), 400
        candidate = candidate[0] 
        interviewer = database.get_available_interviewer()
        if not interviewer:
            return jsonify({"success": False, "message": "No available interviewers for debug interview."}), 400
        interview_id = database.create_interview(
            candidate_id=candidate['id'],
            interviewer_id=interviewer['id'],
            status='scheduled' 
        )

        past_time = datetime.now(timezone.utc) - timedelta(minutes=5)
        
        database.update_interview_details(interview_id, {
            'scheduled_time': past_time.isoformat(),
            'status': 'scheduled',
            'reminders_sent_count': 0,
            'last_reminder_sent_at': None,
            'email_poll_attempts': 0,
            'last_email_polled_at': None
        })

        logger.info(f"Debug interview {interview_id} created for {candidate['name']} with {interviewer['name']} at {past_time.isoformat()}")
        return jsonify({
            "success": True,
            "message": f"Debug interview {interview_id} created and set to 'scheduled' in the past. Check scheduler logs.",
            "interview_id": interview_id
        }), 200
    except Exception as e:
        logger.error(f"Error during /debug-create-past-interview: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500
    
@app.route('/api/v1/debug-get-interview/<int:interview_id>', methods=['GET'])
def debug_get_interview_details(interview_id):

    api_key = request.headers.get('X-API-KEY')
    if not api_key or api_key != config.INTERNAL_API_KEY:
        logger.warning(f"Unauthorized access attempt to /debug-get-interview/{interview_id}.")
        return jsonify({'error': 'Unauthorized'}), 401
    
    try:
        query = """
            SELECT 
                i.id, i.status, i.scheduled_time, i.reminders_sent_count, 
                i.last_reminder_sent_at, i.email_poll_attempts, i.last_email_polled_at,
                c.name AS candidate_name, iv.name AS interviewer_name
            FROM interviews i
            LEFT JOIN candidates c ON i.candidate_id = c.id
            LEFT JOIN interviewers iv ON i.interviewer_id = iv.id
            WHERE i.id = %s;
        """
        
        with database.get_db_connection() as conn:
            with conn.cursor(cursor_factory=database.RealDictCursor) as cur:
                cur.execute(query, (interview_id,))
                interview_data = cur.fetchone()
        
        if interview_data:
            if 'scheduled_time' in interview_data and interview_data['scheduled_time']:
                interview_data['scheduled_time'] = interview_data['scheduled_time'].isoformat()
            if 'last_reminder_sent_at' in interview_data and interview_data['last_reminder_sent_at']:
                interview_data['last_reminder_sent_at'] = interview_data['last_reminder_sent_at'].isoformat()
            if 'last_email_polled_at' in interview_data and interview_data['last_email_polled_at']:
                interview_data['last_email_polled_at'] = interview_data['last_email_polled_at'].isoformat()
            
            logger.info(f"Fetched debug interview details for ID {interview_id}: {interview_data}")
            return jsonify(interview_data), 200
        else:
            logger.warning(f"Attempted to fetch non-existent interview ID: {interview_id}")
            return jsonify({'message': f'Interview with ID {interview_id} not found.'}), 404
    except Exception as e:
        logger.error(f"Error fetching debug interview details for ID {interview_id}: {e}", exc_info=True)
        return jsonify({'error': 'An internal server error occurred.'}), 500

if __name__ == '__main__':
    logger.info("Starting HR Interview Scheduler application...")
    app.run(host='0.0.0.0', port=config.PORT, debug=config.DEBUG)
