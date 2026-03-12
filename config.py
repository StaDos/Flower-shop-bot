import os
from dotenv import load_dotenv

load_dotenv()

MAIN_BOT_TOKEN = os.getenv('MAIN_BOT_TOKEN')
MODERATOR_BOT_TOKEN = os.getenv('MODERATOR_BOT_TOKEN')
MESSAGE_BOT_TOKEN = os.getenv('MESSAGE_BOT_TOKEN')


API_KEY_LLM = os.getenv('API_KEY_LLM')
API_KEY = os.getenv('API_KEY')

MY_ID = int(os.getenv('MY_ID'))
CHANNEL_ID = int(os.getenv('CHANNEL_ID'))
MAIN_CHANNEL_ID = int(os.getenv('MAIN_CHANNEL_ID'))
