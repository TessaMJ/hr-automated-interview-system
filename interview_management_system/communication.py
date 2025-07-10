# interview_management_system/communication.py 

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import List, Dict, Optional
from datetime import datetime
from twilio.rest import Client
from twilio.base.exceptions import TwilioRestException
import imaplib
import email
from email.header import decode_header
import random

from interview_management_system.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER,
    EMAIL_USER,
    EMAIL_PASSWORD,
    SMTP_HOST,
    SMTP_PORT,
    HR_EMAIL, 
    IMAP_HOST,
    IMAP_PORT
)
from interview_management_system.utils import format_datetime_for_display, normalize_phone_number

logger = logging.getLogger(__name__)

class CommunicationManager:
    def __init__(self):
        self.twilio_client = None
        if all([TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_WHATSAPP_NUMBER]):
            try:
                self.twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
                logger.info("Twilio client initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize Twilio client: {e}", exc_info=True)
        else:
            logger.warning("Twilio credentials are not fully configured. WhatsApp messaging will be disabled.")

        self.imap_client = None
        if not all([EMAIL_USER, EMAIL_PASSWORD, IMAP_HOST, IMAP_PORT]):
            logger.warning("IMAP credentials are not fully configured. Email polling will be disabled.")


    def _send_whatsapp(self, to_number: str, body: str) -> bool:
        if not self.twilio_client:
            logger.error(f"Cannot send message to {to_number}: Twilio client is not initialized.")
            return False

        try:
            from_number = f'whatsapp:{TWILIO_WHATSAPP_NUMBER}'
            to_number_normalized = f'whatsapp:{normalize_phone_number(to_number)}'

            message = self.twilio_client.messages.create(from_=from_number, body=body, to=to_number_normalized)
            logger.info(f"Successfully sent WhatsApp message to {to_number_normalized}. SID: {message.sid}")
            return True
        except TwilioRestException as e:
            logger.error(f"Twilio API error sending message to {to_number}: {e}", exc_info=True)
            return False


    def _send_email(self, to_email: str, subject: str, body: str, interview_id: Optional[int] = None) -> bool:
        if not all([EMAIL_USER, EMAIL_PASSWORD, SMTP_HOST, SMTP_PORT]):
            logger.error("Email sending credentials not configured. Cannot send email.")
            return False

        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = None
        try:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
            server.starttls()
            server.login(EMAIL_USER, EMAIL_PASSWORD)
            server.send_message(msg)
            logger.info(f"Email sent successfully to {to_email} for interview {interview_id}.")
            return True
        except smtplib.SMTPAuthenticationError as e:
            logger.error(f"Failed to authenticate with SMTP server for {to_email}. Check EMAIL_USER/EMAIL_PASSWORD and App Passwords. Error: {e}", exc_info=True)
            return False
        except Exception as e:
            logger.error(f"Failed to send email to {to_email} for interview {interview_id}: {e}", exc_info=True)
            return False
        finally:
            if server:
                server.quit()


    def _connect_imap(self) -> bool:
        if not all([EMAIL_USER, EMAIL_PASSWORD, IMAP_HOST, IMAP_PORT]):
            logger.error("IMAP credentials are not fully configured. Cannot connect to IMAP.")
            return False

        if self.imap_client:
            try:
                self.imap_client.noop()
                return True
            except (imaplib.IMAP4.error, ConnectionResetError, OSError) as e:
                logger.warning(f"IMAP connection stale or lost, attempting to reconnect. Error: {e}")
                self.imap_client = None

        if not self.imap_client:
            try:
                self.imap_client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
                self.imap_client.login(EMAIL_USER, EMAIL_PASSWORD)
                logger.info("IMAP client re-connected and logged in successfully for current operation.")
                return True
            except imaplib.IMAP4.error as e:
                logger.error(f"IMAP login failed. Check EMAIL_USER/EMAIL_PASSWORD and App Passwords. Error: {e}", exc_info=True)
                self.imap_client = None
                return False
            except Exception as e:
                logger.error(f"Failed to establish IMAP connection: {e}", exc_info=True)
                self.imap_client = None
                return False
        return False


    def fetch_feedback_emails(self, email_address: str, subject_keyword: str) -> List[str]:
        logger.info(f"Attempting to fetch emails for feedback (real IMAP) for {email_address} with keyword '{subject_keyword}'")

        temp_imap_client = None
        email_bodies = []

        try:
            if not all([EMAIL_USER, EMAIL_PASSWORD, IMAP_HOST, IMAP_PORT]):
                logger.error("IMAP credentials not fully configured in .env. Cannot fetch emails.")
                return []

            temp_imap_client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            temp_imap_client.login(EMAIL_USER, EMAIL_PASSWORD)
            logger.debug("IMAP client connected and logged in for this fetch operation.")

            temp_imap_client.select('inbox')

            search_queries_to_try = [
                b'UNSEEN SUBJECT "[Interview ID:"',
                b'UNSEEN FROM "' + email_address.encode('utf-8') + b'"',
                 b'UNSEEN SUBJECT "' + subject_keyword.encode('utf-8') + b'"',
            ]

            email_ids = []
            search_successful = False

            for query_bytes in search_queries_to_try:
                logger.debug(f"Attempting IMAP search with query: {query_bytes.decode('utf-8')}")
                try:
                    status, email_ids_raw = temp_imap_client.search(None, query_bytes)

                    if status == 'OK' and email_ids_raw and email_ids_raw[0]:
                         email_ids = email_ids_raw
                         search_successful = True
                         logger.debug(f"IMAP search found {len(email_ids[0].split())} emails with query: {query_bytes.decode('utf-8')}")
                         break
                    elif status != 'OK':
                         logger.warning(f"IMAP search failed with status: {status}, Data: {email_ids_raw} for query: {query_bytes.decode('utf-8')}")
                    else:
                         logger.debug(f"IMAP search returned no results for query: {query_bytes.decode('utf-8')}")

                except imaplib.IMAP4.error as e:
                     logger.warning(f"IMAP search query failed syntax/protocol. Error: {e} for query: {query_bytes.decode('utf-8')}")
                except Exception as e:
                     logger.error(f"Unexpected error during IMAP search attempt for query: {query_bytes.decode('utf-8')}: {e}")

            if not search_successful:
                logger.info(f"IMAP search returned no email IDs matching any criteria tested for: FROM='{email_address}', SUBJECT='{subject_keyword}'")
                return []

            for num_bytes in email_ids[0].split():
                num = num_bytes.decode('utf-8')

                logger.debug(f"Fetching details for email ID: {num}")
                status, data = temp_imap_client.fetch(num, '(RFC822)')

                if status != 'OK' or not data or not data[0] or not data[0][1]:
                    logger.error(f"IMAP fetch failed for email {num}. Status: {status}, Data structure unexpected.")
                    continue

                raw_email = data[0][1]

                logger.debug(f"Raw email data for ID {num}:\n---START RAW---\n{raw_email.decode('utf-8', errors='ignore')[:1000]}...\n---END RAW---")

                try:
                    msg = email.message_from_bytes(raw_email)

                    subject_decoded = None
                    try:
                        decoded_parts = decode_header(msg.get('Subject', ''))
                        subject_decoded = ''.join([
                            s.decode(charset if charset else 'utf-8') if isinstance(s, bytes) else s
                            for s, charset in decoded_parts
                        ])
                    except Exception as e:
                        logger.warning(f"Could not decode email subject for email {num}: {e}")
                        subject_decoded = msg.get('Subject', 'N/A')

                    from_decoded = msg.get('From', 'N/A')

                    logger.debug(f"Processing email {num} - Subject: '{subject_decoded}' From: '{from_decoded}'")

                    body = None
                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = part.get_content_type()
                            cdispo = str(part.get('Content-Disposition'))

                            if ctype == 'text/plain' and 'attachment' not in cdispo:
                                try:
                                    body = part.get_payload(decode=True)
                                    charset = part.get_content_charset()
                                    if charset is None:
                                        try:
                                            body = body.decode('utf-8', errors='ignore')
                                        except:
                                            try:
                                                body = body.decode('latin-1', errors='ignore')
                                            except:
                                                body = body.decode(errors='ignore')
                                    else:
                                        body = body.decode(charset, errors='ignore')

                                    email_bodies.append(body)
                                    temp_imap_client.store(num, '+FLAGS', '\\Seen')
                                    logger.debug(f"Marked email {num} as Seen.")
                                    break
                                except Exception as decode_e:
                                    logger.warning(f"Failed to decode part of email {num}: {decode_e}")
                    else:
                        try:
                            body = msg.get_payload(decode=True)
                            charset = msg.get_content_charset()
                            if charset is None:
                                try:
                                    body = body.decode('utf-8', errors='ignore')
                                except:
                                     body = body.decode(errors='ignore')
                            else:
                                body = body.decode(charset, errors='ignore')

                            email_bodies.append(body)
                            temp_imap_client.store(num, '+FLAGS', '\\Seen')
                            logger.debug(f"Marked email {num} as Seen.")
                        except Exception as decode_e:
                            logger.warning(f"Failed to decode non-multipart email {num}: {decode_e}")

                    if not body:
                        logger.warning(f"Could not extract plain text body from email {num}. Skipping.")

                except Exception as e:
                     logger.error(f"Unexpected error during parsing email {num}: {e}", exc_info=True)


            return email_bodies

        except imaplib.IMAP4.error as e:
            logger.error(f"IMAP operation failed during fetch (check credentials/server permissions). Error: {e}", exc_info=True)
            return []
        except Exception as e:
            logger.error(f"An unexpected error occurred during IMAP email fetch: {e}", exc_info=True)
            return []
        finally:
            if temp_imap_client:
                try:
                    temp_imap_client.logout()
                    logger.debug("IMAP client logged out after fetch operation.")
                except Exception as e:
                    logger.warning(f"Error logging out from IMAP: {e}")

    def send_ai_generated_message(self, to_number: str, message: str):
        logger.info(f"Sending AI-generated reply to {to_number}: {message[:50]}...")
        return self._send_whatsapp(to_number, message)

    def send_interviewer_confirmation_acknowledged(self, to_number: str, interviewer_name: str):
        message = (
            f"Hi {interviewer_name},\n\n"
            f"Thank you for confirming the interview. The candidate has been notified, and the meeting link should be in your calendar shortly. ✨"
        )
        return self._send_whatsapp(to_number, message)

    def send_slot_proposal_to_candidate(self, to_number: str, candidate_name: str, slots: List[Dict]):
        slot_texts = [format_datetime_for_display(slot['slot_time']) for slot in slots]
        slot_list_str = "\n".join([f"*{i+1}.* {text}" for i, text in enumerate(slot_texts)])
        message = (
            f"Hello {candidate_name}! 👋\n\n"
            "Thank you for your interest in the position at GNX Solutions!.We are excited to move forward with your application and would like to schedule an interview.\n\n"
            f"🗓️ Please select one of the following time slots:\n{slot_list_str}\n\n"
            "Just reply with the preferred slot of yours. If none of these times work for you, please let us know.\n\n"
            "Looking forward to hearing from you soon!\n\n\n\n"
            "Best regards,\nGNX Solutions HR Team"
        )
        return self._send_whatsapp(to_number, message)


    def send_candidate_slot_acknowledged(self, to_number: str, candidate_name: str):
        message = (
            f"Great, thank you {candidate_name}!\n\n"
            "We've received your selection and are now confirming this time with the interviewer.\n\n"
            "You will receive a final confirmation with the meeting link as soon as they respond. ✨"
        )
        return self._send_whatsapp(to_number, message)

    def send_interviewer_rejection_acknowledged(self, to_number: str, interviewer_name: str, candidate_name: str):
        message = (
            f"Hi {interviewer_name},\n\n"
            f"Thank you for letting us know about the interview with {candidate_name}.\n\n"
            "We will now proceed with rescheduling and will notify you if a new confirmation is needed. No further action is required from your end at this moment. 🙏"
        )
        return self._send_whatsapp(to_number, message)

    def send_confirmation_request_to_interviewer(self, to_number: str, interviewer_name: str, candidate_name: str, slot_time: datetime):
        slot_text = format_datetime_for_display(slot_time)
        message = (
            f"Hi {interviewer_name},\n\n"
            f"An interview with candidate *{candidate_name}* has been proposed for:\n\n"
            f"📅 *{slot_text}*\n\n"
            "Please reply with \"Confirm\" to accept or \"Reject\" to reschedule.\n\n"
            "Thank you! 🙏\nGNX Solutions HR Team"
        )
        return self._send_whatsapp(to_number, message)

    def send_clarification_request_to_interviewer(self, to_number: str, interviewer_name: str, candidate_name: str):
        message = (
            f"Hi {interviewer_name},\n\n"
            f"Regarding the interview with {candidate_name}, we couldn't quite understand your last reply. "
            f"Could you please confirm by simply replying \"Confirm\" if the proposed time works, or \"Reject\" if it doesn't? 🙏"
        )
        return self._send_whatsapp(to_number, message)

    def send_final_confirmation_to_both(self, recipient_number: str, recipient_name: str, interview_details: Dict):
        slot_text = format_datetime_for_display(interview_details['scheduled_time'])
        message = (
            f"✅ *Confirmed!* Your interview is scheduled.\n\n"
            f"Hello {recipient_name},\n\n"
            "Here are the final details:\n\n"
            f"**Candidate:** {interview_details['candidate_name']}\n"
            f"**Interviewer:** {interview_details['interviewer_name']}\n"
            f"**Time:** {slot_text}\n\n"
            f"🔗 *Google Meet Link:*\n{interview_details['meet_link']}\n\n"
            "A calendar invitation has also been sent to your email. Please accept it to add the event to your calendar."
        )
        return self._send_whatsapp(recipient_number, message)

    def send_reschedule_to_candidate(self, to_number: str, candidate_name: str, new_slots: List[Dict]):
        slot_texts = [format_datetime_for_display(slot['slot_time']) for slot in new_slots]
        slot_list_str = "\n".join([f"*{i+1}.* {text}" for i, text in enumerate(slot_texts)])
        message = (
            f"Hi {candidate_name},\n\n"
            "Unfortunately, the interviewer is not available at the time you selected. We apologize for the inconvenience.\n\n"
            "No worries! 😊 Let's find a new time. Here are some new available slots:\n\n"
            f"{slot_list_str}\n\n"
            "Please let us know which one works for you."
        )
        return self._send_whatsapp(to_number, message)

    def send_new_slots_after_candidate_rejection(self, to_number: str, candidate_name: str, new_slots: List[Dict]):
        slot_texts = [format_datetime_for_display(slot['slot_time']) for slot in new_slots]
        slot_list_str = "\n".join([f"*{i+1}.* {text}" for i, text in enumerate(slot_texts)])
        message = (
            f"Hi {candidate_name},\n\n"
            "No problem at all! We understand that schedules can be tight.\n\n"
            "Here is a new set of available time slots for your interview:\n\n"
            f"{slot_list_str}\n\n"
            "Please let us know if any of these work for you. 😊"
        )
        return self._send_whatsapp(to_number, message)

    def send_no_slots_left_to_candidate(self, to_number: str, candidate_name: str):
        message = (
            f"Hi {candidate_name},\n\n"
            f"It seems we couldn't find a suitable time for your interview after a few attempts. To ensure we can connect, please contact our HR team directly at *{HR_EMAIL}* to coordinate a time that works for you.\n\n"
            "We appreciate your patience and look forward to speaking with you."
        )
        return self._send_whatsapp(to_number, message)

    def send_clarification_request_to_candidate(self, to_number: str, candidate_name: str, slots: List[Dict]):
        slot_texts = [format_datetime_for_display(slot['slot_time']) for slot in slots]
        slot_list_str = "\n".join([f"*{i+1}.* {text}" for i, text in enumerate(slot_texts)])
        message = (
            f"Hi {candidate_name},\n\n"
            "Thanks for your reply. To make sure we schedule this correctly, could you please reply with just the number (e.g., \"1\", \"2\") corresponding to your choice from the list below?\n\n"
            f"{slot_list_str}\n\n"
            "Thank you!"
        )
        return self._send_whatsapp(to_number, message)


    def send_feedback_reminder_to_interviewer_whatsapp(self, to_number: str, interviewer_name: str, candidate_name: str):

        message = (
            f"Hi {interviewer_name},\n\n"
            f"This is a friendly reminder regarding the interview with *{candidate_name}* that recently concluded.\n\n"
            f"Could you please provide your feedback and recommendation (Selected/Rejected/Hold) by replying to the email we sent, or by directly emailing our HR team at *{HR_EMAIL}*?\n\n"
            "Your timely feedback is greatly appreciated! 👍"
        )
        return self._send_whatsapp(to_number, message)

    def send_feedback_request_email_to_interviewer(self, to_email: str, interviewer_name: str, candidate_name: str, scheduled_time: datetime, interview_id: int):

        subject = f"ACTION REQUIRED: Feedback for interview with {candidate_name} [Interview ID: {interview_id}]"
        body = (
            f"Dear {interviewer_name},\n\n"
            f"Hope the interview with {candidate_name} (scheduled for {format_datetime_for_display(scheduled_time)}) went well!\n\n"
            f"Please reply to this email directly with your feedback and recommendation (Selected/Rejected/Hold) for the candidate. "
            f"Your timely feedback is crucial for our hiring process.\n\n"
            "Alternatively, you can email your feedback to our HR team at "
            f"{HR_EMAIL}.\n\n"
            "Thank you for your valuable time and contribution.\n\n"
            "Best regards,\nHR Interview Scheduler"
        )
        return self._send_email(to_email, subject, body, interview_id=interview_id)

    def send_final_status_to_candidate(self, to_number: str, candidate_name: str, status: str):
        if status == 'selected':
            message = (
                f"Dear {candidate_name},\n\n"
                "We have an exciting update! Following your interview, we are thrilled to inform you that you have been selected for the role. 🎉\n\n"
                "Our HR team will be in touch with you shortly via email with the official offer letter and next steps. Congratulations!"
            )
        else:
            message = (
                f"Dear {candidate_name},\n\n"
                "Thank you for taking the time to interview with us. We sincerely appreciate your interest in our company.\n\n"
                "After careful consideration, we have decided to move forward with other candidates at this time. We wish you the very best in your job search and encourage you to apply for future openings."
            )
        return self._send_whatsapp(to_number, message)

    def send_interviewer_reassigned_notification(self, to_number: str, interviewer_name: str, candidate_name: str):
        message = (
            f"Hi {interviewer_name},\n\n"
            f"Thank you for your response regarding the interview with {candidate_name}. Due to repeated scheduling conflicts, we have reassigned this interview to another team member to ensure a timely process for the candidate.\n\n"
            "No action is needed from your end. We appreciate your understanding."
        )
        return self._send_whatsapp(to_number, message)

communication_manager = CommunicationManager()
