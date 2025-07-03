# /interview_management_system/database.py

import logging
import psycopg2
from psycopg2.pool import SimpleConnectionPool
from psycopg2.extras import RealDictCursor
from contextlib import contextmanager
from typing import List, Dict, Any, Optional
import datetime

from interview_management_system.config import (
    DATABASE_URL,
    MINIMUM_SCORE,
    TOP_N_CANDIDATES,
    FEEDBACK_REMINDER_INITIAL_DELAY_MINUTES,   
    FEEDBACK_REMINDER_FOLLOW_UP_DELAY_MINUTES, 
    MAX_FEEDBACK_REMINDERS,
    EMAIL_POLL_INTERVAL_MINUTES,
    MAX_FEEDBACK_EMAIL_POLLS
)

logger = logging.getLogger(__name__)

if not DATABASE_URL:
    logger.critical("DATABASE_URL is not configured. The application cannot start.")
    raise ValueError("DATABASE_URL is not set in the environment.")

db_pool = SimpleConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)

@contextmanager
def get_db_connection():
    conn = db_pool.getconn()
    try:
        yield conn
    finally:
        db_pool.putconn(conn)


def update_slot_status(slot_id: int, status: str):
    
    query = "UPDATE interview_slots SET status = %s WHERE id = %s;"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (status, slot_id))
            conn.commit()

def deactivate_offered_slots(interview_id: int):
    
    query = "UPDATE interview_slots SET status = 'rejected' WHERE interview_id = %s AND status = 'offered';"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (interview_id,))
            conn.commit()

def init_db():
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            logger.info("Initializing database schema...")

            cur.execute("DROP TABLE IF EXISTS interview_slots, interviews, candidates, interviewers CASCADE;")

            cur.execute("""
                CREATE TABLE candidates (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    whatsapp_number TEXT NOT NULL UNIQUE,
                    cv_score INTEGER NOT NULL DEFAULT 0,
                    status VARCHAR(50) NOT NULL DEFAULT 'applied'
                );
            """)

            cur.execute("""
                CREATE TABLE interviewers (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    whatsapp_number TEXT NOT NULL UNIQUE,
                    is_active BOOLEAN DEFAULT TRUE
                );
            """)

            cur.execute("""
                CREATE TABLE interviews (
                    id SERIAL PRIMARY KEY,
                    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                    interviewer_id INTEGER REFERENCES interviewers(id) ON DELETE SET NULL,
                    status VARCHAR(50) NOT NULL,
                    rejection_count INTEGER NOT NULL DEFAULT 0,
                    reschedule_attempts INTEGER NOT NULL DEFAULT 0,
                    scheduled_time TIMESTAMP WITH TIME ZONE,
                    meet_link TEXT,
                    feedback_summary TEXT,
                    reminders_sent_count INTEGER NOT NULL DEFAULT 0, 
                    last_reminder_sent_at TIMESTAMP WITH TIME ZONE,
                    email_poll_attempts INTEGER NOT NULL DEFAULT 0,
                    last_email_polled_at TIMESTAMP WITH TIME ZONE,
                    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
                );
            """)
            

            cur.execute("""
                CREATE TABLE interview_slots (
                    id SERIAL PRIMARY KEY,
                    interview_id INTEGER NOT NULL REFERENCES interviews(id) ON DELETE CASCADE,
                    slot_time TIMESTAMP WITH TIME ZONE NOT NULL,
                    status VARCHAR(50) NOT NULL DEFAULT 'offered'
                );
            """)
            
            logger.info("Seeding database with sample data...")
            seed_data = {
                "candidates": [
                    ('Alice Johnson', 'tekmar1344@gmail.com', '+919496207169', 92), # Replace with a real test number
                    ('Bob Smith', 'bob.s@example.com', '+14155552672', 85),
                    ('Charlie Brown', 'charlie.b@example.com', '+14155552673', 78),
                    ('Diana Prince', 'diana.p@example.com', '+14155552674', 74), 
                    ('Eva Green', 'eva.g@example.com', '+14155552675', 95)
                ],
                "interviewers": [
                    ('Mike Ross', 'tessamj1344@gmail.com', '+919048617544'), # Replace with a real test number
                    
                ]
            }
            
            cur.executemany(
                "INSERT INTO candidates (name, email, whatsapp_number, cv_score) VALUES (%s, %s, %s, %s)",
                seed_data["candidates"]
            )
            cur.executemany(
                "INSERT INTO interviewers (name, email, whatsapp_number) VALUES (%s, %s, %s)",
                seed_data["interviewers"]
            )
            
            conn.commit()
            logger.info("Database initialized and seeded successfully.")

def get_interview_awaiting_interviewer_confirmation(interviewer_id: int) -> Optional[Dict[str, Any]]:

    query = """
        SELECT 
            i.*, 
            c.name as candidate_name, 
            c.email as candidate_email,
            c.whatsapp_number as candidate_whatsapp_number,
            iv.name as interviewer_name, 
            iv.email as interviewer_email,
            iv.whatsapp_number as interviewer_whatsapp_number
        FROM interviews i
        JOIN candidates c ON i.candidate_id = c.id
        JOIN interviewers iv ON i.interviewer_id = iv.id
        WHERE i.interviewer_id = %s AND i.status = 'awaiting_interviewer_confirmation'
        ORDER BY i.updated_at DESC
        LIMIT 1;
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (interviewer_id,))
            return cur.fetchone()

def get_latest_interview_for_candidate(candidate_id: int) -> Optional[Dict[str, Any]]:
 
    query = """
        SELECT
            i.id, i.candidate_id, i.interviewer_id, i.status, i.scheduled_time, i.meet_link,
            i.reschedule_attempts, i.rejection_count, i.feedback_summary,
            c.name AS candidate_name, c.email AS candidate_email,
            c.whatsapp_number AS candidate_whatsapp_number,
            iv.name AS interviewer_name, iv.email AS interviewer_email,
            iv.whatsapp_number AS interviewer_whatsapp_number
        FROM interviews i
        JOIN candidates c ON i.candidate_id = c.id
        LEFT JOIN interviewers iv ON i.interviewer_id = iv.id -- LEFT JOIN in case interviewer is null
        WHERE i.candidate_id = %s
        ORDER BY i.created_at DESC
        LIMIT 1;
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (candidate_id,))
            return cur.fetchone()

def get_latest_interview_for_interviewer(interviewer_id: int) -> Optional[Dict[str, Any]]:

    query = """
        SELECT
            i.id, i.candidate_id, i.interviewer_id, i.status, i.scheduled_time, i.meet_link,
            i.reschedule_attempts, i.rejection_count, i.feedback_summary,
            c.name AS candidate_name, c.email AS candidate_email,
            c.whatsapp_number AS candidate_whatsapp_number,
            iv.name AS interviewer_name, iv.email AS interviewer_email,
            iv.whatsapp_number AS interviewer_whatsapp_number
        FROM interviews i
        JOIN interviewers iv ON i.interviewer_id = iv.id
        LEFT JOIN candidates c ON i.candidate_id = c.id -- LEFT JOIN in case candidate is null (though unlikely in this flow)
        WHERE i.interviewer_id = %s
        ORDER BY i.created_at DESC
        LIMIT 1;
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (interviewer_id,))
            return cur.fetchone()

def get_top_candidates_for_shortlisting() -> List[Dict[str, Any]]:
    query = """
        SELECT id, name, email, whatsapp_number, cv_score
        FROM candidates
        WHERE status = 'applied' AND cv_score >= %s
        ORDER BY cv_score DESC
        LIMIT %s;
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (MINIMUM_SCORE, TOP_N_CANDIDATES))
            return cur.fetchall()

def get_available_interviewer(exclude_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    query = """
        SELECT id, name, email, whatsapp_number
        FROM interviewers
        WHERE is_active = TRUE
    """
    params = []
    if exclude_id:
        query += " AND id != %s"
        params.append(exclude_id)
    
    query += " ORDER BY RANDOM() LIMIT 1;"
    
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            return cur.fetchone()

def create_interview(candidate_id: int, interviewer_id: int, status: str) -> int:
    query = """
        INSERT INTO interviews (candidate_id, interviewer_id, status)
        VALUES (%s, %s, %s) RETURNING id;
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (candidate_id, interviewer_id, status))
            interview_id = cur.fetchone()[0]
            conn.commit()
            return interview_id

def add_interview_slots(interview_id: int, slots: List[str]):
    query = "INSERT INTO interview_slots (interview_id, slot_time) VALUES (%s, %s);"
    slot_data = [(interview_id, slot) for slot in slots]
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(query, slot_data)
            conn.commit()

def update_candidate_status(candidate_id: int, status: str):
    query = "UPDATE candidates SET status = %s WHERE id = %s;"
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, (status, candidate_id))
            conn.commit()

def get_user_by_whatsapp(whatsapp_number: str) -> Optional[Dict[str, Any]]:
    query = """
        SELECT id, name, 'candidate' as user_type FROM candidates WHERE whatsapp_number = %s
        UNION ALL
        SELECT id, name, 'interviewer' as user_type FROM interviewers WHERE whatsapp_number = %s;
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (whatsapp_number, whatsapp_number))
            return cur.fetchone()

def get_interview_by_user_id(user_id: int, user_type: str) -> Optional[Dict[str, Any]]:
    if user_type == 'candidate':
        field = 'i.candidate_id'  
    elif user_type == 'interviewer':
        field = 'i.interviewer_id'
    else:
        return None

    query = f"""
        SELECT 
            i.*, 
            c.name as candidate_name, 
            c.email as candidate_email,
            c.whatsapp_number as candidate_whatsapp_number,
            iv.name as interviewer_name, 
            iv.email as interviewer_email,
            iv.whatsapp_number as interviewer_whatsapp_number
        FROM interviews i
        JOIN candidates c ON i.candidate_id = c.id
        JOIN interviewers iv ON i.interviewer_id = iv.id
        WHERE {field} = %s AND i.status NOT IN ('completed_selected', 'completed_rejected', 'cancelled_no_slots', 'cancelled_by_candidate')
        ORDER BY i.created_at DESC
        LIMIT 1;
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (user_id,))
            return cur.fetchone()

def get_offered_slots_for_interview(interview_id: int) -> List[Dict]:
    query = """
        SELECT id, slot_time, status
        FROM interview_slots
        WHERE interview_id = %s AND status = 'offered'
        ORDER BY slot_time;
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (interview_id,))
            return [
                {
                    'id': slot['id'],
                    'slot_time': slot['slot_time'],
                    'status': slot['status']
                } for slot in cur.fetchall()
            ]
def update_interview_details(interview_id: int, updates: Dict[str, Any]):
    set_clauses = [f"{key} = %s" for key in updates.keys()]
    values = list(updates.values()) + [interview_id]
    
    query = f"""
        UPDATE interviews SET {', '.join(set_clauses)}, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s;
    """
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, values)
            conn.commit()

def get_interviews_for_feedback_processing() -> List[Dict[str, Any]]:
 
    query = f"""
        SELECT
            i.id,
            i.status,
            i.scheduled_time,
            i.last_reminder_sent_at,
            i.reminders_sent_count,
            c.name AS candidate_name,
            c.email AS candidate_email,
            c.whatsapp_number AS candidate_whatsapp_number,
            iv.name AS interviewer_name,
            iv.email AS interviewer_email,
            iv.whatsapp_number AS interviewer_whatsapp_number
        FROM interviews i
        JOIN candidates c ON i.candidate_id = c.id
        JOIN interviewers iv ON i.interviewer_id = iv.id
        WHERE
            -- Condition 1: Interview is scheduled and its scheduled time plus initial delay is in the past
            (i.status = 'scheduled' AND i.scheduled_time < NOW() - INTERVAL '{FEEDBACK_REMINDER_INITIAL_DELAY_MINUTES} minutes')
            OR
            -- Condition 2: Interview is awaiting feedback, hasn't hit max reminders, and enough time has passed since last reminder
            (i.status = 'awaiting_feedback' 
             AND i.reminders_sent_count < {MAX_FEEDBACK_REMINDERS}
             AND i.last_reminder_sent_at IS NOT NULL AND i.last_reminder_sent_at < NOW() - INTERVAL '{FEEDBACK_REMINDER_FOLLOW_UP_DELAY_MINUTES} minutes')
        ORDER BY i.scheduled_time ASC;
    """
    
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            return cur.fetchall()

def get_interviews_awaiting_feedback_email_poll() -> List[Dict[str, Any]]:
 
    query = f"""
        SELECT
            i.id,
            i.candidate_id,
            i.interviewer_id,
            i.status,
            i.scheduled_time,
            i.feedback_summary,
            i.reminders_sent_count,
            i.last_reminder_sent_at,
            i.email_poll_attempts,
            i.last_email_polled_at,
            c.name AS candidate_name,
            c.email AS candidate_email,
            c.whatsapp_number AS candidate_whatsapp_number,
            iv.name AS interviewer_name,
            iv.email AS interviewer_email,
            iv.whatsapp_number AS interviewer_whatsapp_number
        FROM interviews i
        JOIN candidates c ON i.candidate_id = c.id
        JOIN interviewers iv ON i.interviewer_id = iv.id
        WHERE
            i.status = 'awaiting_feedback'
            AND i.email_poll_attempts < {MAX_FEEDBACK_EMAIL_POLLS}
            AND (i.last_email_polled_at IS NULL 
                 OR i.last_email_polled_at < NOW() - INTERVAL '{EMAIL_POLL_INTERVAL_MINUTES} minutes')
        ORDER BY i.scheduled_time DESC;
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query)
            return cur.fetchall()

def get_all_slots_for_interview(interview_id: int) -> List[Dict[str, Any]]:

    query = """
        SELECT id, slot_time, status
        FROM interview_slots
        WHERE interview_id = %s
        ORDER BY slot_time;
    """
    with get_db_connection() as conn:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, (interview_id,))
            return [
                {
                    'id': slot['id'],
                    'slot_time': slot['slot_time'], 
                    'status': slot['status']
                } for slot in cur.fetchall()
            ]
