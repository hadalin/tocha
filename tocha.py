# -*- coding: utf-8 -*-

import sys
import locale
import logging
import time
import datetime
import re
import argparse
from configparser import ConfigParser
import feedparser
import tweepy
import math
from urllib.request import urlopen, HTTPError
from io import StringIO


# Parameters
PERIOD = 600  # Seconds
ALERT_LEVEL = 3
ALERT_WINDOW = 120  # Minutes
REGEX_LEVEL = re.compile("stopnja (?P<level>(-|0|1|2|3))/3")
REGEX_TIME = re.compile("(?P<time>[0-9][0-9]:[0-9][0-9]) CE")
THROTTLE = 1  # Seconds
TWITTER_ENABLED = True
IMAGE_URL = 'http://meteo.arso.gov.si/uploads/probase/www/warning/graphic/warning_hp-sr_si-sea_latest.jpg'


# Logging
class InfoFilter(logging.Filter):
    def filter(self, rec):
        return rec.levelno in (logging.DEBUG, logging.INFO)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

out_handler = logging.StreamHandler(sys.stdout)
out_handler.addFilter(InfoFilter())
out_handler.setFormatter(formatter)
out_handler.setLevel(logging.INFO)
logger.addHandler(out_handler)

err_handler = logging.StreamHandler(sys.stderr)
err_handler.setFormatter(formatter)
err_handler.setLevel(logging.WARNING)
logger.addHandler(err_handler)


def throttle(decorated):
    def wrapper(*args, **kw):
        decorated(*args, **kw)
        time.sleep(THROTTLE)
    return wrapper


@throttle
def tweet(twitter_api, twitter_verified, location, timestamp):
    if twitter_verified:
        status = u"%s [%s. %s]" % (location, time.strftime("%a").lower(), timestamp)
        logger.info("Tweet %s" % status)
        if TWITTER_ENABLED:
            try:
                # Update status with image
                image = urlopen(IMAGE_URL)
                f = StringIO(image.read())
                image.close()
                twitter_api.update_with_media(filename='pic.jpg', status=status, file=f)
                f.close()
            except HTTPError:
                # Update status text only and report the problem
                twitter_api.update_status(status=status)
                logger.error('Updated status text only without media')


def process_feeds(twitter_api, twitter_verified, feeds):
    for item in feeds:
        location = item[0]
        feed = feedparser.parse(item[1])
        alert_timestamp = item[2]

        # Continue if status attribute exists and equals 200
        if hasattr(feed, 'status') and feed.status == 200:

            # Entries count must equal 1
            if len(feed.entries) == 1:

                # Search for expected string
                match_level = REGEX_LEVEL.search(feed.entries[0].title)
                match_time = REGEX_TIME.search(feed.entries[0].title)

                match_level_ok = hasattr(match_level, 'groupdict') and len(match_level.groupdict()) == 1
                match_time_ok = hasattr(match_time, 'groupdict') and len(match_time.groupdict()) == 1
                if match_level and match_level_ok and match_time and match_time_ok:
                    level = int(match_level.groupdict()['level'])
                    timestamp = match_time.groupdict()['time']

                    if alert_timestamp is not None and alert_timestamp <= (datetime.datetime.now() - datetime.timedelta(minutes=ALERT_WINDOW)):
                        item[2] = None  # Reset alert timestamp

                    if level == ALERT_LEVEL and alert_timestamp is None:
                        item[2] = datetime.datetime.now()  # Set alert timestamp
                        tweet(twitter_api, twitter_verified, location, timestamp)
                else:
                    logger.warn('Error parsing {} feed'.format(location))
            else:
                logger.warn('{} feed entries count not equals 1'.format(location))
        else:
            logger.warn('{} feed status not 200 or no status attribute'.format(location))


def parse_config(file_path):
    config = ConfigParser()

    options = {
        'feeds': None,
        'twitter': {
            'consumer_key': None,
            'consumer_secret': None,
            'access_token': None,
            'access_token_secret': None
        }
    }

    # Check config file path
    if file_path:
        config.read(file_path)

        if config.has_option('Twitter', 'consumer_key'):
            options['twitter']['consumer_key'] = config.get('Twitter', 'consumer_key')
        if config.has_option('Twitter', 'consumer_secret'):
            options['twitter']['consumer_secret'] = config.get('Twitter', 'consumer_secret')
        if config.has_option('Twitter', 'access_token'):
            options['twitter']['access_token'] = config.get('Twitter', 'access_token')
        if config.has_option('Twitter', 'access_token_secret'):
            options['twitter']['access_token_secret'] = config.get('Twitter', 'access_token_secret')

        # Check if Feeds section exists
        if not config.has_section('Feeds'):
            error = 'Feeds section not present in config file (check config file name also)'
            logger.error(error)
        else:
            # Good to go
            options['feeds'] = []
            section_feeds_options = config.options('Feeds')
            for option in section_feeds_options:
                option_sliced = config.get('Feeds', option).split('|')
                try:
                    location = option_sliced[0]
                    feed = option_sliced[1]
                except IndexError:
                    error = 'Error parsing config file'
                    logger.error(error)
                    options['feeds'] = []  # Set empty feed list
                    break

                options['feeds'].append([location, feed, None])
    else:
        error = 'No config file'
        logger.error(error)

    return options


def main():
    logger.info('Start')

    twitter_verified = False
    locale_set = False

    argparser = argparse.ArgumentParser()
    argparser.add_argument("-C", "--config", help="Configuration file")
    args = argparser.parse_args()

    # Feeds are in the form of:
    # [location, feed url, alert timestamp]
    options = parse_config(args.config)

    # Setup locale
    try:
        locale.setlocale(locale.LC_TIME, "sl_SI.utf8")
        locale_set = True
    except locale.Error:
        try:
            locale.setlocale(locale.LC_TIME, "sl_SI")  # osx
            locale_set = True
        except locale.Error as e:
            logger.exception(e)

    # Setup twitter
    auth = tweepy.OAuthHandler(options['twitter']['consumer_key'], options['twitter']['consumer_secret'])
    auth.set_access_token(options['twitter']['access_token'], options['twitter']['access_token_secret'])

    try:
        twitter_api = tweepy.API(auth_handler=auth)
        if not twitter_api.verify_credentials():
            logger.error('Twitter authentication failed')
        else:
            twitter_verified = True
    except tweepy.TweepError as e:
        logger.exception(e)

    # Delay till full ten minutes
    now = datetime.datetime.now()
    delta = now + datetime.timedelta(minutes=10)
    delta = delta.replace(minute=int(math.floor(delta.minute / 10)) * 10).replace(second=0).replace(microsecond=0)
    time.sleep((delta - now).seconds + 1)

    logger.info('Start processing feeds')

    while True:
        try:
            if locale_set:
                process_feeds(twitter_api, twitter_verified, options['feeds'])
        except Exception as e:
            logger.exception(e)

        time.sleep(PERIOD)

if __name__ == '__main__':
    main()
