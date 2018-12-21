import difflib
import feedparser
import hashlib
import socket
import time

from feedr.dbmanager import DatabaseManager
from feedr.tweetupdate import TweetUpdate


class MonitorFeedUpdate(object):

    '''
    This class is used to monitor the RSS feed for a new update.
    It interacts with the DatabaseManager and TweetUpdate classes, to check if
    the update has already been posted or if it must be posted and logged in
    the database.
    '''

    def __init__(self, feed_name, feed_parse_timeout, feed_url,
                 sqlite_db, feed_dbtable,
                 oauth_key, oauth_secret, consumer_key, consumer_secret):
        '''
        * Parses the RSS feed with feedparser.
        * Initializes a DatabaseManager object.
        * Initializes a TweetUpdate object.
        '''

        # RSS feed
        self.feed_name = feed_name
        socket.setdefaulttimeout(feed_parse_timeout)
        self.feed = feedparser.parse(feed_url)
        self.latest_entry = None
        self.feed_subscribed_users = None

        # DatabaseManager object
        self.dbmanager = DatabaseManager(sqlite_db, feed_dbtable)

        # TweetUpdate object
        self.tweetupdate = TweetUpdate(oauth_key, oauth_secret, consumer_key,
                                       consumer_secret)

    def get_latest_entry_date(self):
        for key in ('published', 'updated'):
            if key in self.latest_entry:
                return self.latest_entry[key]
        else:
            return ''

    def monitor(self):
        '''
        Monitors the RSS feed for a new update.
        This calls the DatabaseManager object's check_for_existing_update
        method.
         * New update: checks if it is a duplicate with is_duplicate_update,
           removes the last tweet and DB entry if it is. In all cases, the
           tweet_latest_update method is called. Logs.
         * No new update: does nothing, logs.
        '''

        self.feed_subscribed_users = self.dbmanager.get_feed_subscribed_users()

        for entry in reversed(self.feed.entries):
            # use reverse for iterating from oldest to latest feed
            self.latest_entry = entry
            unchecked_hash = (self.rss_latest_sha256(),)
            check = self.dbmanager.check_for_existing_update(unchecked_hash)
            localtime_log = time.strftime(
                "%d %b %Y - %H:%M:%S", time.localtime())

            if check:
                # FIXME: Use logging module
                pass
            else:
                # See https://github.com/iceTwy/py-feedr/issues/4
                if self.is_duplicate_update():
                    self.tweetupdate.delete_last_tweet()
                    entry_table_hash = self.dbmanager.get_last_table_entry[1]
                    self.dbmanager.del_last_table_entry()
                    print(
                        '[{0}] - {1} - Duplicate update in the feed.\n'
                        '[{0}] - {1} - Deleted entry {} from the table, '
                        ' and its associated tweet\n'.format(
                            self.feed_name,
                            localtime_log,
                            entry_table_hash))

                try:
                    self.tweetupdate.tweet_latest_update(self.latest_entry)
                    self.tweetupdate.reset_msg()
                    self.send_dm_to_feed_subscribed_users()
                except Exception as e:
                    print('Error while sending tweet: {}'.format(e))
                else:
                    print('[{0}] - {1} - New update posted: {2}\n'
                          '[{0}] - {1} - Update title: {3}\n'
                          '[{0}] - {1} - Published: {4}\n'.format(
                              self.feed_name, localtime_log,
                              self.rss_latest_sha256()[:10],
                              self.latest_entry['title'],
                              self.get_latest_entry_date(),
                          ))
                finally:
                    self.dbmanager.create_latest_rss_entry(
                        self.latest_rss_entry_to_db()
                    )
                    print("Entry updated into database.")

    def is_duplicate_update(self):
        '''
        Checks if an update is a duplicate of the previous one in the feed
        by using fuzzy-string matching on the title or checking if the old
        update's title is contained in the new one.
        '''

        cur_title = self.latest_entry['title']
        last_table_entry = self.dbmanager.get_last_table_entry()
        if not last_table_entry:  # empty table
            return False
        else:
            prev_title = last_table_entry[3]

        if prev_title in cur_title:
            return True

        delta = difflib.SequenceMatcher(None, cur_title, prev_title)
        if delta.ratio() >= 0.75:
            return True

        return False

    def rss_latest_sha256(self):
        '''
        Creates an unique SHA-256 hash from the latest RSS feed element using
        the publication date, the title and the URL of the element.

        Returns the hex digest of the SHA-256 hash.
        '''
        genhash = hashlib.sha256()

        genhash.update(
            (self.get_latest_entry_date() +
             self.latest_entry['title'] +
             self.latest_entry['link'])
            .encode('utf-8')
        )
        return genhash.hexdigest()

    def latest_rss_entry_to_db(self):
        '''
        Formats the latest RSS feed element to a valid table entry in the
        database using the following structure:
            (sha256_hash text, date text, title text, url text)
        '''
        update = (self.rss_latest_sha256(),
                  self.get_latest_entry_date(),
                  self.latest_entry['title'],
                  self.latest_entry['link'])

        return update

    def send_dm_to_feed_subscribed_users(self):
        msg = "{}\n{}".format(
            self.latest_entry['title'],
            self.latest_entry['link'],
        )
        for user in self.feed_subscribed_users:
            print('Prepare to send dm to {}'.format(user))
            self.tweetupdate.send_dm(user, msg)
            print('sent dm to {}:\n{}'.format(user, msg))
