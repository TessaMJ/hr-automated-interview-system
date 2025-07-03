# interview_management_system/ai_service.py


import logging
import requests
import json
import re 
import os 
from typing import List, Dict, Any, Optional


from interview_management_system.config import GROQ_API_KEY, HR_EMAIL
from interview_management_system.utils import format_datetime_for_display, normalize_phone_number #

logger = logging.getLogger(__name__)

class AIBrain: 
    def __init__(self, api_key: str, knowledge_base_path: str = os.path.join(os.path.dirname(__file__), 'knowledge_base.txt')):
     
        if not api_key:
            logger.critical("GROQ_API_KEY is not configured. AI functions will be limited.")
        self.api_key = api_key
        self.api_url = "https://api.groq.com/openai/v1/chat/completions"
        self.model = "llama3-8b-8192" 
        self.knowledge_base = self._load_knowledge_base(knowledge_base_path)
        logger.info("AIBrain initialized.")

    def _load_knowledge_base(self, path: str) -> str:
        if not os.path.exists(path):
            logger.warning(f"Knowledge base file not found at {path}. AI will not be able to answer KB questions.")
            return ""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.error(f"Error loading knowledge base from {path}: {e}", exc_info=True)
            return ""

    def _get_kb_answer(self, question: str) -> Optional[str]:
        question_lower = question.lower().strip()
        kb_sections = {
            "interview process": r"# Interview Process\n([\s\S]*?)(?=\n#|\Z)",
            "dress code": r"# Dress Code\n([\s\S]*?)(?=\n#|\Z)",
            "interview location": r"# Interview Location\n([\s\S]*?)(?=\n#|\Z)",
            "post-interview steps": r"# Post-Interview Steps\n([\s\S]*?)(?=\n#|\Z)",
            "rescheduling": r"# Rescheduling\n([\s\S]*?)(?=\n#|\Z)",
            "company culture": r"# Company Culture\n([\s\S]*?)(?=\n#|\Z)",
            "job role": r"# Job Role\n([\s\S]*?)(?=\n#|\Z)"
        }

        target_section_key = None
        if "dress code" in question_lower:
            target_section_key = "dress code"
        elif "interview process" in question_lower or "what happens" in question_lower or "how does it work" in question_lower:
            target_section_key = "interview process"
        elif "location" in question_lower or "where is" in question_lower or "remote" in question_lower:
            target_section_key = "interview location"
        elif "after interview" in question_lower or "post-interview" in question_lower or "next steps" in question_lower:
            target_section_key = "post-interview steps"
        elif "reschedule" in question_lower or "change time" in question_lower or "move" in question_lower:
            target_section_key = "rescheduling"
        elif "company culture" in question_lower or "culture" in question_lower:
            target_section_key = "company culture"
        elif "job role" in question_lower or "role details" in question_lower:
            target_section_key = "job role"

        if target_section_key and target_section_key in kb_sections:
            pattern = re.compile(kb_sections[target_section_key], re.IGNORECASE)
            match = pattern.search(self.knowledge_base)
            if match:
                content = match.group(1).strip()
                first_sentence_match = re.match(r'^(.*?)\? (.*)', content, re.DOTALL)
                if first_sentence_match:
                    return first_sentence_match.group(2).strip()
                return content
        return None 

    def _call_groq_api(self, system_prompt: str, user_prompt: str, temperature: float = 0.1) -> Optional[Dict[str, Any]]:
        if not self.api_key:
            logger.error("Groq API key is not set. Cannot make API call.")
            return None

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "model": self.model,
            "temperature": temperature,
            "response_format": {"type": "json_object"}
        }
        try:
            response = requests.post(self.api_url, headers=headers, json=payload, timeout=20) 
            response.raise_for_status()
            content = response.json()['choices'][0]['message']['content']
            parsed_content = json.loads(content)
            logger.debug(f"Groq API raw response: {content}")
            logger.debug(f"Groq API parsed response: {parsed_content}")
            return parsed_content
        except (requests.exceptions.RequestException, json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Error calling Groq API or parsing its response: {e}", exc_info=True)
            return None

    def analyze_conversational_message(self, user_type: str, message_text: str, interview_status: Optional[str], candidate_name: str, interviewer_name: str, offered_slots: List[Dict]) -> Dict[str, Any]:
        message_lower = message_text.lower().strip()

        is_candidate_awaiting_selection = (user_type == 'candidate' and interview_status == 'awaiting_candidate_selection')
        is_interviewer_awaiting_confirmation = (user_type == 'interviewer' and interview_status == 'awaiting_interviewer_confirmation')
        is_interview_confirmed_or_completed = (interview_status in ['scheduled', 'completed_selected', 'completed_rejected', 'feedback_pending', 'feedback_overdue', 'stalled'])

        context_data_for_llm = {
            "user_type": user_type,
            "interview_status": interview_status,
            "candidate_name": candidate_name,
            "interviewer_name": interviewer_name,
            "offered_slots_details": [
                {"index": i + 1, "slot_id": slot['id'], "datetime_iso": slot['slot_time'].isoformat(), "display_time": slot['slot_time'].strftime("%A, %B %d at %I:%M %p %Z")}
                for i, slot in enumerate(offered_slots)
            ]
        }

        system_prompt_action_extraction = f"""
        You are a highly intelligent and precise interview scheduling bot. Your task is to interpret user messages (from candidates or interviewers) in the context of their current interview status and extract their exact intent and any necessary data. You MUST be able to understand various forms of speech, including idioms, direct, and indirect phrasing.

        Return a JSON object with two keys: "intent" and "parsed_data".

        Contextual Information Provided:
        {{
            "user_type": "candidate" or "interviewer",
            "interview_status": "current status (e.g., awaiting_candidate_selection, awaiting_interviewer_confirmation, scheduled)",
            "candidate_name": "Name of candidate",
            "interviewer_name": "Name of interviewer",
            "offered_slots_details": [ {{ "index": N, "slot_id": "UNIQUE_ID", "datetime_iso": "ISO_DATE_TIME", "display_time": "Formatted time for user" }} ]
        }}
        (Note: "offered_slots_details" is only present if the user is a candidate awaiting selection.)

        Possible 'intent' values and their required 'parsed_data':

        1.  'select_slot': User (candidate) is choosing one of the *offered slots*.
            'parsed_data' MUST contain:
            -   "slot_id": The *exact unique ID* of the chosen slot from 'offered_slots_details'.
            -   Example user messages: "I'll take option 3.", "The one on Tuesday at 10 AM works best.", "I want the last option.", "Can I confirm the second slot?", "Yes, the one for July 3rd at 11:00 AM.", "My choice is number 1.", "I'll go with the slot that starts at 12 PM."
            -   If multiple slots are mentioned, infer the most likely. If no clear, available slot is identified, use 'unclear'.

        2.  'request_reschedule': User (candidate) cannot make any of the proposed times or asks for new options.
            'parsed_data' is null.
            -   Example user messages: "None of these times work for me.", "Can I get new slots?", "I need to reschedule this.", "I'm not available then.", "These dates are packed for me.", "I am busy at this date.", "I can't make it.", "I have a conflict."

        3.  'confirm_interviewer': User (interviewer) agrees to the proposed interview time.
            'parsed_data' is null.
            -   Example user messages: "Confirm.", "Yes, that works.", "Looks good.", "I can make that.", "Perfect, I'm available.", "Alright."

        4.  'reject_interviewer': User (interviewer) cannot make the proposed interview time.
            'parsed_data' is null.
            -   Example user messages: "Reject.", "I'm unavailable.", "Cannot make it.", "I'm packed on that date.", "No, I can't do that time.", "Need to reschedule this.", "I am busy at this date.", "I have a conflict at that time."

        5.  'ask_kb_question': User asks a question that can be answered from a general knowledge base (e.g., about the interview process, dress code, company culture, post-interview steps, location, general job role info).
            'parsed_data' MUST contain:
            -   "question": "The full, clear question asked by the user, rephrased if necessary for clarity."

        6.  'defer_until_scheduled': If the user asks a question that is relevant but best answered *after* the interview is confirmed/scheduled (e.g., very specific technical details of the job, in-depth interview format beyond general info, detailed team structure). This applies *only* if the interview status is currently in a scheduling phase ('awaiting_candidate_selection' or 'awaiting_interviewer_confirmation').
            'parsed_data' is null.
            -   Example user messages: "What specific coding languages will I be tested on?", "Can you tell me about the day-to-day tasks?", "Who will be in the interview?"

        7.  'out_of_scope': The message clearly falls outside the bot's capabilities and requires direct human (HR) intervention (e.g., questions about salary, benefits, personal leave requests, extremely complex specific role questions, unrelated personal queries).
            'parsed_data' is null.
            -   Example user messages: "What is the salary for this position?", "Can I take leave next month?", "My dog is sick."

        8.  'ok_or_thanks': Simple acknowledgments like "ok", "thanks", "got it", "alright", "no problem", "understood", "cool", "got it".
            'parsed_data' is null.

        9.  'greeting': The message is purely a greeting and nothing more.
            'parsed_data' is null.
            -   Example user messages: "Hi", "Hello", "Good morning", "Hey there."

        Analyze the user's message *comprehensively* considering all contextual information provided, and select the MOST appropriate intent.
        Prioritize specific scheduling actions if the status aligns. Only classify as 'greeting' if it's purely a greeting.
        """

        user_prompt_action_extraction = f"Context: {json.dumps(context_data_for_llm, indent=2)}\n\nUser's Message: \"{message_text}\"\n\nDetermine the intent and extract any necessary data as JSON."

        llm_analysis = self._call_groq_api(system_prompt_action_extraction, user_prompt_action_extraction, temperature=0.1)

        if not llm_analysis or 'intent' not in llm_analysis:
            logger.error(f"LLM analysis failed to return expected format. Message: '{message_text}'. Raw AI: {llm_analysis}")
            return {"intent": "unclear", "reply_message": "I'm sorry, I'm having trouble processing your request. Could you please try rephrasing it?"}

        intent = llm_analysis.get('intent')
        parsed_data = llm_analysis.get('parsed_data')

        if user_type == 'candidate' and is_candidate_awaiting_selection:
            if intent == 'select_slot':
                selected_slot_id = parsed_data.get('slot_id') if parsed_data else None
                valid_slot_ids = {s['id'] for s in offered_slots}

                if selected_slot_id and selected_slot_id in valid_slot_ids:
                    return {
                        "intent": "select_slot",
                        "reply_message": "Got it! Processing your slot selection...",
                        "parsed_data": {"slot_id": selected_slot_id}
                    }
                else:
                    logger.warning(f"LLM identified slot_id '{selected_slot_id}' but it's not valid/offered. Message: '{message_text}'")
                    return {
                        "intent": "unclear",
                        "reply_message": "I'm sorry, I couldn't find that specific slot among the options provided. Could you please try again by clearly stating the number, or the date and time of your preferred slot?"
                    }

            elif intent == 'request_reschedule':
                return {
                    "intent": "request_reschedule",
                    "reply_message": "Understood. Let me check for new slots for you.",
                    "parsed_data": None
                }

        if user_type == 'interviewer' and is_interviewer_awaiting_confirmation:
            if intent == 'confirm_interviewer':
                return {
                    "intent": "confirm_interviewer",
                    "reply_message": "Thank you for confirming!",
                    "parsed_data": None
                }
            elif intent == 'reject_interviewer':
                return {
                    "intent": "reject_interviewer",
                    "reply_message": "Understood. We will proceed with rescheduling.",
                    "parsed_data": None
                }

        if intent == 'ask_kb_question':
            question_from_llm = parsed_data.get('question', message_text)
            system_prompt_kb_answer = f"""
            You are an AI assistant for an HR interview scheduling system. Your task is to answer a user's question ONLY using the provided knowledge base.
            If the answer is not found in the knowledge base, state that you are limited to the provided information and cannot answer and suggest contacting HR.
            Knowledge Base:
            ---
            {self.knowledge_base}
            ---
            """
            user_prompt_kb_answer = f"User's Question: \"{question_from_llm}\"\n\nBased on the Knowledge Base, answer the question clearly and concisely. If the information is not present, state that you cannot answer from the provided knowledge and recommend contacting HR at {HR_EMAIL}."

            try:
                kb_response_raw = self._call_groq_api(system_prompt_kb_answer, user_prompt_kb_answer, temperature=0.2)
                kb_answer_text = kb_response_raw['choices'][0]['message']['content'] if kb_response_raw and 'choices' in kb_response_raw and kb_response_raw['choices'][0]['message'].get('content') else None
            except Exception as e:
                logger.error(f"Error getting KB answer from Groq: {e}", exc_info=True)
                kb_answer_text = None

            if not kb_answer_text or "cannot answer from the provided knowledge" in kb_answer_text.lower() or "not present" in kb_answer_text.lower() or "contact hr" in kb_answer_text.lower():
                return {
                    "intent": "out_of_scope",
                    "reply_message": f"I am limited to assisting with interview scheduling and common questions. For specific inquiries beyond this, please contact HR at {HR_EMAIL}."
                }
            return {
                "intent": "kb_question",
                "reply_message": kb_answer_text
            }

        elif intent == 'defer_until_scheduled':
            if is_candidate_awaiting_selection or is_interviewer_awaiting_confirmation:
                return {
                    "intent": "scheduling_deflection",
                    "reply_message": "That's a good question! We can provide more details after your interview slot is confirmed. For now, please focus on selecting your preferred time/confirming your availability."
                }
            else:
                logger.warning(f"AI incorrectly suggested 'defer_until_scheduled' when status is {interview_status}. Re-routing.")
                return {
                    "intent": "out_of_scope",
                    "reply_message": f"I am limited to assisting with interview scheduling and common questions. For specific inquiries beyond this, please contact HR at {HR_EMAIL}."
                }

        elif intent == 'out_of_scope':
            return {
                "intent": "out_of_scope",
                "reply_message": f"I am limited to assisting with interview scheduling and common questions. For specific inquiries beyond this, please contact HR at {HR_EMAIL}."
            }
        elif intent == 'ok_or_thanks':
            return {"intent": "ok_or_thanks", "reply_message": "You're welcome! Let me know if you need anything else regarding your interview."}
        elif intent == 'greeting':
            greeting_keywords = ["hi", "hello", "hey", "good morning", "good afternoon", "good evening", "greetings"]
            if any(greet in message_lower for greet in greeting_keywords) and \
               len(message_lower.split()) <= 3 and \
               not any(word in message_lower for word in ["busy", "packed", "slot", "reschedule", "confirm", "reject", "question", "what", "where", "how", "when"]):
                if is_candidate_awaiting_selection:
                    return {
                        "intent": "greeting",
                        "reply_message": f"Hello {candidate_name}! I'm here to help you schedule your interview. Please select a slot from the options I previously sent, or ask a question about the process."
                    }
                elif is_interviewer_awaiting_confirmation:
                    return {
                        "intent": "greeting",
                        "reply_message": f"Hi {interviewer_name}! You have a pending interview confirmation for {candidate_name}. Please reply 'Confirm' or 'Reject'."
                    }
                elif user_type == "interviewer" and interview_status == "feedback_pending":
                    return {
                        "intent": "greeting",
                        "reply_message": f"Hello {interviewer_name}! Please remember to submit feedback for the recent interview with {candidate_name}. Is there anything I can help you with regarding that?"
                    }
                elif is_interview_confirmed_or_completed:
                    return {
                        "intent": "greeting",
                        "reply_message": f"Hello {candidate_name if user_type == 'candidate' else interviewer_name}! How can I help you today?"
                    }
                else:
                    return {
                        "intent": "greeting",
                        "reply_message": "Hello! How can I help you today?"
                    }
            else:
                 return {"intent": "unclear", "reply_message": "I'm not sure how to respond to that. Could you please clarify or ask a question related to your interview?"}

        else: 
            return {"intent": "unclear", "reply_message": "I'm sorry, I didn't quite understand your message. Could you please rephrase it clearly?"}


    def parse_feedback_email(self, email_body: str) -> Dict[str, Any]:
        system_prompt = """
            You are an expert HR data extraction system. Your task is to analyze an interviewer's feedback email and extract a structured summary.
            Your response MUST be a JSON object with two keys: "recommendation" and "summary" or any other synonyms or phrases or related to these.
            The 'recommendation' must be one of three values: 'selected', 'rejected', or 'hold'.
            The 'summary' should be a brief, neutral summary of the key feedback points from the email.
            If the recommendation is not explicitly clear or implied, set 'recommendation' to 'unclear'.
            """
        user_prompt = f"Interviewer's Feedback Email Body:\n\n---\n{email_body}\n---\n\nExtract the recommendation and summary into a JSON object."

        result = self._call_groq_api(system_prompt, user_prompt, temperature=0.0) # Use low temp for extraction consistency

        if result and 'recommendation' in result:
            return result

        logger.warning("AI feedback parsing failed or returned invalid format. Defaulting to 'unclear'.")
        return {"recommendation": "unclear", "summary": "Could not automatically parse feedback."}

ai_brain = AIBrain(api_key=GROQ_API_KEY)