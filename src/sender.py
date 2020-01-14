import logging
import sys
import time

import telegram as t
from telegram.ext import messagequeue as mq
from telegram.utils.request import Request

logging.basicConfig(stream=sys.stdout,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

import os


class MQBot(t.Bot):
    """A subclass of Bot which delegates send method handling to Message Queue"""

    def __init__(self, *args, is_queued_def=True, mqueue=None, **kwargs):
        super(MQBot, self).__init__(*args, **kwargs)
        # below 2 attributes should be provided for decorator usage
        self._is_messages_queued_default = is_queued_def
        self._msg_queue = mqueue or mq.MessageQueue()

    def __del__(self):
        try:
            self._msg_queue.stop()
        except:
            pass

    @mq.queuedmessage
    def send_message(self, *args, **kwargs):
        """
        Wrapped method would accept new `queued` and `isgroup`
        OPTIONAL arguments
        """
        return super(MQBot, self).send_message(*args, **kwargs)


def send_stuff(bot, contact_chat_id):
    for i in range(1000):
        promise = bot.send_message(contact_chat_id, f'message: {i + 1}')

        # check if message was sent successfully.
        # access result of the promise. it will raise exception in case exception occurred in MessageQueue.
        # the check `promise.exception is not None` does not work as expected, so use this way
        try:
            result = promise.result()
        except t.error.RetryAfter as rae:
            logger.exception(rae)
            time.sleep(300)
        except t.error.Unauthorized as ue:
            logger.exception(ue)
            break
            # user blocked the bot
        except t.error.BadRequest as bre:
            logger.exception(bre)
            if bre.message == 'Chat not found':
                # wrong chat it
                print('will remove chat id')
        except Exception as e:
            logger.error(e)


def main():
    token = os.environ.get('BOT_TOKEN_TEST')
    contact_chat_id = os.environ.get('CONTACT_CHAT_ID')
    photos_file_ids_fp = 'photo_file_ids_test.json'

    request = Request(con_pool_size=8, read_timeout=180)
    message_queue = mq.MessageQueue(all_burst_limit=20, all_time_limit_ms=10_000)
    bot = MQBot(token, request=request, mqueue=message_queue)

    send_stuff(bot, contact_chat_id)

    # stop the message queue
    message_queue.stop()


if __name__ == '__main__':
    main()
