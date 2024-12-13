from flask import Flask, render_template, request, jsonify, session, redirect, flash, url_for
from taskgenie import TaskGenieApp
from dotenv import load_dotenv
from bson import ObjectId
import asyncio
import re
from datetime import datetime, timedelta
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import pickle
import os
import logging
import json

# Custom JSON encoder to handle ObjectId
class MongoJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, ObjectId):
            return str(obj)
        return super().default(obj)

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Set environment variable for development
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

app = Flask(__name__)

# Configure app to use custom JSON encoder
app.json_encoder = MongoJSONEncoder

# Set a secure secret key
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev_key_123')  # fallback to dev key if env var not set

# Initialize the TaskGenie app
load_dotenv()
task_genie = TaskGenieApp()

# Store user sessions
user_sessions = {}

# Google OAuth2 Configuration
SCOPES = [
    'openid',
    'https://www.googleapis.com/auth/calendar',
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile'
]

flow = Flow.from_client_secrets_file(
    'client_secret.json',
    scopes=SCOPES,
    redirect_uri='http://127.0.0.1:5000/oauth2callback'
)

def run_async(coro):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

@app.route('/')
def home():
    """Home route that handles both authenticated and non-authenticated states"""
    return render_template('index.html', user_name=session.get('user_name'))

@app.route('/continue_as_guest', methods=['POST'])
def continue_as_guest():
    """Handle guest login"""
    try:
        # Clear any existing session
        session.clear()
        
        # Set guest credentials
        session['user_name'] = 'guest'
        session['user_email'] = 'guest@example.com'
        
        return jsonify({'status': 'success'})
    except Exception as e:
        logger.error(f"Error in guest login: {str(e)}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/login')
def login():
    """Initiate Google OAuth login flow"""
    try:
        # Clear any existing session
        session.clear()
        
        # Generate authorization URL
        authorization_url, state = flow.authorization_url()
        session['state'] = state
        
        return redirect(authorization_url)
    except Exception as e:
        logger.error(f"Error initiating login: {str(e)}")
        flash('Failed to initiate login', 'error')
        return redirect('/')

@app.route('/logout')
def logout():
    """Handle user logout by clearing session and redirecting appropriately"""
    try:
        current_user = session.get('user_name', 'Unknown user')
        logger.info(f"Initiating logout for user: {current_user}")
        
        was_google_user = 'credentials' in session
        
        # Clear all session data
        session.clear()
        logger.info(f"Session cleared successfully for {current_user}")
        
        # For Google users, return the Google logout URL to handle in frontend
        if was_google_user:
            google_logout_url = 'https://accounts.google.com/Logout'
            return_url = request.host_url
            logger.info(f"Returning Google logout URL to frontend")
            return jsonify({
                'redirect_url': google_logout_url,
                'return_url': return_url,
                'was_google_user': True
            })
            
        # For guest users or after Google logout
        logger.info("Redirecting to home page")
        return jsonify({
            'redirect_url': '/',
            'was_google_user': False
        })
        
    except Exception as e:
        logger.error(f"Logout failed: {str(e)}")
        # Still try to clear session and redirect home on error
        session.clear()
        return jsonify({
            'redirect_url': '/',
            'was_google_user': False
        })

@app.route('/oauth2callback')
def oauth2callback():
    """Handle Google OAuth callback"""
    try:
        # Get authorization code
        code = request.args.get('code')
        if not code:
            raise ValueError("No authorization code received")
            
        # Exchange code for credentials
        flow.fetch_token(authorization_response=request.url)
        credentials = flow.credentials
        
        # Store credentials in session
        session['credentials'] = {
            'token': credentials.token,
            'refresh_token': credentials.refresh_token,
            'token_uri': credentials.token_uri,
            'client_id': credentials.client_id,
            'client_secret': credentials.client_secret,
            'scopes': credentials.scopes
        }
        
        # Get user info from Google
        try:
            service = build('oauth2', 'v2', credentials=credentials)
            user_info = service.userinfo().get().execute()
            
            # Store user info in session
            session['user_email'] = user_info['email']
            session['user_name'] = user_info['name']
            
            # Initial calendar sync for Google users
            if session['user_name'] != 'guest':
                task_genie.db.connect()
                
                # Remove all existing events and tasks for this user
                task_genie.db.db['events'].delete_many({'User': session['user_name']})
                task_genie.db.db['tasks'].delete_many({'User': session['user_name']})
                
                # Get events from Google Calendar
                calendar_service = build('calendar', 'v3', credentials=credentials)
                now = datetime.utcnow()
                thirty_days_ago = now - timedelta(days=30)
                events_result = calendar_service.events().list(
                    calendarId='primary',
                    timeMin=thirty_days_ago.isoformat() + 'Z',
                    # timeMax=(now + timedelta(days=30)).isoformat() + 'Z',
                    maxResults=999,
                    singleEvents=True,
                    orderBy='startTime'
                ).execute()
                google_events = events_result.get('items', [])
                
                # Import all Google Calendar events to MongoDB
                for google_event in google_events:
                    try:
                        process_google_calendar_event(google_event, session['user_name'], task_genie.db)
                    except KeyError as e:
                        logger.warning(f"Skipping event due to missing field: {str(e)}")
                        continue
                
                task_genie.db.close()
            
            return redirect('/')
            
        except Exception as e:
            logger.error(f"Error getting user info: {str(e)}")
            flash('Failed to get user information', 'error')
            return redirect('/')
            
    except Exception as e:
        logger.error(f"OAuth callback error: {str(e)}")
        flash('Authentication failed', 'error')
        return redirect('/')

@app.route('/chat', methods=['POST'])
def chat():
    """Handle chat messages"""
    try:
        # Verify user is authenticated
        user_name = session.get('user_name')
        if not user_name:
            return jsonify({'error': 'User not authenticated'}), 401
            
        # Get message from request
        data = request.json
        message = data.get('message')
        if not message:
            return jsonify({'error': 'Missing message'}), 400
            
        # Process message and get response
        task_genie.db.connect()
        action = task_genie.categorizer.categorize_input(message)
        
        response = {
            'action': action,
            'message': '',
            'data': None
        }
        
        # Handle different action types
        if action == 'Query':
            raw_results, filtered_results = run_async(
                task_genie.query_processor.process_query(user_name, message, precise=False)
            )
            response['message'] = filtered_results
            response['data'] = raw_results
            # print(f"Raw results: {raw_results}")
            
            
        elif action == 'Schedule':
            event_task = task_genie.categorizer.categorize_event_task(message)
            if event_task == "Event":
                event_json = task_genie.query_processor.extract_event_information(
                    message, user_name
                )
                response['message'] = "Would you like to schedule this event?"
                response['data'] = event_json
            elif event_task == "Task":
                task_json = task_genie.query_processor.extract_task_information(
                    message, user_name
                )
                response['message'] = "Would you like to schedule this task?"
                response['data'] = task_json
                
        elif action == 'Update':
            # First, find the document to update
            search_prompt = """
            Convert the following update request into a search/query request.
            Keep all the important search criteria (who, what, when, where) but change the action verb to find/show/what/list.
            Relax all the time information from the query.

            Examples:
            - Input: "update my meeting with Bob tomorrow" -> "find my meeting with Bob tomorrow (any time tomorrow)"
            - Input: "change my dentist appointment" -> "when is my dentist appointment (any time)"
            - Input: "modify the team meeting at 3pm" -> "find the team meeting (any time)"

            Update request: "{query}"

            Return only the converted query, nothing else.
            """
            search_query = task_genie.openai_service.create_chat_completion(
                search_prompt.format(query=message),
                "You are an AI assistant specializing in converting update requests into search queries."
            ).strip()
            
            raw_results, _ = run_async(task_genie.query_processor.process_query(user_name, search_query, precise=True))
            # print(f"Raw results: {raw_results}")
            if raw_results and len(raw_results) > 0:
                original_doc = raw_results[0]
                # Determine if it's an event or task
                is_task = 'Due Date' in original_doc
                
                if is_task:
                    query = f"Update the following task as follows: ```{message}```\n\nOriginal task: ```{json.dumps(original_doc, indent=2)} ```"
                    updated_doc = task_genie.query_processor.extract_task_information(query, user_name)
                else:
                    query = f"Update the following event as follows: ```{message}```\n\nOriginal event: ```{json.dumps(original_doc, indent=2)} ```"
                    updated_doc = task_genie.query_processor.extract_event_information(query, user_name)
                print(query)
                
                if updated_doc:
                    # Preserve the original ID and google_event_id
                    updated_doc['_id'] = original_doc['_id']
                    if 'google_event_id' in original_doc:
                        updated_doc['google_event_id'] = original_doc['google_event_id']
                    
                    # Create display data with both original and updated info
                    display_data = {
                        'original': original_doc,
                        'update': updated_doc
                    }
                    
                    response['message'] = "Please confirm the update:"
                    response['data'] = display_data
                else:
                    response['message'] = "Failed to process update information."
            else:
                response['message'] = "No matching events or tasks found."
                
        elif action == 'Delete':
            search_prompt = """
            Convert the following delete request into a search/query request. 
            Keep all the important search criteria (who, what, when, where) but change the action verb to find/show/what/list.
            Relax all the time information from the query.

            Examples:
            - Input: "delete my meeting with Bob tomorrow" -> "find my meeting with Bob tomorrow (any time tomorrow)"
            - Input: "cancel my dentist appointment" -> "what is my dentist appointment (any time)"
            - Input: "clear my schedule for next week" -> "what is my schedule (any time next week)"
            - Input: "drop the team meeting at 3pm" -> "find the team meeting (any time)"
            - Input: "cancel my tasks tomorrow" -> "what are my tasks (any time tomorrow)"

            Delete request: "{query}"

            Return only the converted query, nothing else.
            """
            search_query = task_genie.openai_service.create_chat_completion(
                search_prompt.format(query=message),
                "You are an AI assistant specializing in converting delete requests into search queries."
            ).strip()

            print(f"Search query: {search_query}")
            
            raw_results, _ = run_async(task_genie.query_processor.process_query(user_name, search_query, precise=True))
            print(f"Raw results: {raw_results}")
            if raw_results:
                response['message'] = "Found this matching document to delete:"
                response['data'] = raw_results[0]
            else:
                response['message'] = "No matching events or tasks found."
                
        elif action == 'Conversation':
            system_content = f"You are TaskGenie, a concise AI assistant. The user is {user_name}."
            response_content, conversation_history = task_genie.openai_service.create_chat_conversation(
                message,
                system_content,
                user_sessions.get(user_name, {}).get('conversation_history', [])
            )
            if user_name not in user_sessions:
                user_sessions[user_name] = {}
            user_sessions[user_name]['conversation_history'] = conversation_history
            print(f"Conversation history: {conversation_history}")
            response['message'] = response_content
            
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Error in chat: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        task_genie.db.close()

def sync_with_google_calendar(user_email, event):
    """Sync single event with Google Calendar"""
    if 'credentials' not in session:
        logger.warning("No credentials found in session")
        return False
        
    credentials = Credentials(**session['credentials'])
    
    if not credentials.valid:
        if credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(Request())
                session['credentials']['token'] = credentials.token
            except Exception as e:
                logger.error(f"Failed to refresh credentials: {str(e)}")
                return False
        else:
            logger.warning("Invalid credentials and cannot refresh")
            return False
            
    service = build('calendar', 'v3', credentials=credentials)
    
    try:
        # Ensure datetime is in RFC3339 format
        start_time = datetime.fromisoformat(event['Start Time'].replace('Z', '+00:00'))
        end_time = datetime.fromisoformat(event['End Time'].replace('Z', '+00:00'))
        
        calendar_event = {
            'summary': event['Title'],
            'description': event.get('Description', ''),
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'America/New_York',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'America/New_York',
            },
            'location': event.get('Location', ''),
            'reminders': {
                'useDefault': True
            }
        }
        
        try:
            # If event has a Google Calendar ID, update it
            if 'google_event_id' in event:
                try:
                    # Try to get the event first to make sure it exists
                    service.events().get(
                        calendarId='primary',
                        eventId=event['google_event_id']
                    ).execute()
                    
                    # If event exists, update it
                    result = service.events().update(
                        calendarId='primary',
                        eventId=event['google_event_id'],
                        body=calendar_event
                    ).execute()
                except Exception as e:
                    # If event doesn't exist in Google Calendar, create new one
                    logger.warning(f"Event not found in Google Calendar, creating new: {str(e)}")
                    result = service.events().insert(
                        calendarId='primary', 
                        body=calendar_event
                    ).execute()
            else:
                # Create new event
                result = service.events().insert(
                    calendarId='primary', 
                    body=calendar_event
                ).execute()
                
            # Store the Google Calendar event ID
            event['google_event_id'] = result['id']
            
            # Update the event in MongoDB with the new google_event_id
            if '_id' in event:
                task_genie.db.db['events'].update_one(
                    {'_id': ObjectId(event['_id'])},
                    {'$set': {'google_event_id': result['id']}}
                )
                
            logger.info(f"Successfully synced event {event['Title']} with Google Calendar")
            return True
            
        except Exception as e:
            logger.error(f"Error syncing with Google Calendar: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"Error preparing event data: {str(e)}")
        return False

@app.route('/confirm', methods=['POST'])
def confirm_action():
    try:
        data = request.json
        action = data.get('action')
        confirmed = data.get('confirmed')
        document = data.get('document')
        
        user_name = session.get('user_name')
        user_email = session.get('user_email')
        
        if not user_name:
            return jsonify({'error': 'User not authenticated'}), 401
            
        if not all([action, confirmed is not None, document]):
            return jsonify({'error': 'Missing required fields'}), 400
            
        task_genie.db.connect()
        
        if not confirmed:
            return jsonify({'message': 'Action cancelled'})

        # Helper function to reschedule and sync tasks
        def reschedule_and_sync_tasks():
            if user_name == 'guest':
                return
                
            try:
                # Reschedule all tasks
                task_genie.task_scheduler.calculate_task_metrics(user_name)
                task_genie.task_scheduler.calculate_task_urgency(user_name)
                task_genie.task_scheduler.schedule_tasks(user_name)
                logger.info("Successfully scheduled tasks")
                
                # Sync all tasks with Google Calendar
                all_tasks = task_genie.db.db['tasks'].find({'User': user_name})
                for task in all_tasks:
                    sync_success = sync_with_google_calendar(user_email, task)
                    if sync_success:
                        task_genie.db.db['tasks'].update_one(
                            {'_id': task['_id']},
                            {'$set': {'google_event_id': task['google_event_id']}}
                        )
                    else:
                        logger.warning(f"Failed to sync task {task['_id']} with Google Calendar")
            except Exception as e:
                logger.error(f"Error in reschedule_and_sync_tasks: {str(e)}")
            
        if action == 'Schedule':
            collection = 'tasks' if 'Due Date' in document else 'events'
            
            # Initialize google_event_id if not present
            if 'google_event_id' not in document:
                document['google_event_id'] = None
                
            doc_id = task_genie.db.add_document(collection, document)
            document['_id'] = str(doc_id)
            
            # Reschedule and sync tasks
            reschedule_and_sync_tasks()
            
            # If it's an event, sync it with Google Calendar
            if collection == 'events' and user_name != 'guest':
                sync_success = sync_with_google_calendar(user_email, document)
                if sync_success:
                    task_genie.db.db[collection].update_one(
                        {'_id': ObjectId(doc_id)},
                        {'$set': {'google_event_id': document['google_event_id']}}
                    )
            
            return jsonify({
                'message': f'Successfully scheduled the {collection[:-1]}',
                'document': document
            })
            
        elif action == 'Update':
            collection = 'tasks' if 'Due Date' in document['update'] else 'events'
            update_doc = document['update']
            doc_id = update_doc.pop('_id', None)
            
            if not doc_id:
                return jsonify({'error': 'Document ID missing'}), 400
                
            # Preserve google_event_id if it exists
            original_doc = task_genie.db.db[collection].find_one({'_id': ObjectId(doc_id)})
            if original_doc and 'google_event_id' in original_doc:
                update_doc['google_event_id'] = original_doc['google_event_id']
            
            result = task_genie.db.db[collection].update_one(
                {'_id': ObjectId(doc_id)},
                {'$set': update_doc}
            )
            
            if result.modified_count != 1:
                return jsonify({'error': 'Failed to update the document'}), 400
                
            # Get the updated document
            updated_doc = task_genie.db.db[collection].find_one({'_id': ObjectId(doc_id)})
            updated_doc['_id'] = str(updated_doc['_id'])
            
            # Reschedule and sync tasks
            reschedule_and_sync_tasks()
            
            # If it's an event, sync it with Google Calendar
            if collection == 'events' and user_name != 'guest':
                sync_success = sync_with_google_calendar(user_email, updated_doc)
                if sync_success:
                    task_genie.db.db[collection].update_one(
                        {'_id': ObjectId(doc_id)},
                        {'$set': {'google_event_id': updated_doc['google_event_id']}}
                    )
            
            return jsonify({
                'message': 'Successfully updated the document',
                'document': updated_doc
            })
            
        elif action == 'Delete':
            collection = 'tasks' if 'Due Date' in document else 'events'
            document_id = document.get('_id')
            
            if not document_id:
                return jsonify({'error': 'Document ID missing'}), 400
                
            # Delete from Google Calendar first if applicable
            if user_name != 'guest':
                try:
                    credentials = Credentials(**session['credentials'])
                    service = build('calendar', 'v3', credentials=credentials)
                    
                    event = task_genie.db.db[collection].find_one({'_id': ObjectId(document_id)})
                    if event and 'google_event_id' in event:
                        service.events().delete(
                            calendarId='primary',
                            eventId=event['google_event_id']
                        ).execute()
                except Exception as e:
                    logger.warning(f"Failed to delete event from Google Calendar: {str(e)}")
            
            result = task_genie.db.db[collection].delete_one(
                {'_id': ObjectId(document_id)}
            )
            
            if result.deleted_count != 1:
                return jsonify({'error': 'Failed to delete the document'}), 400
                
            # Reschedule and sync tasks
            reschedule_and_sync_tasks()
            
            return jsonify({
                'message': 'Successfully deleted the document',
                'document_id': str(document_id)
            })
            
        return jsonify({'error': 'Invalid action'}), 400
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        task_genie.db.close()

@app.route('/get_calendar_events', methods=['POST'])
def get_calendar_events():
    try:
        data = request.json
        user_name = data.get('user_name')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        
        if not all([user_name, start_date, end_date]):
            return jsonify({'error': 'Missing required fields'}), 400
            
        task_genie.db.connect()
            
        # Query events
        events_query = {
            'User': {'$regex': f"\\b{re.escape(user_name)}\\b", '$options': 'i'},
            'Start Time': {
                '$gte': start_date,
                '$lte': end_date
            }
        }
        events = task_genie.db.execute_query('events', events_query)
        
        # Query tasks
        tasks_query = {
            'User': {'$regex': f"\\b{re.escape(user_name)}\\b", '$options': 'i'},
            '$or': [
                {'Start Time': {
                    '$gte': start_date,
                    '$lte': end_date
                }},
                {'Due Date': {
                    '$gte': start_date,
                    '$lte': end_date
                }}
            ]
        }
        tasks = task_genie.db.execute_query('tasks', tasks_query)

        # Serialize documents
        events = task_genie.task_scheduler.serialize_document(events)
        tasks = task_genie.task_scheduler.serialize_document(tasks)

        # Format dates in events and tasks
        formatted_events = []
        for event in events:
            event_copy = {k: v for k, v in event.items() if k != 'key_embedding'}
            event_copy['_id'] = str(event_copy['_id']) if '_id' in event_copy else None
            
            # Ensure google_event_id exists
            if 'google_event_id' not in event_copy:
                event_copy['google_event_id'] = None
            
            for date_field in ['Start Time', 'End Time']:
                if date_field in event_copy:
                    try:
                        dt = datetime.strptime(event_copy[date_field], '%Y-%m-%d %H:%M:%S')
                        event_copy[date_field] = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError):
                        event_copy[date_field] = None
                        
            formatted_events.append(event_copy)

        formatted_tasks = []
        for task in tasks:
            task_copy = {k: v for k, v in task.items() if k != 'key_embedding'}
            task_copy['_id'] = str(task_copy['_id']) if '_id' in task_copy else None
            
            # Ensure google_event_id exists
            if 'google_event_id' not in task_copy:
                task_copy['google_event_id'] = None
            
            for date_field in ['Start Time', 'Due Date']:
                if date_field in task_copy:
                    try:
                        dt = datetime.strptime(task_copy[date_field], '%Y-%m-%d %H:%M:%S')
                        task_copy[date_field] = dt.strftime('%Y-%m-%d %H:%M:%S')
                    except (ValueError, TypeError):
                        task_copy[date_field] = None
                        
            formatted_tasks.append(task_copy)

        logger.info(f"Found {len(formatted_events)} events and {len(formatted_tasks)} tasks")

        return jsonify({
            'events': formatted_events,
            'tasks': formatted_tasks
        })
        
    except Exception as e:
        logger.error(f"Error getting calendar events: {str(e)}")
        return jsonify({'error': str(e)}), 500
    finally:
        task_genie.db.close()

def refresh_google_credentials():
    """Helper function to check and refresh Google credentials"""
    if 'credentials' not in session:
        return None
        
    try:
        credentials = Credentials(**session['credentials'])
        
        if not credentials.valid:
            if credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
                session['credentials'] = {
                    'token': credentials.token,
                    'refresh_token': credentials.refresh_token,
                    'token_uri': credentials.token_uri,
                    'client_id': credentials.client_id,
                    'client_secret': credentials.client_secret,
                    'scopes': credentials.scopes
                }
                return credentials
            return None
        return credentials
    except Exception as e:
        logger.error(f"Error refreshing credentials: {str(e)}")
        return None

def process_google_calendar_event(google_event, user_name, db):
    """Process a single Google Calendar event"""
    if 'dateTime' not in google_event['start'] and 'dateTime' not in google_event['start']:
        return

    start = google_event['start'].get('dateTime')
    end = google_event['end'].get('dateTime')
    
    if not start or not end:
        raise KeyError("Missing start or end time")

    # Parse datetime with or without time component
    start_dt = datetime.fromisoformat(start)
    end_dt = datetime.fromisoformat(end)
    
    start_time = start_dt.strftime('%Y-%m-%d %H:%M:%S')
    end_time = end_dt.strftime('%Y-%m-%d %H:%M:%S')
    
    db_event = {
        'User': user_name,
        'Title': google_event.get('summary', 'Untitled Event'),
        'Description': google_event.get('description', ''),
        'Start Time': start_time,
        'End Time': end_time,
        'Location': google_event.get('location', ''),
        'google_event_id': google_event['id']
    }
    
    # Update or insert event
    db.db['events'].update_one(
        {
            'google_event_id': google_event['id'],
            'User': user_name
        },
        {'$set': db_event},
        upsert=True
    )

def sync_mongodb_event_to_google(mongo_event, service, google_events_dict):
    """Sync a single MongoDB event to Google Calendar"""
    try:
        # Convert datetime strings to proper format
        start_time = datetime.strptime(mongo_event['Start Time'], '%Y-%m-%d %H:%M:%S')
        end_time = datetime.strptime(mongo_event['End Time'], '%Y-%m-%d %H:%M:%S')
        
        calendar_event = {
            'summary': mongo_event['Title'],
            'description': mongo_event.get('Description', ''),
            'start': {
                'dateTime': start_time.isoformat(),
                'timeZone': 'America/New_York',
            },
            'end': {
                'dateTime': end_time.isoformat(),
                'timeZone': 'America/New_York',
            },
            'location': mongo_event.get('Location', ''),
            'reminders': {
                'useDefault': True
            }
        }
        
        try:
            if 'google_event_id' in mongo_event:
                if mongo_event['google_event_id'] in google_events_dict:
                    result = service.events().update(
                        calendarId='primary',
                        eventId=mongo_event['google_event_id'],
                        body=calendar_event
                    ).execute()
                else:
                    result = service.events().insert(
                        calendarId='primary',
                        body=calendar_event
                    ).execute()
                    mongo_event['google_event_id'] = result['id']
            else:
                result = service.events().insert(
                    calendararId='primary',
                    body=calendar_event
                ).execute()
                mongo_event['google_event_id'] = result['id']
                
            # Update MongoDB with the new google_event_id
            if 'google_event_id' in mongo_event:
                task_genie.db.db['events'].update_one(
                    {'_id': mongo_event['_id']},
                    {'$set': {'google_event_id': mongo_event['google_event_id']}}
                )
                
        except Exception as e:
            logger.error(f"Error syncing event to Google Calendar: {str(e)}")
            raise
            
    except Exception as e:
        logger.error(f"Error preparing event data: {str(e)}")
        raise


if __name__ == '__main__':
    app.run(debug=True)