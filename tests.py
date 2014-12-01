from datetime import datetime
from django.test import TestCase
from django.contrib.auth import get_user_model
from pyechonest.util import EchoNestException

from .models import EmailTime
import views


class EmailsTests(TestCase):

    def setUp(self):

        User = get_user_model()
        self.users = users = []
        for name in ['bob', 'alice']:
            user = User(username=name,
                        email='linernotes.robot@gmail.com')
            users.append(user)
        User.objects.bulk_create(users)

        now = datetime.utcnow()
        ets = []
        for user in users:
            ets.append(EmailTime(user=user,
                                 time=now))
        EmailTime.objects.bulk_create(ets)

    def test_connection(self):

        conn = views.connect()
        ehlo = conn.ehlo()
        self.assertEqual(ehlo[0], 250)

    def test_handle_error(self):

        exc = Exception('test_error')
        self.assertRaises(Exception, views.handle_error, True, exc,
                          'test_handle_error', raise_=True)

        exc = EchoNestException(code=1)
        val = views.handle_error(False, exc, 'test_handle_error')
        self.assertEqual(val, views.ERROR_SLEEP_TIME)

        exc = EchoNestException(code=3)
        val = views.handle_error(False, exc, 'test_handle_error')
        self.assertEqual(val, views.ERROR_SLEEP_TIME_ON_RACE_EXC)
