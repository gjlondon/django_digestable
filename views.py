import random
import time
import urllib2
import logging
import pytz
import gevent
from gevent.pool import Pool
from datetime import datetime, timedelta
from celery import task
from pyechonest.util import EchoNestException
from email.mime.text import MIMEText
import smtplib
from django.db import transaction
from django.conf import settings
from django.template.loader import render_to_string
from django.contrib.auth import get_user_model

from emails.email_setttings import ERROR_SLEEP_TIME_ON_RACE_EXC, ERROR_SLEEP_TIME, EMAIL_DELIVERY_HOST, \
    EMAIL_DELIVERY_PORT, EMAIL_CONNECTION_RETRIES, EMAIL_DELIVERY_HOST_USER, EMAIL_DELIVERY_HOST_PASSWORD, \
    EMAIL_FROM_ADDRESS, SEND_EMAILS, EMAIL_DEBUG_FLAG, EMAIL_DEBUG_USERNAMES, DEFAULT_EMAIL_SUBJECT


User = get_user_model()

from .models import EmailTime

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
gevent_pool = gevent.pool.Pool(size=10)


class RescheduleException(Exception):

    def __init__(self, err, **kwargs):
        # err: original exception
        self.err = err
        super(RescheduleException, self).__init__(**kwargs)


@transaction.commit_manually
def bulk_update(objects):
    try:
        for o in objects:
            o.save()
    except Exception as err:
        transaction.rollback_unless_managed()
        raise err
    else:
        transaction.commit()

    return objects


def handle_error(finish, error, message, raise_=False):
    if finish is False:
        logger.info('{message}: {error:s}'.
                    format(message=message, error=error))
        if isinstance(error, EchoNestException) \
                and error.code == 3:
            return ERROR_SLEEP_TIME_ON_RACE_EXC
        else:
            return ERROR_SLEEP_TIME
    else:
        logger.error('{message}: {error:s}'.
                     format(message=message, error=error))
        if raise_ is True:
            raise error


def call_echonest_api(method, args=(), kwargs=None,
                      ignore_error_codes=(), raise_=False):
    """ Helper function to call EchoNest API.  Returns data from EchoNest API
    call.

    :param method: pyechonest callable object
    :param args: args for method
    :param kwargs: kwargs for method
    :param ignore_error_codes: error codes to ignore
    :param raise_: argument passed to handle_error
    """

    logger.info('{}'.format(method))
    if kwargs is None:
        kwargs = {}
    data = None

    RETRIES = 5
    i = 0
    while i < RETRIES:
        i += 1
        error = None
        try:
            stime = time.time()
            data = method(*args, **kwargs)
            logger.info('{}: returned in {:.3f}s.'.
                        format(method, time.time() - stime))
            break
        except (EchoNestException, urllib2.HTTPError) as error:
            if isinstance(error, EchoNestException):
                if error.code in ignore_error_codes:
                    error = None
                    break
            sleep = handle_error(
                i > RETRIES,
                error,
                'error in: {} '.format(method),
                raise_=raise_)
            if sleep is not None:
                time.sleep(sleep)

    return data, error


class GreenletWithArgs(gevent.Greenlet):

    def run(self):
        """
        Greenlet.run methods removes args and kwargs from __dict__, we need
        them to reschedule the task.
        """

        args, kwargs = self.args, self.kwargs
        super(GreenletWithArgs, self).run()
        if 'args' not in self.__dict__:
            self.__dict__['args'] = args
        if 'kwargs' not in self.__dict__:
            self.__dict__['kwargs'] = kwargs


class PoolWithArgs(Pool):

    greenlet_class = GreenletWithArgs


def compose_email(to, context,
                  email_subject=DEFAULT_EMAIL_SUBJECT,
                  debug=False):

    content = render_to_string('emails/email.html', context)
    msg = MIMEText(content.encode('UTF-8'), 'html')
    msg['Subject'] = email_subject
    msg['From'] = EMAIL_FROM_ADDRESS
    msg['To'] = to

    return msg


def connect():
    """ Establish an smtp connection.
    """
    logger.info('establishing smtp connection with %s using port %d'
                % (EMAIL_DELIVERY_HOST,
                   EMAIL_DELIVERY_PORT))
    conn = smtplib.SMTP(EMAIL_DELIVERY_HOST,
                        EMAIL_DELIVERY_PORT)
    logger.info('logged in')
    (code, resp) = conn.ehlo()
    if not (200 <= code <= 299):
        raise smtplib.SMTPHeloError(code, resp)
    conn.starttls()
    (code, resp) = conn.ehlo()
    if not (200 <= code <= 299):
        raise smtplib.SMTPHeloError(code, resp)

    i = 0
    while i <= EMAIL_CONNECTION_RETRIES:
        i += 1
        err = None
        try:
            conn.login(EMAIL_DELIVERY_HOST_USER,
                       EMAIL_DELIVERY_HOST_PASSWORD)
        except smtplib.SMTPAuthenticationError as err:
            pass

        if err is None:
            break
        else:
            logger.error('{err.__class__.__name__}: {err}'.format(err=err))
            try:
                conn.quit()
            except smtplib.SMTPServerDisconnected:
                pass
            sleep_time = handle_error(
                i >= EMAIL_CONNECTION_RETRIES,
                err,
                'connection error',
                raise_=True)
            if sleep_time is not None:
                time.sleep(sleep_time)

    return conn


def get_data_for_emails():
    return


def email_context(user):
    return


@task()
def send_emails(usernames=None, from_addr=EMAIL_FROM_ADDRESS):
    """
    Sending emails.

    :from_addr: use this address in From email header
    :usernames: list of usernames to send emails to.  If it is None, read users
        using the EmailTime model.
    """

    if SEND_EMAILS is False and usernames is None:
        return

    if EMAIL_DEBUG_FLAG is False:
        staff_emails = [user.email for user in User.objects.filter(is_staff=True)]

    start_time = datetime.utcnow()
    # user list with favorites
    if usernames is None:
        email_users = EmailTime.objects. \
            filter(time <= start_time). \
            select_related('user'). \
            prefetch_related('user__favorite_set',
                             'user__profile_set'). \
            all()
        if EMAIL_DEBUG_FLAG is True:
            email_users = email_users. \
                filter(user__username__in=EMAIL_DEBUG_USERNAMES)
        # Note: it would be better for performance to have User <-> Profile
        # a one-to-one field and use select_related instead of
        # prefetch_related.
        users = set([eu.user for eu in email_users])

    else:
        users = User.objects. \
            select_related('emailtime'). \
            prefetch_related('favorite_set', 'profile_set'). \
            filter(username__in=usernames)
        users = set(users)

    _users = set()
    delete_ids = []
    for user in users:
        try:
            profile = user.profile_set.all()[0]
        except IndexError:
            digest = True
        else:
            digest = profile.receive_digests
        if digest:
            _users.add(user)
        else:
            # delete EmailTime for users how opted out Profile.receive_digest
            try:
                delete_ids.append(user.emailtime.id)
            except EmailTime.DoesNotExist:
                # this might only happend when username is not None
                pass
    users = _users

    if delete_ids:
        # bulk_delete:
        EmailTime.objects.filter(id__in=delete_ids).delete()

    # get data
    try:
        results = get_data_for_emails()
    except RescheduleException as err:
        if usernames is None:
            logger.warn('Resheduling emails on: {err}.'.format(err=str(err.err)))
            now = datetime.utcnow().replace(tzinfo=pytz.utc)
            for email in email_users:
                email.time = now + timedelta(hours=1)
            bulk_update(email_users)
        return

    emails = []
    for user in users:
        # create email using dict_of_results_for_artists_by_id
        context = email_context(user)
        if usernames is not None or settings.EMAIL_DEBUG_FLAG is True:
            to = " ".join(staff_emails)
        else:
            to = user.email
        emails.append((user,
                       compose_email(to,
                                     context,
                                     debug=usernames is not None),
                       context,))

    conn = connect()  # open SMTP connection

    for user, email, context in emails:
        # Note: context in this loop can be used to record sent items
        for i in range(1, settings.EMAIL_SEND_RETRIES):
            error = None
            try:
                logger.info('sending email to {user.username} ({user.email})'.
                            format(user=user))
                if settings.EMAIL_DEBUG_FLAG is True or usernames is not None:
                    email_addresses = staff_emails
                else:
                    email_addresses = (user.email.encode('UTF-8'),)
                refused = conn.sendmail(from_addr,
                                        email_addresses,
                                        email.as_string())
            except smtplib.SMTPServerDisconnected as error:
                logger.error("{}: {}".
                             format(error.__class__.__name__,
                                    str(error)))
                conn = connect()

            except (smtplib.SMTPSenderRefused, smtplib.SMTPConnectError) as error:
                logger.error("{}: smtp_code={}, {}".
                             format(error.__class__.__name__,
                                    error.smtp_code,
                                    str(error)))
                try:
                    conn.close()
                except:
                    pass
                conn = connect()

            except smtplib.SMTPRecipientsRefused as error:
                logger.error("{}: smtp_code={}, {}".
                             format(error.__class__.__name__,
                                    error.smtp_code,
                                    str(error)))
                break

            except smtplib.SMTPDataError as error:
                logger.error("{}: smtp_code={}, {}".
                             format(error.__class__.__name__,
                                    error.smtp_code,
                                    str(error)))
                break
            except smtplib.SMTPException as error:
                logger.error("{}: smtp_code={}, {}".
                             format(error.__class__.__name__,
                                    error.smtp_code,
                                    str(error)))
            else:
                # TODO: record send items (context)
                if not refused:
                    break

        # Set next email date
        # usernames is an arg of send_emails (testing)
        if usernames is None:
            if error is None:
                t = start_time + \
                    timedelta(days=random.randint(0, 4), hours=random.randint(0, 23))
                t = t.replace(tzinfo=pytz.utc)
                email_time = EmailTime.objects.get_or_create(user=user)
                email_time.time = t
                email_time.save()
            else:
                if not isinstance(error, smtplib.SMTPRecipientsRefused):
                    # do not reschedule if the server did not recognize the email
                    email_time = EmailTime.objects.get_or_create(user=user)
                    t = datetime.utcnow() + timedelta(hours=1)
                    t = t.replace(tzinfo=pytz.utc)
                    email_time.time = t
                    email_time.save()
    try:
        conn.quit()
    except:
        pass


def subscribe_users_to_emails(user_ids):
    """
        :param user_ids: a tuple of User.id's.
    """

    now = datetime.utcnow().replace(tzinfo=pytz.utc)
    ets = []
    for user_id in user_ids:
        et = EmailTime(user_id=user_id,
                       time=now + timedelta(days=random.randint(0, 4),
                                            hours=random.randint(0, 23)))
        ets.append(et)

    EmailTime.objects.bulk_create(ets)
