import os

__author__ = 'rogueleaderr'


ERROR_SLEEP_TIME = 5
ERROR_SLEEP_TIME_ON_RACE_EXC = 30
EMAIL_DELIVERY_HOST = str(os.getenv("EMAIL_DELIVERY_SERVER"))
EMAIL_DELIVERY_HOST_USER = str(os.getenv("EMAIL_DELIVERY_USER"))
EMAIL_DELIVERY_HOST_PASSWORD = str(os.getenv("EMAIL_DELIVERY_PASSWORD"))
EMAIL_DELIVERY_PORT = int(os.getenv("EMAIL_DELIVERY_PORT"))
EMAIL_FROM_ADDRESS = str(os.getenv("EMAIL_FROM_ADDRESS"))
EMAIL_USE_TLS = True
SEND_EMAILS = False
EMAIL_CONNECTION_RETRIES = 10
EMAIL_SEND_RETRIES = 5
EMAIL_DEBUG_FLAG = False  # if True send emails to User.is_staff instead to recipients.
EMAIL_DEBUG_USERNAMES = ('george',)  # usernames for which emails are generated if EAIL_DEBUG_FLAG is True
DEFAULT_EMAIL_SUBJECT = "hi"