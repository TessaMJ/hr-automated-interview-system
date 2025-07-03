# interview_management_system/services.py

import logging
import re
from typing import Dict, Any, List, Optional 
import datetime
import pytz
from interview_management_system import database, utils
from interview_management_system.ai_service import ai_brain
from interview_management_system.communication import communication_manager
from interview_management_system.config import (
    SLOTS_PER_PROPOSAL,
    MAX_CANDIDATE_RESCHEDULE_ATTEMPTS,
    MAX_INTERVIEWER_REJECTIONS,
    FEEDBACK_REMINDER_INITIAL_DELAY_MINUTES,
    FEEDBACK_REMINDER_FOLLOW_UP_DELAY_MINUTES,
    MAX_FEEDBACK_REMINDERS,
    GMAIL_FEEDBACK_SUBJECT_KEYWORD,
    MAX_FEEDBACK_EMAIL_POLLS,
    HR_EMAIL 
)

logger = logging.getLogger(__name__)

class InterviewService:
    def start_shortlisting_and_interview_process(self):
        logger.info("Starting shortlisting and interview process...")
        top_candidates = database.get_top_candidates_for_shortlisting()

        if not top_candidates:
            logger.info("No new candidates met the shortlisting criteria.")
            return {"success": True, "count": 0, "message": "No new candidates to process."}

        initiated_count = 0
        for candidate in top_candidates:
            logger.info(f"Processing shortlisted candidate: {candidate['name']} (ID: {candidate['id']})")
            interviewer = database.get_available_interviewer()
            if not interviewer:
                logger.error(f"No available interviewers for candidate {candidate['id']}. Skipping.")
                continue

            interview_id = database.create_interview(
                candidate_id=candidate['id'],
                interviewer_id=interviewer['id'],
                status='awaiting_candidate_selection'
            )

            database.update_candidate_status(candidate['id'], 'interview_initiated')

            new_slots_dt = utils.generate_future_slots(num_slots=SLOTS_PER_PROPOSAL)
            database.add_interview_slots(interview_id, [dt.isoformat() for dt in new_slots_dt])

            offered_slots = database.get_offered_slots_for_interview(interview_id)

            communication_manager.send_slot_proposal_to_candidate(
                to_number=candidate['whatsapp_number'],
                candidate_name=candidate['name'],
                slots=offered_slots
            )
            initiated_count += 1

        logger.info(f"Successfully initiated interviews for {initiated_count} candidates.")
        return {"success": True, "count": initiated_count, "message": f"Initiated interviews for {initiated_count} candidates."}

    def handle_incoming_whatsapp(self, sender_number: str, message_body: str):
        normalized_number = utils.normalize_phone_number(sender_number)
        user = database.get_user_by_whatsapp(normalized_number)

        if not user:
            logger.warning(f"Received message from unrecognized number: {normalized_number}")
            communication_manager.send_ai_generated_message(normalized_number, f"Hello! It seems your number is not registered in our system. Please contact HR at {HR_EMAIL}.")
            return
        interview: Optional[Dict[str, Any]] = None
        if user['user_type'] == 'candidate':
            interview = database.get_interview_by_user_id(user['id'], 'candidate')
            if not interview:
                interview = database.get_latest_interview_for_candidate(user['id'])
        elif user['user_type'] == 'interviewer':
            interview = database.get_interview_awaiting_interviewer_confirmation(user['id'])
            if not interview:
                interview = database.get_latest_interview_for_interviewer(user['id'])

        current_interview_status = interview['status'] if interview else None
        candidate_name = interview['candidate_name'] if interview and 'candidate_name' in interview else user.get('name', "there")
        interviewer_name = interview['interviewer_name'] if interview and 'interviewer_name' in interview else user.get('name', "there")
        offered_slots = []
        if interview and interview['status'] == 'awaiting_candidate_selection':
            offered_slots = database.get_offered_slots_for_interview(interview['id'])

        ai_response = ai_brain.analyze_conversational_message(
            user_type=user['user_type'],
            message_text=message_body,
            interview_status=current_interview_status,
            candidate_name=candidate_name,
            interviewer_name=interviewer_name,
            offered_slots=offered_slots 
        )

        intent = ai_response.get('intent')
        reply_message = ai_response.get('reply_message')
        parsed_data = ai_response.get('parsed_data')

        logger.info(f"AI determined intent: '{intent}' for user {user['id']} (Type: {user['user_type']}, Status: {current_interview_status}).")

        if user['user_type'] == 'candidate' and interview and interview['id'] and interview['status'] == 'awaiting_candidate_selection':
            if intent == 'select_slot':
                logger.info(f"Dispatching candidate slot selection for interview {interview['id']}.")
                self._process_candidate_slot_confirmation(interview, ai_response)
                return

            elif intent == 'request_reschedule':
                logger.info(f"Dispatching candidate reschedule request for interview {interview['id']}.")
                self._process_candidate_reschedule_request(interview)
                return

        elif user['user_type'] == 'interviewer' and interview and interview['id'] and interview['status'] == 'awaiting_interviewer_confirmation':
            if intent == 'confirm_interviewer':
                logger.info(f"Dispatching interviewer confirmation for interview {interview['id']}.")
                communication_manager.send_interviewer_confirmation_acknowledged( 
                    to_number=interview['interviewer_whatsapp_number'],
                    interviewer_name=interviewer_name
                )
                self._finalize_interview_schedule(interview)
                return 

            elif intent == 'reject_interviewer':
                logger.info(f"Dispatching interviewer rejection for interview {interview['id']}.")
                communication_manager.send_interviewer_rejection_acknowledged(
                    to_number=interview['interviewer_whatsapp_number'],
                    interviewer_name=interviewer_name,
                    candidate_name=candidate_name
                )
                self._process_interviewer_rejection(interview)
                return 
        if reply_message:
            communication_manager.send_ai_generated_message(normalized_number, reply_message)
        else:
            logger.error(f"AI response for intent '{intent}' did not contain a reply_message. Sending generic fallback.")
            communication_manager.send_ai_generated_message(normalized_number, "I'm sorry, I encountered an internal issue. Please try again or contact HR.")
    def _handle_candidate_reply(self, interview: Dict[str, Any], ai_response: Dict):
        if interview['status'] != 'awaiting_candidate_selection':
            logger.info(f"Ignoring candidate action for interview {interview['id']} in status '{interview['status']}'.")
            return 

        intent = ai_response.get('intent')

        if intent == 'select_slot':
            self._process_candidate_slot_confirmation(interview, ai_response)
        elif intent == 'request_reschedule':
            self._process_candidate_reschedule_request(interview)
        else:
            logger.warning(f"Unexpected AI intent '{intent}' received for _handle_candidate_reply for interview {interview['id']}. Sending clarification.")
            offered_slots = database.get_offered_slots_for_interview(interview['id'])
            communication_manager.send_clarification_request_to_candidate(
                to_number=interview['candidate_whatsapp_number'],
                candidate_name=interview['candidate_name'],
                slots=offered_slots
            )

    def _process_candidate_slot_confirmation(self, interview: Dict, ai_response: Dict):
        offered_slots = database.get_offered_slots_for_interview(interview['id'])
        valid_slot_ids = {s['id'] for s in offered_slots}

        selection_details = ai_response.get('parsed_data', {})
        selected_slot_id = selection_details.get('slot_id')

        logger.debug(f"Candidate slot selection: AI parsed slot_id='{selected_slot_id}'")
        try:
            if not selected_slot_id or selected_slot_id not in valid_slot_ids:
                raise ValueError(f"AI provided invalid or un-offered slot_id: {selected_slot_id}")
            chosen_slot = next((s for s in offered_slots if s['id'] == selected_slot_id), None)
            if not chosen_slot: 
                raise ValueError(f"Could not find chosen_slot object for ID: {selected_slot_id}")


            database.deactivate_offered_slots(interview['id']) 
            database.update_slot_status(chosen_slot['id'], 'selected') 
            database.update_interview_details(interview['id'], {
                'scheduled_time': chosen_slot['slot_time'].isoformat(),
                'status': 'awaiting_interviewer_confirmation'
            })

            communication_manager.send_candidate_slot_acknowledged(
                to_number=interview['candidate_whatsapp_number'],
                candidate_name=interview['candidate_name']
            )
            communication_manager.send_confirmation_request_to_interviewer(
                to_number=interview['interviewer_whatsapp_number'],
                interviewer_name=interview['interviewer_name'],
                candidate_name=interview['candidate_name'],
                slot_time=chosen_slot['slot_time']
            )
        except (ValueError, TypeError) as e:
            logger.warning(f"Error processing AI-selected slot ID '{selected_slot_id}' for interview {interview['id']}. Error: {e}")
            communication_manager.send_clarification_request_to_candidate(
                to_number=interview['candidate_whatsapp_number'],
                candidate_name=interview['candidate_name'],
                slots=offered_slots
            )

    def _process_candidate_reschedule_request(self, interview: Dict):
        new_attempts = interview['reschedule_attempts'] + 1
        if new_attempts >= MAX_CANDIDATE_RESCHEDULE_ATTEMPTS:
            database.update_interview_details(interview['id'], {'status': 'cancelled_no_slots'})
            communication_manager.send_no_slots_left_to_candidate(
                to_number=interview['candidate_whatsapp_number'],
                candidate_name=interview['candidate_name']
            )
        else:
            database.update_interview_details(interview['id'], {'reschedule_attempts': new_attempts})

            database.deactivate_offered_slots(interview['id'])
            all_previously_offered_slots = database.get_all_slots_for_interview(interview['id'])
            latest_prev_slot_time = None
            if all_previously_offered_slots:
                latest_prev_slot_time = max(s['slot_time'] for s in all_previously_offered_slots)

            last_offered_slots = database.get_offered_slots_for_interview(interview['id']) 
            exclude_dates_list = list(set(s['slot_time'].date() for s in last_offered_slots))
            
            new_slots_dt = utils.generate_future_slots(
                num_slots=SLOTS_PER_PROPOSAL,
                start_from_datetime=latest_prev_slot_time,
                exclude_dates=exclude_dates_list
            )

            if not new_slots_dt:
                logger.warning(f"Failed to generate new slots for candidate {interview['candidate_name']} (ID: {interview['candidate_id']}) after reschedule request. Max attempts: {new_attempts}. Moving to 'cancelled_no_slots'.")
                database.update_interview_details(interview['id'], {'status': 'cancelled_no_slots'})
                communication_manager.send_no_slots_left_to_candidate(
                    to_number=interview['candidate_whatsapp_number'],
                    candidate_name=interview['candidate_name']
                )
                return


            database.add_interview_slots(interview['id'], [dt.isoformat() for dt in new_slots_dt])

            updated_slots = database.get_offered_slots_for_interview(interview['id'])

            communication_manager.send_new_slots_after_candidate_rejection(
                to_number=interview['candidate_whatsapp_number'],
                candidate_name=interview['candidate_name'],
                new_slots=updated_slots
            )
    def _handle_interviewer_reply(self, interview: Dict[str, Any], ai_response: Dict):
        if interview['status'] != 'awaiting_interviewer_confirmation':
            logger.info(f"Ignoring interviewer action for interview {interview['id']} in status '{interview['status']}'.")
            return

        intent = ai_response.get('intent')

        if intent == 'confirm_interviewer':
            self._finalize_interview_schedule(interview)
        elif intent == 'reject_interviewer':
            communication_manager.send_interviewer_rejection_acknowledged(
                to_number=interview['interviewer_whatsapp_number'],
                interviewer_name=interview['interviewer_name'],
                candidate_name=interview['candidate_name']
            )
            self._process_interviewer_rejection(interview)
        else:
            logger.warning(f"Unexpected AI intent '{intent}' received for _handle_interviewer_reply for interview {interview['id']}.")
            communication_manager.send_clarification_request_to_interviewer(
                to_number=interview['interviewer_whatsapp_number'],
                interviewer_name=interview['interviewer_name'],
                candidate_name=interview['candidate_name']
            )

    def _finalize_interview_schedule(self, interview: Dict):
        meet_link = utils.create_google_meet_event(
            summary=f"Interview: {interview['candidate_name']} with {interview['interviewer_name']}",
            start_time=interview['scheduled_time'],
            attendee_emails=[interview['candidate_email'], interview['interviewer_email']]
        )
        if not meet_link:
            logger.error(f"Failed to create Google Meet link for interview {interview['id']}. Manual intervention required.")
            return

        database.update_interview_details(interview['id'], {
            'status': 'scheduled',
            'meet_link': meet_link
        })

        updated_interview = database.get_interview_by_user_id(interview['candidate_id'], 'candidate')

        communication_manager.send_final_confirmation_to_both(
            recipient_number=updated_interview['candidate_whatsapp_number'],
            recipient_name=updated_interview['candidate_name'],
            interview_details=updated_interview
        )
        communication_manager.send_final_confirmation_to_both(
            recipient_number=updated_interview['interviewer_whatsapp_number'],
            recipient_name=updated_interview['interviewer_name'],
            interview_details=updated_interview
        )

    def _process_interviewer_rejection(self, interview: Dict):
        new_rejection_count = interview['rejection_count'] + 1

        communication_manager.send_interviewer_rejection_acknowledged(
            to_number=interview['interviewer_whatsapp_number'],
            interviewer_name=interview['interviewer_name'],
            candidate_name=interview['candidate_name']
        )

        if new_rejection_count >= MAX_INTERVIEWER_REJECTIONS:
            self._reassign_interviewer(interview)
        else:
            database.update_interview_details(interview['id'], {
                'rejection_count': new_rejection_count,
                'status': 'awaiting_candidate_selection'
            })

            database.deactivate_offered_slots(interview['id'])
            all_previously_offered_slots = database.get_all_slots_for_interview(interview['id'])
            latest_prev_slot_time = None
            if all_previously_offered_slots:
                latest_prev_slot_time = max(s['slot_time'] for s in all_previously_offered_slots)
            exclude_dates_list = []
            if interview['scheduled_time']: 
                exclude_dates_list.append(interview['scheduled_time'].date())

            new_slots_dt = utils.generate_future_slots(
                num_slots=SLOTS_PER_PROPOSAL,
                start_from_datetime=latest_prev_slot_time,
                exclude_dates=exclude_dates_list
            )

            if not new_slots_dt:
                logger.warning(f"Failed to generate new slots for candidate {interview['candidate_name']} (ID: {interview['candidate_id']}) after interviewer rejection. Max attempts: {new_rejection_count}. Moving to 'cancelled_no_slots'.")
                database.update_interview_details(interview['id'], {'status': 'cancelled_no_slots'})
                communication_manager.send_no_slots_left_to_candidate(
                    to_number=interview['candidate_whatsapp_number'],
                    candidate_name=interview['candidate_name']
                )
                return


            database.add_interview_slots(interview['id'], [dt.isoformat() for dt in new_slots_dt])
            updated_slots = database.get_offered_slots_for_interview(interview['id'])

            communication_manager.send_reschedule_to_candidate(
                to_number=interview['candidate_whatsapp_number'],
                candidate_name=interview['candidate_name'],
                new_slots=updated_slots
            )


    def _reassign_interviewer(self, interview: Dict):
        logger.warning(f"Interviewer rejection limit reached for interview {interview['id']}. Reassigning.")
        old_interviewer_id = interview['interviewer_id']
        new_interviewer = database.get_available_interviewer(exclude_id=old_interviewer_id)

        if not new_interviewer:
            logger.critical(f"Could not reassign interview {interview['id']}: No other active interviewers found. Moving interview {interview['id']} to 'stalled'.")
            database.update_interview_details(interview['id'], {'status': 'stalled'}) 
            return

        database.update_interview_details(interview['id'], {
            'interviewer_id': new_interviewer['id'],
            'rejection_count': 0,
            'status': 'awaiting_interviewer_confirmation' 
        })

        communication_manager.send_interviewer_reassigned_notification(
            to_number=interview['interviewer_whatsapp_number'], 
            interviewer_name=interview['interviewer_name'],
            candidate_name=interview['candidate_name']
        )
        communication_manager.send_confirmation_request_to_interviewer(
            to_number=new_interviewer['whatsapp_number'], 
            interviewer_name=new_interviewer['name'],
            candidate_name=interview['candidate_name'],
            slot_time=interview['scheduled_time'] 
        )

    def poll_interviewer_emails_for_feedback(self):
        logger.info("Polling interviewer emails for feedback.")
        interviews_to_poll = database.get_interviews_awaiting_feedback_email_poll()

        if not interviews_to_poll:
            logger.info("No interviews found awaiting feedback email polling.")
            return

        for interview in interviews_to_poll:
            logger.info(f"Processing email poll for interview {interview['id']} (Interviewer: {interview['interviewer_email']}).")
            new_poll_attempts = interview['email_poll_attempts'] + 1
            database.update_interview_details(interview['id'], {
                'email_poll_attempts': new_poll_attempts,
                'last_email_polled_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
            })
            try:
                feedback_emails = communication_manager.fetch_feedback_emails(
                    email_address=interview['interviewer_email'],
                    subject_keyword=GMAIL_FEEDBACK_SUBJECT_KEYWORD
                )
            except Exception as e:
                logger.error(f"Error fetching emails for interviewer {interview['interviewer_email']} for interview {interview['id']}: {e}")
                continue

            found_feedback = False
            for email_body in feedback_emails:
                analysis = ai_brain.parse_feedback_email( 
                    email_body=email_body
                )

                feedback_summary = analysis.get('summary')
                recommendation = analysis.get('recommendation')

                if feedback_summary and recommendation and recommendation != 'unclear':
                    logger.info(f"Feedback found for interview {interview['id']}. Summary: {feedback_summary[:100]}..., Recommendation: {recommendation}")
                    database.update_interview_details(interview['id'], {
                        'status': f'completed_{recommendation}',
                        'feedback_summary': feedback_summary,
                        'last_email_polled_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        'email_poll_attempts': new_poll_attempts
                    })
                    found_feedback = True
                    if recommendation in ['selected', 'rejected']:
                        communication_manager.send_final_status_to_candidate(
                            to_number=interview['candidate_whatsapp_number'],
                            candidate_name=interview['candidate_name'],
                            status=recommendation
                        )
                    break
                elif feedback_summary:
                    logger.info(f"Feedback found for interview {interview['id']} but recommendation was unclear. Summary: {feedback_summary[:100]}...")
                    database.update_interview_details(interview['id'], {
                        'feedback_summary': feedback_summary,
                        'last_email_polled_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                        'email_poll_attempts': new_poll_attempts
                    })

            if not found_feedback and new_poll_attempts >= MAX_FEEDBACK_EMAIL_POLLS:
                logger.warning(f"Max email poll attempts reached for interview {interview['id']} without clear feedback. Moving to 'feedback_overdue'.")
                database.update_interview_details(interview['id'], {'status': 'feedback_overdue'})
            elif not found_feedback:
                logger.info(f"No clear feedback found in emails for interview {interview['id']} yet. Attempt {new_poll_attempts}/{MAX_FEEDBACK_EMAIL_POLLS}.")


    def _request_feedback_from_interviewer(self, details: Dict):
        logger.info(f"Requesting feedback from {details['interviewer_name']} for interview {details['id']} (via WhatsApp and Email).")
        current_reminders_sent = details.get('reminders_sent_count', 0)
        new_reminders_sent = current_reminders_sent + 1
        communication_manager.send_feedback_reminder_to_interviewer_whatsapp(
            to_number=details['interviewer_whatsapp_number'],
            interviewer_name=details['interviewer_name'],
            candidate_name=details['candidate_name']
        )

        communication_manager.send_feedback_request_email_to_interviewer(
            to_email=details['interviewer_email'],
            interviewer_name=details['interviewer_name'],
            candidate_name=details['candidate_name'],
            scheduled_time=details['scheduled_time'],
            interview_id=details['id']
        )
        update_data = {
            'status': 'awaiting_feedback',
            'reminders_sent_count': new_reminders_sent,
            'last_reminder_sent_at': datetime.datetime.now(datetime.timezone.utc).isoformat()
        }
        database.update_interview_details(details['id'], update_data)

    def check_for_completed_interviews_and_send_reminders(self):
        logger.info("Checking for completed interviews and pending feedback reminders.")

        interviews_to_process = database.get_interviews_for_feedback_processing()

        for interview in interviews_to_process:
            now_utc = datetime.datetime.now(datetime.timezone.utc)
            if interview['status'] == 'scheduled':
                scheduled_time_utc = interview['scheduled_time']
                if scheduled_time_utc.tzinfo is None:
                    scheduled_time_utc = pytz.utc.localize(scheduled_time_utc)
                else:
                    scheduled_time_utc = scheduled_time_utc.astimezone(datetime.timezone.utc)
                if scheduled_time_utc + datetime.timedelta(minutes=FEEDBACK_REMINDER_INITIAL_DELAY_MINUTES) <= now_utc:
                    logger.info(f"Interview {interview['id']} completed. Requesting initial feedback.")
                    self._request_feedback_from_interviewer(interview)

            elif interview['status'] == 'awaiting_feedback':
                last_reminder_utc = None
                if interview['last_reminder_sent_at'] is None:
                    last_reminder_utc = datetime.datetime.min.replace(tzinfo=datetime.timezone.utc)
                else:
                    last_reminder_utc = interview['last_reminder_sent_at']
                    if last_reminder_utc.tzinfo is None:
                        last_reminder_utc = pytz.utc.localize(last_reminder_utc)
                    else:
                        last_reminder_utc = last_reminder_utc.astimezone(datetime.timezone.utc)
                if (last_reminder_utc + datetime.timedelta(minutes=FEEDBACK_REMINDER_FOLLOW_UP_DELAY_MINUTES) <= now_utc and
                    interview['reminders_sent_count'] < MAX_FEEDBACK_REMINDERS):

                    logger.info(f"Sending follow-up feedback reminder for interview {interview['id']}.")
                    self._request_feedback_from_interviewer(interview)
                elif interview['reminders_sent_count'] >= MAX_FEEDBACK_REMINDERS:
                    logger.warning(f"Max feedback reminders sent for interview {interview['id']}. Moving to 'feedback_overdue' status.")
                    database.update_interview_details(interview['id'], {'status': 'feedback_overdue'})

interview_service = InterviewService()