import os
from dotenv import load_dotenv
from telegram import Update, KeyboardButton, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, filters, ContextTypes
import requests
import os.path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import datetime
import pytz

SCOPES = ["https://www.googleapis.com/auth/calendar"]

load_dotenv()
GOOGLE_TIMEZONE_API_KEY = os.getenv("GOOGLE_TIMEZONE_API_KEY")
TOKEN = os.getenv("TELEGRAM_TOKEN")

TITLE, START, END, LOCATION, CODE = range(5)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Hello\nUse /help command to get help")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("To get a question you need to use /question command to enter a topic")

async def quote_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    response = requests.get("http://localhost:8000/quote").json()
    quote = response[0]["quote"]

    await update.message.reply_text(quote)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Operation canceled.")
    return ConversationHandler.END

async def task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("What is the title of your task?")
    return TITLE

async def title_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['title'] = update.message.text
    await update.message.reply_text("Enter the start date of your task? (YYYY-MM-DD HH:MM:SS)")
    return START

async def start_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['start'] = update.message.text
    await update.message.reply_text("Enter the end date of your task? (YYYY-MM-DD HH:MM:SS)")

    return END

async def end_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['end'] = update.message.text
    await update.message.reply_text(
    'Please share your location for timezone information:',
    reply_markup=ReplyKeyboardMarkup([[KeyboardButton("Share Location", request_location=True)]], one_time_keyboard=True)
    )

    return LOCATION

async def location_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_location = update.message.location
    context.user_data['location'] = (user_location.latitude, user_location.longitude)
    timezone_str = get_timezone(context.user_data['location'])
    start_date_str = context.user_data['start']
    end_date_str = context.user_data['end']
    dt_start = datetime.datetime.strptime(start_date_str, "%Y-%m-%d %H:%M:%S")
    dt_end = datetime.datetime.strptime(end_date_str, "%Y-%m-%d %H:%M:%S")
    # Add the timezone information
    timezone = pytz.timezone(timezone_str)
    dt_start = timezone.localize(dt_start)
    dt_end = timezone.localize(dt_end)


    # Use the run_console method to get the URL and send it to the user
    
    flow = InstalledAppFlow.from_client_secrets_file(
        'credentials.json', SCOPES
    )
    flow.redirect_uri = 'urn:ietf:wg:oauth:2.0:oob'
    auth_url, _ = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )

    context.user_data['flow'] = flow
    context.user_data['dt_start'] = dt_start
    context.user_data['dt_end'] = dt_end
    context.user_data['timezone_str'] = timezone_str

    await update.message.reply_text(
        "Please visit the following URL to authorize this application and provide the code here:\n" + auth_url
    )

    # Pause here and wait for the user to enter the authorization code
    return CODE

async def auth_code_response(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    flow = context.user_data['flow']
    dt_start = context.user_data['dt_start']
    dt_end = context.user_data['dt_end']
    timezone_str = context.user_data['timezone_str']
    code = update.message.text

    try:
        flow.fetch_token(code=code)
        creds = flow.credentials

        service = build("calendar", "v3", credentials=creds)

        event = {
            'summary': context.user_data['title'],
            'start': {
                'dateTime': dt_start.isoformat(),
                'timeZone': timezone_str,
            },
            'end': {
                'dateTime': dt_end.isoformat(),
                'timeZone': timezone_str,
            }
        }

        event = service.events().insert(calendarId='primary', body=event).execute()
        await update.message.reply_text(f"Event created: {event.get('htmlLink')}")
    except Exception as e:
        await update.message.reply_text(f"Failed to create event: {str(e)}")

    return ConversationHandler.END


def get_timezone(location):
    latitude, longitude = location
    timestamp = int(datetime.datetime.now().timestamp())
    url = f"https://maps.googleapis.com/maps/api/timezone/json?location={latitude},{longitude}&timestamp={timestamp}&key={GOOGLE_TIMEZONE_API_KEY}"
    
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        if data['status'] == 'OK':
            return data['timeZoneId']
    return None

async def error(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    print(f"Update {update} caused error {context.error}")

if __name__ == "__main__":
    print("starting bot...")
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("quote", quote_command))
    conv_handler2 = ConversationHandler(
        entry_points=[CommandHandler('task', task)],
        states={
            TITLE: [MessageHandler(filters.TEXT, title_response)],
            START: [MessageHandler(filters.TEXT, start_response)],
            END: [MessageHandler(filters.TEXT, end_response)],
            LOCATION: [MessageHandler(filters.LOCATION, location_response)],
            CODE : [MessageHandler(filters.TEXT, auth_code_response)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    app.add_handler(conv_handler2)
    app.add_error_handler(error)

    print("polling...")
    app.run_polling(poll_interval=3)
