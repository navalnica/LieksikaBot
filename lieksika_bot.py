import datetime
import json
import logging
import os
import traceback
from functools import wraps

import numpy as np
import requests
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, User,
                      ParseMode)
from telegram.ext import (Updater, CallbackContext, CommandHandler, ConversationHandler, MessageHandler, Filters,
                          CallbackQueryHandler)

# *************** global variables ***************

# TODO: reformat as separate class with attributes

# conversation states
CONV_STATE_FB_RECEIVING, CONV_STATE_FB_VERIFICATION = range(2)
CONV_STATE_GET_WORD_RECEIVED = 2

# inline keyboard callback data
CB_DATA_GET_WORD_RESEND_CURRENT, CB_DATA_GET_WORD_SEND_NEXT = map(str, range(2))
CB_DATA_FB_VERIFY, CB_DATA_FB_REJECT = map(str, range(2, 4))

conversation_context = dict()

K_GET_WORD_LAST_MESSAGE_ID = 'last_photo_message_id'
K_FB_MESSAGE_ID = 'feedback_message_id'
K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID = 'feedback_message_with_inline_keyboard'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

# photos_file_ids_fn = 'photo_file_ids.json'
photos_file_ids_fn = 'photo_file_ids_test.json'
with open(photos_file_ids_fn) as fin:
    photo_file_ids = json.load(fin)
    photo_file_ids = list(photo_file_ids.items())

contact_chat_id = os.environ.get('CONTACT_CHAT_ID')
if not contact_chat_id:
    raise EnvironmentError('CONTACT_CHAT_ID variable not found in environment')


# *************** end of global variables ***************

def error_handler(update: Update, context: CallbackContext):
    logger.error(f'Update:\n{update}')
    logger.exception(context.error)

    # send detailed report to developer
    traceback_str = ''.join(traceback.format_tb(context.error.__traceback__))
    user_info_str = get_user_info_str(update.effective_user)
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
        context.bot.send_document(contact_chat_id, document=fin, caption=message, parse_mode=ParseMode.MARKDOWN)


def get_user_info_str(user: User):
    info = (f'id: {user.id}\n'
            f'full name: {user.full_name}\n'
            f'language code: {user.language_code}')
    if user.username is not None:
        info += f'\nlink: @{user.username}'
    return info


def reject_edit_update(func):
    """
    Reject updates that contain information about edited message.
    `message` field of such updates is None
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        update = args[0] if len(args) > 0 else kwargs['update']
        if update.message is None:
            logger.info(f'{func.__name__}: ignoring edit update')
            return
        return func(*args, **kwargs)

    return wrapper


@reject_edit_update
def about(update: Update, context):
    bot_description = ('Прывітанне!\nLieksika Bot ведае больш за 300 цікавых і адметных беларускіх словаў. '
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
def start(update: Update, context: CallbackContext):
    about(update, context)
    help(update, context)

    user_info_str = get_user_info_str(update.effective_user)
    description = f'#new_user\n\n{user_info_str}'
    context.bot.send_message(contact_chat_id, description)


@reject_edit_update
def dad_joke(update, context):
    url = "https://icanhazdadjoke.com/"
    headers = {'Accept': 'application/json'}
    r = requests.request("GET", url, headers=headers)
    joke = r.json()['joke']
    update.message.reply_text(joke)


@reject_edit_update
def help(update: Update, context: CallbackContext):
    msg = (f'Бот умее адказваць на наступныя каманды:\n\n'
           f'/get: атрымаць выпадковае слова\n'
           f'/about: падрабязнае апісанне боту\n'
           f'/feedback: напісаць распрацоўшчыку\n'
           f'/help: паказаць спіс даступных камандаў\n'
           f'/joke: атрымаць жарт :)'
           )
    update.message.reply_text(msg)


@reject_edit_update
def unknown_command(update: Update, context: CallbackContext):
    chat_id = update.effective_user.id
    text = update.effective_message.text
    logger.info(f'unrecognized command: {text}')
    context.bot.send_message(chat_id, f'Выбачайце, каманда не пазнаная: {text}')
    help(update, context)


# ********** feedback conversation methods **********

@reject_edit_update
def feedback_start(update, context):
    chat_id = update.effective_user.id

    if chat_id not in conversation_context:
        conversation_context[chat_id] = dict()
    feedback_cleanup(chat_id, context.bot)

    update.message.reply_text(f'Калі ласка, апішыце праблему ці сваю параду. Вы можаце далучыць фота, дакумент, '
                              f'даслаць стыкер - я падтрымліваю ўсе фарматы.\n'
                              f'Паведамленне будзе перасланае распрацоўшчыку.\n\n'
                              f'Каб перарваць размову, скарыстайце любую іншую каманду,\nнапрыклад /get.')

    return CONV_STATE_FB_RECEIVING


@reject_edit_update
def feedback_received(update, context: CallbackContext):
    chat_id = update.effective_user.id

    conversation_context[chat_id][K_FB_MESSAGE_ID] = update.message.message_id
    reply_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton('Так', callback_data=CB_DATA_FB_VERIFY),
        InlineKeyboardButton('Не', callback_data=CB_DATA_FB_REJECT)
    ]])
    res = update.message.reply_text(
        f'Вы хочаце даслаць гэтае паведамленне? (тэкст у паведамленні на гэтым кроку ўсё яшчэ можна рэдагаваць)',
        reply_markup=reply_markup,
        reply_to_message_id=conversation_context[chat_id][K_FB_MESSAGE_ID]
    )
    conversation_context[chat_id][K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID] = res.message_id

    return CONV_STATE_FB_VERIFICATION


def feedback_cleanup(chat_id, bot):
    if K_FB_MESSAGE_ID in conversation_context[chat_id]:
        del conversation_context[chat_id][K_FB_MESSAGE_ID]
    if K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID in conversation_context[chat_id]:
        bot.edit_message_reply_markup(
            chat_id,
            conversation_context[chat_id][K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID],
            reply_markup=None
        )
        del conversation_context[chat_id][K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID]


def feedback_verified(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = update.effective_user.id

    user_info_str = get_user_info_str(update.effective_user)
    context.bot.send_message(contact_chat_id, f'#feedback\n\nuser:\n{user_info_str}')
    context.bot.forward_message(
        chat_id=contact_chat_id,
        from_chat_id=chat_id,
        message_id=conversation_context[chat_id][K_FB_MESSAGE_ID])

    context.bot.send_message(chat_id, 'Вашае паведамленне (яно прыведзенае ніжэй) дасланае распрацоўшчыку.\n'
                                      'Вялікі дзякуй!')
    context.bot.forward_message(
        chat_id=chat_id,
        from_chat_id=chat_id,
        message_id=conversation_context[chat_id][K_FB_MESSAGE_ID])

    context.bot.answer_callback_query(callback_query_id=query.id)
    feedback_cleanup(chat_id, context.bot)

    return ConversationHandler.END


def feedback_canceled(update: Update, context):
    chat_id = update.effective_user.id
    logger.info(f'feedback conversation canceled. user_id: {chat_id}')
    # some calls are from inline keyboard
    if update.callback_query is not None:
        context.bot.answer_callback_query(callback_query_id=update.callback_query.id)
    feedback_cleanup(chat_id, context.bot)
    context.bot.send_message(chat_id, 'Размова перарваная')

    return ConversationHandler.END


def feedback_timeout(bot, update):
    chat_id = update.effective_user.id
    logger.info(f'conversation timeout. chat_id: {chat_id}')
    bot.send_message(
        chat_id,
        f'Размова перарваная: перавышаны час чакання адказу. Паспрабуйце яшчэ раз.',
        reply_markup=None)
    feedback_cleanup(chat_id, bot)


@reject_edit_update
def feedback_input_not_recognized(update, context):
    chat_id = update.effective_user.id
    context.bot.edit_message_reply_markup(
        chat_id,
        conversation_context[chat_id][K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID],
        reply_markup=None
    )
    reply_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton('Так', callback_data=CB_DATA_FB_VERIFY),
        InlineKeyboardButton('Не', callback_data=CB_DATA_FB_REJECT)
    ]])
    res = update.message.reply_text(
        f'Вы хочаце даслаць гэтае паведамленне? (тэкст у паведамленні на гэтым кроку ўсё яшчэ можна рэдагаваць)',
        reply_markup=reply_markup,
        reply_to_message_id=conversation_context[chat_id][K_FB_MESSAGE_ID]
    )
    conversation_context[chat_id][K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID] = res.message_id


# ********** end of feedback conversation methods **********


def ignore_update(update, context):
    pass


# ********** get word conversation methods **********

def get_random_photo_object():
    ix = np.random.randint(0, len(photo_file_ids))
    photo = photo_file_ids[ix][1]
    return photo


def _send_photo(bot, chat_id, photo):
    buttons = [
        [InlineKeyboardButton(text='Змяніць бягучае', callback_data=CB_DATA_GET_WORD_RESEND_CURRENT)],
        [InlineKeyboardButton(text='Даслаць наступнае', callback_data=CB_DATA_GET_WORD_SEND_NEXT)]
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    res = bot.send_photo(
        chat_id=chat_id,
        photo=photo,
        reply_markup=keyboard
    )
    conversation_context[chat_id][K_GET_WORD_LAST_MESSAGE_ID] = res.message_id


@reject_edit_update
def get(update: Update, context: CallbackContext):
    chat_id = update.effective_user.id

    if chat_id not in conversation_context:
        conversation_context[chat_id] = dict()
    get_word_cleanup(chat_id, context.bot)

    photo = get_random_photo_object()
    logger.info(f'get. chat_id: {chat_id}, file_id: {photo}')
    _send_photo(context.bot, chat_id, photo)

    return CONV_STATE_GET_WORD_RECEIVED


def get_word_resend_current(update: Update, context):
    query = update.callback_query
    chat_id = query.from_user.id

    photo = get_random_photo_object()

    buttons = [
        [InlineKeyboardButton(text='Змяніць бягучае', callback_data=CB_DATA_GET_WORD_RESEND_CURRENT)],
        [InlineKeyboardButton(text='Даслаць наступнае', callback_data=CB_DATA_GET_WORD_SEND_NEXT)]
    ]
    keyboard = InlineKeyboardMarkup(buttons)

    context.bot.edit_message_media(
        chat_id=chat_id,
        message_id=query.message.message_id,
        media=InputMediaPhoto(media=photo),
        reply_markup=keyboard
    )
    context.bot.answer_callback_query(callback_query_id=query.id)


def get_word_cleanup(chat_id, bot):
    if K_GET_WORD_LAST_MESSAGE_ID in conversation_context[chat_id]:
        bot.edit_message_reply_markup(
            chat_id,
            conversation_context[chat_id][K_GET_WORD_LAST_MESSAGE_ID],
            reply_markup=None
        )
        del conversation_context[chat_id][K_GET_WORD_LAST_MESSAGE_ID]


def get_word_send_next(update, context):
    query = update.callback_query
    chat_id = query.from_user.id

    photo = get_random_photo_object()
    get_word_cleanup(chat_id, context.bot)
    _send_photo(context.bot, query.from_user.id, photo)
    context.bot.answer_callback_query(callback_query_id=query.id)


def get_word_timeout(bot, update):
    chat_id = update.effective_user.id
    get_word_cleanup(chat_id, bot)
    logger.info(f'get_word conversation timeout. chat_id: {chat_id}')


def get_word_canceled(update, context):
    chat_id = update.effective_user.id
    logger.info(f'get_word conversation canceled. user_id: {chat_id}')
    get_word_cleanup(chat_id, context.bot)

    return ConversationHandler.END


# ********** end of get word conversation methods **********


def main():
    # token = os.environ.get('BOT_TOKEN')
    token = os.environ.get('BOT_TOKEN_TEST')
    if not token:
        raise EnvironmentError('BOT_TOKEN variable not found in environment')

    mode = os.environ.get('MODE')
    if not mode or mode not in ['heroku', 'local']:
        raise EnvironmentError('MODE (heroku|local) variable not found in environment')
    logger.info(f'running in {mode} mode')

    port = os.environ.get('PORT')
    heroku_app_name = os.environ.get('APP_NAME')
    if mode == 'heroku':
        if port is None:
            raise EnvironmentError('PORT variable not found in environment')
        else:
            port = int(port)
        if heroku_app_name is None:
            raise EnvironmentError('APP_NAME variable not found in environment')

    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    conversation_feedback = ConversationHandler(
        entry_points=[CommandHandler('feedback', feedback_start)],
        states={
            CONV_STATE_FB_RECEIVING: [
                MessageHandler(Filters.command, feedback_canceled),
                MessageHandler(Filters.all, feedback_received)
            ],
            CONV_STATE_FB_VERIFICATION: [
                CallbackQueryHandler(feedback_verified, pattern=f'^{CB_DATA_FB_VERIFY}$'),
                CallbackQueryHandler(feedback_canceled, pattern=f'^{CB_DATA_FB_REJECT}$'),
            ],
            ConversationHandler.TIMEOUT: [MessageHandler(Filters.all, feedback_timeout)]
        },
        fallbacks=[
            MessageHandler(Filters.command, feedback_canceled),
            MessageHandler(Filters.all, feedback_input_not_recognized)
        ],
        allow_reentry=True,
        conversation_timeout=20 * 60
    )

    conversation_get_word = ConversationHandler(
        entry_points=[CommandHandler('get', get)],
        states={
            CONV_STATE_GET_WORD_RECEIVED: [
                CallbackQueryHandler(get_word_resend_current, pattern=f'^{CB_DATA_GET_WORD_RESEND_CURRENT}$'),
                CallbackQueryHandler(get_word_send_next, pattern=f'^{CB_DATA_GET_WORD_SEND_NEXT}$')
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(Filters.all, get_word_timeout),
                CallbackQueryHandler(get_word_timeout)
            ]
        },
        fallbacks=[MessageHandler(Filters.command, get_word_canceled)],
        allow_reentry=True,
        conversation_timeout=20 * 60
    )

    dp.add_handler(CommandHandler('start', start), group=1)
    dp.add_handler(CommandHandler('about', about), group=1)
    dp.add_handler(CommandHandler('help', help), group=1)
    dp.add_handler(CommandHandler('joke', dad_joke), group=1)

    # ignore to avoid handling update two times
    # because /get is the entry point of conversation in another group
    dp.add_handler(CommandHandler('get', ignore_update), group=1)
    dp.add_handler(CommandHandler('feedback', ignore_update), group=1)

    dp.add_handler(MessageHandler(Filters.command, unknown_command), group=1)

    dp.add_handler(conversation_feedback, group=2)

    dp.add_handler(conversation_get_word, group=3)

    dp.add_error_handler(error_handler)

    if mode == 'heroku':
        updater.start_webhook(listen="0.0.0.0", port=port, url_path=token)
        updater.bot.setWebhook(f'https://{heroku_app_name}.herokuapp.com/{token}')
    elif mode == 'local':
        dp.bot.delete_webhook()
        updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
