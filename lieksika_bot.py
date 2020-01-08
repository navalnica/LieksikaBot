import datetime
import json
import logging
import traceback
from functools import wraps
from signal import SIGINT

import numpy as np
import requests
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, User,
                      ParseMode)
from telegram.error import BadRequest
from telegram.ext import (Updater, CallbackContext, CommandHandler, ConversationHandler, MessageHandler, Filters,
                          CallbackQueryHandler)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


# -------------- decorators --------------

def reject_edit_update(func):
    """
    Reject updates that contain information about edited message.
    `message` field of such updates is None
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        update = args[1] if len(args) > 1 else kwargs['update']
        chat_id = update.effective_user.id
        if update.message is None:
            logger.info(f'{func.__name__}. ignoring edit update. chat_id: {chat_id}')
            return
        return func(*args, **kwargs)

    return wrapper


def log_method_name_and_chat_id_from_update(_method=None, *, update_pos_arg_ix=0):
    """
    Log method call into `info` stream.
    This decorator can be invoked bot without parentheses and with argument `update_pos_arg_ix` provided
    :param _method: parameter to check how the decorator is used
    :param update_pos_arg_ix: index of `update` in positional arguments
    """

    def outer_wrapper(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            effective_update_ix = update_pos_arg_ix + 1  # take `self` argument into account
            update = args[effective_update_ix] if len(args) > effective_update_ix else kwargs['update']
            chat_id = update.effective_user.id
            logger.info(f'{func.__name__}. chat_id: {chat_id}')
            return func(*args, **kwargs)

        return wrapper

    if _method is None:
        # decorator is called with parameter `update_pos_arg_ix`
        return outer_wrapper
    else:
        # decorator is called without parentheses
        return outer_wrapper(_method)


class LieksikaBot:

    def __init__(self, token, contact_chat_id, mode, photos_file_ids_fp):
        self.token = token
        self.contact_chat_id = contact_chat_id
        self.photos_file_ids_fp = photos_file_ids_fp

        self.mode = 'local'
        self.heroku_app_name = None
        self.heroku_port = None
        self.prev_webhook_info = None

        self.conversation_context = dict()

        self.updater = Updater(token, use_context=True, user_sig_handler=self.try_to_restore_webhook)
        self.dp = self.updater.dispatcher

        # conversation states
        self.CONV_STATE_FB_RECEIVING, self.CONV_STATE_FB_VERIFICATION = range(2)
        self.CONV_STATE_GET_WORD_RECEIVED = 2

        # inline keyboard callback data
        self.CB_DATA_GET_WORD_RESEND_CURRENT, self.CB_DATA_GET_WORD_SEND_NEXT = map(str, range(2))
        self.CB_DATA_FB_VERIFY, self.CB_DATA_FB_REJECT = map(str, range(2, 4))

        self.K_GET_WORD_LAST_MESSAGE_ID = 'last_photo_message_id'
        self.K_FB_MESSAGE_ID = 'feedback_message_id'
        self.K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID = 'feedback_message_with_inline_keyboard'

        with open(self.photos_file_ids_fp) as fin:
            photo_file_ids = json.load(fin)
            self.photos_file_ids = tuple(photo_file_ids.items())

        self.init_handlers()

    def set_heroku_mode(self, heroku_app_name, heroku_port):
        self.mode = 'heroku'
        self.heroku_app_name = heroku_app_name
        self.heroku_port = heroku_port

    def init_handlers(self):
        conversation_feedback = ConversationHandler(
            entry_points=[CommandHandler('feedback', self.feedback_start)],
            states={
                self.CONV_STATE_FB_RECEIVING: [
                    MessageHandler(Filters.command, self.feedback_canceled),
                    MessageHandler(Filters.all, self.feedback_received)
                ],
                self.CONV_STATE_FB_VERIFICATION: [
                    CallbackQueryHandler(self.feedback_verified, pattern=f'^{self.CB_DATA_FB_VERIFY}$'),
                    CallbackQueryHandler(self.feedback_canceled, pattern=f'^{self.CB_DATA_FB_REJECT}$'),
                ],
                ConversationHandler.TIMEOUT: [MessageHandler(Filters.all, self.feedback_timeout)]
            },
            fallbacks=[
                MessageHandler(Filters.command, self.feedback_canceled),
                MessageHandler(Filters.all, self.feedback_input_not_recognized)
            ],
            allow_reentry=True,
            conversation_timeout=20 * 60
        )

        conversation_get_word = ConversationHandler(
            entry_points=[CommandHandler('get', self.get)],
            states={
                self.CONV_STATE_GET_WORD_RECEIVED: [
                    CallbackQueryHandler(self.get_word_resend_current,
                                         pattern=f'^{self.CB_DATA_GET_WORD_RESEND_CURRENT}$'),
                    CallbackQueryHandler(self.get_word_send_next, pattern=f'^{self.CB_DATA_GET_WORD_SEND_NEXT}$')
                ],
                ConversationHandler.TIMEOUT: [
                    MessageHandler(Filters.all, self.get_word_timeout),
                    CallbackQueryHandler(self.get_word_timeout)
                ]
            },
            fallbacks=[MessageHandler(Filters.command, self.get_word_canceled)],
            allow_reentry=True,
            conversation_timeout=20 * 60
        )

        self.dp.add_handler(CommandHandler('start', self.start), group=1)
        self.dp.add_handler(CommandHandler('about', self.about), group=1)
        self.dp.add_handler(CommandHandler('help', self.help), group=1)
        self.dp.add_handler(CommandHandler('joke', self.dad_joke), group=1)
        # ignore commands to avoid handling updates multiple times in different groups
        self.dp.add_handler(CommandHandler('get', self.ignore_update), group=1)
        self.dp.add_handler(CommandHandler('feedback', self.ignore_update), group=1)
        self.dp.add_handler(MessageHandler(Filters.command, self.unknown_command), group=1)

        self.dp.add_handler(conversation_feedback, group=2)

        self.dp.add_handler(conversation_get_word, group=3)

        self.dp.add_error_handler(self.error_handler)

    def run(self):
        logger.info(f'\n*****************************************\n'
                    f'running LieksikaBot with next parameters:\n\n'
                    f'photos_file_ids_fp: "{self.photos_file_ids_fp}"\n'
                    f'mode: "{self.mode}"\n'
                    f'heroku_app_name: "{self.heroku_app_name}"\n'
                    f'heroku_port: "{self.heroku_port}"\n'
                    f'*****************************************\n')

        if self.mode == 'heroku':
            self.updater.start_webhook(listen="0.0.0.0", port=self.heroku_port, url_path=self.token)
            self.updater.bot.setWebhook(f'https://{self.heroku_app_name}.herokuapp.com/{self.token}')
        elif self.mode == 'local':
            self.prev_webhook_info = self.dp.bot.get_webhook_info()
            self.dp.bot.delete_webhook()
            self.updater.start_polling()
        self.updater.idle()

    def try_to_restore_webhook(self, signal, frame):
        if signal == SIGINT:
            to_try = bool(self.prev_webhook_info.url)
            logger.info(f'handling SIGINT signal. previous webhook url string is not empty: {to_try}')
            if to_try:
                self.dp.bot.set_webhook(self.prev_webhook_info.url)
                logger.info(f'have reset webhook url to previous value')

    def error_handler(self, update: Update, context: CallbackContext):
        logger.error(f'Update:\n{update}')
        logger.exception(context.error)

        # send detailed report to developer
        traceback_str = ''.join(traceback.format_tb(context.error.__traceback__))
        user_info_str = self.get_user_info_str(update.effective_user)
        # convert TelegramObject to json, load it to dict
        # and then dump back to json with pretty indents
        update_json = json.dumps(json.loads(update.to_json()), indent=2)
        message = (f'#error\n\n'
                   f'user:\n{user_info_str}\n\n'
                   f'error:\n`{context.error}`\n\n')
        error_fn = f'error_{datetime.datetime.now().strftime("%Y-%m-%d_%H-%M")}.txt'
        with open(error_fn, 'w') as fout:
            fout.write(f'user:\n{user_info_str}\n\n')
            fout.write(f'error:\n{context.error}\n\n')
            fout.write(f'traceback:\n{traceback_str}\n\n')
            fout.write(f'update:\n{update_json}')
        with open(error_fn, 'rb') as fin:
            context.bot.send_document(self.contact_chat_id, document=fin, caption=message,
                                      parse_mode=ParseMode.MARKDOWN)

    @staticmethod
    def get_user_info_str(user: User):
        info = (f'id: {user.id}\n'
                f'full name: {user.full_name}\n'
                f'language code: {user.language_code}')
        if user.username is not None:
            info += f'\nlink: @{user.username}'
        return info

    @reject_edit_update
    @log_method_name_and_chat_id_from_update
    def start(self, update: Update, context: CallbackContext):
        update.message.reply_text(f'Добры дзень!\n'
                                  f'Рады, што вы вырашылі паспрабаваць Lieksika Bot.\n'
                                  f'Ніжэй будуць дасланыя паведамленні з апісаннем боту і '
                                  f'інструкцыямі па яго карыстанні. Паўторна атрымаць іх вы '
                                  f'можаце ў любы момант з дапамогай камандаў\n'
                                  f'/about ды /help')
        self.about(update, context)
        self.help(update, context)

        # store id of the new user to send scheduled messages
        user_info_str = self.get_user_info_str(update.effective_user)
        description = f'#new_user\n\n{user_info_str}'
        context.bot.send_message(self.contact_chat_id, description)

    @reject_edit_update
    @log_method_name_and_chat_id_from_update
    def about(self, update: Update, context):
        bot_description = (
            'Прывітанне!\nLieksika Bot ведае больш за 300 цікавых і адметных беларускіх словаў. '
            'І іх спіс будзе пашырацца!\n\n'
            'Словы захоўваюцца ў выглядзе скрыншотаў з рэсурсаў slounik.org, skarnik.by.\n'
            'Вялікі дзякуй іх распрацоўшчыкам за праведзеную працу па сістэматызацыі і стварэнні '
            'сайтаў і мабільнага дадатку. На жаль, іх інтэрфэйсы не маюць магчымасці ствараць падборкі '
            'словаў, дасылаць напаміны для паўтарэння вывучаных словаў. '
            'З мэтай скласці базу цікавых і не пашыраных у штодзённым '
            'жыцці словаў, аўтаматызаваць іх паўтарэнне і быў створаны гэты бот.\n\n'
            'У будучыні плануецца дадаць магчымасць рэгулярнай рассылкі словаў: '
            'штодня вы зможаце атрымліваць падборку новай цікавай лексікі.\n\n'
            'Каб бот даслаў вам выпадковае слова, карыстайце каманду /get.\n'
            'З дапамогай клавішаў пад атрыманым паведамленнем вы можаце альбо загадаць боту змяніць апошняе '
            'слова, калі ўжо ведаеце яго, альбо захаваць паведамленне і перайсці да наступнага слова.\n\n'
            'Каб даслаць распрацоўшчыку сваю параду альбо інфармацыю пра памылку, '
            'карыстайце каманду /feedback.\n\n'
            'Прыемнага паглыблення ў свет беларускай мовы!\n\n'
            '!! Калі вы хочаце дапамагчы ў распрацоўцы slounik.org, skarnik.by ці іншых беларускіх '
            'электронных рэсурсаў, прысвечаных мове, абавязкова напішыце распрацоўшчыку праз '
            'каманду \n/feedback !!')
        update.message.reply_text(bot_description)

    @reject_edit_update
    @log_method_name_and_chat_id_from_update
    def help(self, update: Update, context: CallbackContext):
        msg = (f'Бот умее адказваць на наступныя каманды:\n\n'
               f'/get: атрымаць выпадковае слова\n'
               f'/about: падрабязнае апісанне боту\n'
               f'/feedback: напісаць распрацоўшчыку\n'
               f'/help: паказаць спіс даступных камандаў\n'
               f'/joke: атрымаць жарт :)'
               )
        update.message.reply_text(msg)

    @reject_edit_update
    @log_method_name_and_chat_id_from_update
    def dad_joke(self, update, context):
        url = "https://icanhazdadjoke.com/"
        headers = {'Accept': 'application/json'}
        try:
            r = requests.request("GET", url, headers=headers)
            joke = r.json()['joke']
            update.message.reply_text(joke)
        except Exception as e:
            update.message.reply_text('Выбачайце! Праблемы з падлучэннем да серверу з жартамі)')
            logger.exception(e)

    @reject_edit_update
    def unknown_command(self, update: Update, context: CallbackContext):
        chat_id = update.effective_user.id
        text = update.effective_message.text
        logger.info(f'unknown_command. chat_id: {chat_id}, text: "{text}"')
        context.bot.send_message(chat_id, f'Выбачайце, каманда не пазнаная: {text}')
        self.help(update, context)

    # -------------- feedback conversation methods --------------

    @reject_edit_update
    @log_method_name_and_chat_id_from_update
    def feedback_start(self, update, context):
        chat_id = update.effective_user.id

        if chat_id not in self.conversation_context:
            self.conversation_context[chat_id] = dict()
        self.feedback_cleanup(chat_id, context.bot)

        update.message.reply_text(
            f'Калі ласка, апішыце сваю праблему ці параду. Вы можаце далучыць фота, дакумент, '
            f'даслаць стыкер - бот падтрымлівае ўсе фарматы.\n'
            f'Паведамленне будзе перасланае распрацоўшчыку.\n\n'
            f'Каб перарваць размову, скарыстайце любую іншую каманду,\nнапрыклад /get.')

        return self.CONV_STATE_FB_RECEIVING

    @reject_edit_update
    @log_method_name_and_chat_id_from_update
    def feedback_received(self, update, context: CallbackContext):
        chat_id = update.effective_user.id

        self.conversation_context[chat_id][self.K_FB_MESSAGE_ID] = update.message.message_id
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton('Так', callback_data=self.CB_DATA_FB_VERIFY),
            InlineKeyboardButton('Не', callback_data=self.CB_DATA_FB_REJECT)
        ]])
        res = update.message.reply_text(
            f'Вы хочаце даслаць гэтае паведамленне? (тэкст у паведамленні на гэтым кроку ўсё яшчэ можна рэдагаваць)',
            reply_markup=reply_markup,
            reply_to_message_id=self.conversation_context[chat_id][self.K_FB_MESSAGE_ID]
        )
        self.conversation_context[chat_id][self.K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID] = res.message_id

        return self.CONV_STATE_FB_VERIFICATION

    def feedback_cleanup(self, chat_id, bot):
        logger.info(f'feedback_cleanup. chat_id: {chat_id}')
        if self.K_FB_MESSAGE_ID in self.conversation_context[chat_id]:
            del self.conversation_context[chat_id][self.K_FB_MESSAGE_ID]
        if self.K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID in self.conversation_context[chat_id]:
            try:
                bot.edit_message_reply_markup(
                    chat_id,
                    self.conversation_context[chat_id][self.K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID],
                    reply_markup=None
                )
            except BadRequest as e:
                logger.error(e)
            finally:
                del self.conversation_context[chat_id][self.K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID]

    @log_method_name_and_chat_id_from_update
    def feedback_verified(self, update: Update, context: CallbackContext):
        query = update.callback_query
        chat_id = update.effective_user.id

        user_info_str = self.get_user_info_str(update.effective_user)
        context.bot.send_message(self.contact_chat_id, f'#feedback\n\nuser:\n{user_info_str}')
        context.bot.forward_message(
            chat_id=self.contact_chat_id,
            from_chat_id=chat_id,
            message_id=self.conversation_context[chat_id][self.K_FB_MESSAGE_ID])

        context.bot.send_message(chat_id, 'Вашае паведамленне (яно прыведзенае ніжэй) дасланае распрацоўшчыку.\n'
                                          'Вялікі дзякуй!')
        context.bot.forward_message(
            chat_id=chat_id,
            from_chat_id=chat_id,
            message_id=self.conversation_context[chat_id][self.K_FB_MESSAGE_ID])

        context.bot.answer_callback_query(callback_query_id=query.id)
        self.feedback_cleanup(chat_id, context.bot)

        return ConversationHandler.END

    @log_method_name_and_chat_id_from_update
    def feedback_canceled(self, update: Update, context):
        chat_id = update.effective_user.id
        # some calls are from inline keyboard
        if update.callback_query is not None:
            context.bot.answer_callback_query(callback_query_id=update.callback_query.id)
        self.feedback_cleanup(chat_id, context.bot)
        context.bot.send_message(chat_id, 'Размова перарваная')

        return ConversationHandler.END

    @log_method_name_and_chat_id_from_update(update_pos_arg_ix=1)
    def feedback_timeout(self, bot, update):
        chat_id = update.effective_user.id
        bot.send_message(
            chat_id,
            f'Размова перарваная: перавышаны час чакання адказу. Паспрабуйце яшчэ раз.',
            reply_markup=None)
        self.feedback_cleanup(chat_id, bot)

    @reject_edit_update
    @log_method_name_and_chat_id_from_update
    def feedback_input_not_recognized(self, update, context):
        chat_id = update.effective_user.id
        context.bot.edit_message_reply_markup(
            chat_id,
            self.conversation_context[chat_id][self.K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID],
            reply_markup=None
        )
        reply_markup = InlineKeyboardMarkup([[
            InlineKeyboardButton('Так', callback_data=self.CB_DATA_FB_VERIFY),
            InlineKeyboardButton('Не', callback_data=self.CB_DATA_FB_REJECT)
        ]])
        res = update.message.reply_text(
            f'Вы хочаце даслаць гэтае паведамленне? (тэкст у паведамленні на гэтым кроку ўсё яшчэ можна рэдагаваць)',
            reply_markup=reply_markup,
            reply_to_message_id=self.conversation_context[chat_id][self.K_FB_MESSAGE_ID]
        )
        self.conversation_context[chat_id][self.K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID] = res.message_id

    # -------------- end of feedback conversation methods --------------

    def ignore_update(self, update, context):
        pass

    # -------------- get word conversation methods --------------

    def get_random_photo_object(self, chat_id):
        ix = np.random.randint(0, len(self.photos_file_ids))
        photo = self.photos_file_ids[ix][1]
        logger.info(f'get_random_photo_object. chat_id: {chat_id}, file_id: "{photo}"')
        return photo

    def _send_photo(self, bot, chat_id, photo):
        buttons = [
            [InlineKeyboardButton(text='Змяніць бягучае', callback_data=self.CB_DATA_GET_WORD_RESEND_CURRENT)],
            [InlineKeyboardButton(text='Даслаць наступнае', callback_data=self.CB_DATA_GET_WORD_SEND_NEXT)]
        ]
        keyboard = InlineKeyboardMarkup(buttons)
        res = bot.send_photo(
            chat_id=chat_id,
            photo=photo,
            reply_markup=keyboard
        )
        self.conversation_context[chat_id][self.K_GET_WORD_LAST_MESSAGE_ID] = res.message_id

    @reject_edit_update
    @log_method_name_and_chat_id_from_update
    def get(self, update: Update, context: CallbackContext):
        chat_id = update.effective_user.id

        if chat_id not in self.conversation_context:
            self.conversation_context[chat_id] = dict()
        self.get_word_cleanup(chat_id, context.bot)

        photo = self.get_random_photo_object(chat_id)
        self._send_photo(context.bot, chat_id, photo)

        return self.CONV_STATE_GET_WORD_RECEIVED

    @log_method_name_and_chat_id_from_update
    def get_word_resend_current(self, update: Update, context):
        query = update.callback_query
        chat_id = query.from_user.id

        photo = self.get_random_photo_object(chat_id)

        buttons = [
            [InlineKeyboardButton(text='Змяніць бягучае', callback_data=self.CB_DATA_GET_WORD_RESEND_CURRENT)],
            [InlineKeyboardButton(text='Даслаць наступнае', callback_data=self.CB_DATA_GET_WORD_SEND_NEXT)]
        ]
        keyboard = InlineKeyboardMarkup(buttons)

        context.bot.edit_message_media(
            chat_id=chat_id,
            message_id=query.message.message_id,
            media=InputMediaPhoto(media=photo),
            reply_markup=keyboard
        )
        context.bot.answer_callback_query(callback_query_id=query.id)

    def get_word_cleanup(self, chat_id, bot):
        logger.info(f'get_word_cleanup. chat_id: {chat_id}')
        if self.K_GET_WORD_LAST_MESSAGE_ID in self.conversation_context[chat_id]:
            try:
                bot.edit_message_reply_markup(
                    chat_id,
                    self.conversation_context[chat_id][self.K_GET_WORD_LAST_MESSAGE_ID],
                    reply_markup=None
                )
            except BadRequest as e:
                logger.error(e)
            finally:
                del self.conversation_context[chat_id][self.K_GET_WORD_LAST_MESSAGE_ID]

    @log_method_name_and_chat_id_from_update
    def get_word_send_next(self, update, context):
        query = update.callback_query
        chat_id = query.from_user.id

        photo = self.get_random_photo_object(chat_id)
        self.get_word_cleanup(chat_id, context.bot)
        self._send_photo(context.bot, query.from_user.id, photo)
        context.bot.answer_callback_query(callback_query_id=query.id)

    @log_method_name_and_chat_id_from_update(update_pos_arg_ix=1)
    def get_word_timeout(self, bot, update):
        chat_id = update.effective_user.id
        self.get_word_cleanup(chat_id, bot)

    @log_method_name_and_chat_id_from_update
    def get_word_canceled(self, update, context):
        chat_id = update.effective_user.id
        self.get_word_cleanup(chat_id, context.bot)

        return ConversationHandler.END

    # -------------- end of get word conversation methods --------------
