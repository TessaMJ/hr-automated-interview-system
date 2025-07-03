# HR Interview Management System

## Overview

This project is a comprehensive HR Interview Management System designed to automate and streamline the interview scheduling process. It leverages a combination of technologies, including:

*   **Flask:** A lightweight Python web framework for building the API and handling webhooks.
*   **Twilio:** For sending and receiving WhatsApp messages to candidates and interviewers.
*   **Groq API:**  For AI-powered conversational message analysis and feedback parsing.
*   **Google Calendar API:** For creating and managing Google Meet events and sending calendar invitations.
*   **PostgreSQL:** A robust relational database for storing candidate, interviewer, interview, and slot information.
*   **IMAP:** For polling interviewer email inboxes for feedback.
*   **pytz:** For timezone aware scheduling.

The system automates tasks such as:

*   Candidate shortlisting based on CV scores.
*   Interview scheduling and slot selection.
*   Automated reminders and confirmations.
*   Feedback collection and analysis.
*   AI-powered conversational message analysis for intent recognition.

## Key Features

*   **Automated Interview Scheduling:** System proposes interview slots to candidates and confirms with interviewers.
*   **WhatsApp Integration:** Communication with candidates and interviewers via WhatsApp for scheduling updates and reminders.
*   **AI-Powered Conversation Analysis:** Uses Groq API to understand candidate and interviewer intent from messages.
*   **Google Calendar Integration:** Automatically creates Google Meet events and sends calendar invitations.
*   **Email Feedback Polling:** Automatically retrieves interview feedback from interviewer's email inboxes.
*   **Database Persistence:** Uses PostgreSQL to store all relevant data, ensuring persistence and reliability.
*   **Configurable Settings:**  Many parameters (e.g., scheduling windows, reminder intervals) can be configured via environment variables.

## Architecture

The system is structured as follows:

*   **`ai_service.py`:** Contains the `AIBrain` class, which interfaces with the Groq API for message analysis and feedback parsing.
*   **`app.py`:**  The main Flask application, defining API endpoints and webhook handlers.
*   **`communication.py`:**  Handles communication with candidates and interviewers via WhatsApp (Twilio) and email (SMTP/IMAP).
*   **`config.py`:**  Loads and manages configuration settings from environment variables.
*   **`database.py`:**  Provides functions for interacting with the PostgreSQL database.
*   **`scheduler.py`:**  Runs background tasks, such as checking for completed interviews and sending reminders.
*   **`services.py`:**  Implements the core business logic of the interview scheduling process.
*   **`utils.py`:**  Contains utility functions, such as date/time formatting, phone number normalization, and Google Calendar event creation.

## Setup Instructions

1.  **Clone the Repository:**

    ```bash
    git clone <your_repository_url>
    cd <your_project_directory>
    ```

2.  **Install Dependencies:**

    ```bash
    pip install -r requirements.txt
    ```

    *   This project's dependencies are listed in the `requirements.txt` file.

3.  **Configure Environment Variables:**

    *   Create a `.env` file in the root directory of the project.
    *   Copy the contents of `.env.example` into your new `.env` file.
    *   Edit the `.env` file and replace the placeholder values with your actual credentials.

    *   **Note:**
        *   For email settings, use the "App Password" for increased security, especially with Gmail.
        *   Ensure that you have correctly configured all necessary API keys and credentials.

4.  **Setup Google Cloud Project and Calendar API:**

    This is required for Google Calendar integration and creating Google Meet events.

    *   **Create a Google Cloud Project:**
        1.  Go to the [Google Cloud Console](https://console.cloud.google.com/).
        2.  Create a new project.
    *   **Enable the Google Calendar API:**
        1.  In your project, go to "APIs & Services" -> "Library".
        2.  Search for "Google Calendar API" and enable it.
    *   **Create Credentials:**
        1.  Go to "APIs & Services" -> "Credentials".
        2.  Click "Create credentials" -> "OAuth client ID".
        3.  Configure the OAuth client:
            *   **Application type:** "Desktop app".
            *   Name it something descriptive (e.g., "Interview Scheduler Desktop App").
        4.  Download the Client Secret:
            *   After creating the OAuth client, download the "client_secret\_.json" file.
            *   Rename this file to `client_secret.json` and place it in the root directory of your project (or adjust the `GOOGLE_CLIENT_SECRET_FILE` environment variable in your `.env` file accordingly).

5.  **Generate Google Calendar API Token:**

    *   Run the `generate_google_token.py` script to authenticate with the Google Calendar API and generate the token file:

        ```bash
        python generate_google_token.py
        ```

    *   This will open a browser window and prompt you to log in to your Google account and grant the application access to your calendar.
    *   After authentication, a `token.pickle` file will be created, storing your credentials.


6.  **Optional: Initial Database Setup and Data Modification (using pgAdmin):**

    *   This step is optional but highly recommended for testing and customization.  You can modify the sample database content or manually create the database before the initialization step.
    *   **Install pgAdmin:** If you don't already have it, download and install pgAdmin from [https://www.pgadmin.org/](https://www.pgadmin.org/).
    *   **Connect to the Database:**
        *   Open pgAdmin.
        *   Create a new server connection using the database credentials (DB\_USER, DB\_PASSWORD, DB\_HOST, DB\_PORT, DB\_NAME) from your `.env` file.
        *   If the database doesn't exist, create it first.
    *   **Browse the Schema:**
        *   Expand the server connection, then expand "Databases" -> your database name -> "Schemas" -> "public" -> "Tables".
        *   If the tables doesn't exist then skip this step.
        *   You'll see tables like `candidates`, `interviewers`, `interviews`, and `interview_slots`.
    *   **Edit Data:**
        *   Right-click on a table (e.g., `candidates`) and select "View/Edit Data" -> "All Rows".
        *   You can now directly edit the data in the table.  For example, you might want to update the `whatsapp_number` fields to use your test accounts.

7.  **Initialize the Database:**

    *   Use the provided API endpoint to initialize the database schema and seed with sample data:

        ```bash
        curl -X POST -H "X-API-KEY: your_internal_api_key" http://localhost:5000/api/v1/init-db
        ```
        (Replace `your_internal_api_key` with the actual value from your `.env` file.)

8.  **Setup Twilio and Join Sandbox (If Using a Free Account):**

    If you're using a free Twilio account, you need to set up the Twilio Sandbox for WhatsApp.
    *   **Twilio Account:** If you don't have one, create a free Twilio account at [https://www.twilio.com/try-twilio](https://www.twilio.com/try-twilio).
    *   **WhatsApp Sandbox:**
        *   Go to your Twilio account dashboard.
        *   Navigate to "Messaging" -> "Try WhatsApp" -> "Activate your Sandbox".
        *   Follow the instructions to join the sandbox. You'll need to send a specific WhatsApp message from each of your test accounts to the Twilio number to activate them.
    *   **Update `whatsapp_number` in Database:**
        Update the `whatsapp_number` of the candidates and interviewers to numbers that has successfully subscribed to Twilio Whatsapp sandbox.

9.  **Run the Application:**

    ```bash
    python interview_management_system/app.py
    ```

    The application will start running on the specified port (default: 5001).

10. **Run the Background Scheduler:**

    In another terminal:

    ```bash
    python scheduler.py
    ```

11. **Set up Twilio Webhook:**

    Configure your Twilio WhatsApp Sandbox to send messages to your application's webhook endpoint. The webhook URL should be similar to:

    ```
    <your_app_base_url>/webhook/whatsapp
    ```

    (Replace `<your_app_base_url>` with the actual URL of your deployed application.) Also make sure Twilio properly sends message on the correct url.

12. **Start Shortlisting Process:**

    *   To begin the automated shortlisting and interview scheduling process, use the following API endpoint:

        ```bash
        curl -X POST -H "X-API-KEY: your_internal_api_key" http://localhost:5000/api/v1/start-shortlisting
        ```
        (Replace `your_internal_api_key` with the actual value from your `.env` file.)

## API Endpoints

*   `/webhook/whatsapp` (POST):  Twilio webhook for receiving WhatsApp messages.
*   `/api/v1/start-shortlisting` (POST): Starts the shortlisting and interview process (requires `X-API-KEY` header).
*   `/api/v1/init-db` (POST): Initializes the database schema (requires `X-API-KEY` header).
*   `/api/v1/debug-create-past-interview` (POST): Creates a debug interview in the past (requires `X-API-KEY` header). Useful for testing the scheduler.
*   `/api/v1/debug-get-interview/<interview_id>` (GET): Retrieves details of a specific interview (requires `X-API-KEY` header).


