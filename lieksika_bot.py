import json
import logging
import os
import traceback

import numpy as np
import requests
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto, ReplyKeyboardRemove, User,
                      ParseMode)
from telegram.ext import (Updater, CallbackContext, CommandHandler, ConversationHandler, MessageHandler, Filters,
                          CallbackQueryHandler)

# *************** global variables ***************

# TODO: reformat as separate class with attributes
# TODO: add methods decorator to remove previous inline keyboard

# conversation states
FEEDBACK_RECEIVING, FEEDBACK_VERIFICATION = range(2)

# inline keyboard callback data
RESEND_CURRENT, SEND_NEXT, FEEDBACK_VERIFY, FEEDBACK_REJECT = map(str, range(4))

conversation_context = dict()

K_LAST_PHOTO_MESSAGE_ID = 'last_photo_message_id'
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

    traceback_str = ''.join(traceback.format_tb(context.error.__traceback__))
    user_info_str = get_user_info_str(update.effective_user)
    update_json = update.to_json()
    message = (f'#error\n\n'
               f'user:\n{user_info_str}\n\n'
               f'error:\n`{context.error}`\n\n'
               f'traceback:\n`{traceback_str}`\n\n'
               f'update:\n`{update_json}`')
    context.bot.send_message(
        contact_chat_id,
        message,
        parse_mode=ParseMode.MARKDOWN
    )


def remove_inline_keyboard_from_last_photo(bot, chat_id, user_data):
    if K_LAST_PHOTO_MESSAGE_ID in user_data:
        try:
            bot.edit_message_reply_markup(chat_id, user_data[K_LAST_PHOTO_MESSAGE_ID], reply_markup=None)
        except Exception as e:
            logger.exception(e)
        finally:
            del user_data[K_LAST_PHOTO_MESSAGE_ID]


def get_user_info_str(user: User):
    info = (f'id: {user.id}\n'
            f'full name: {user.full_name}\n'
            f'language code: {user.language_code}')
    if user.username is not None:
        info += f'\nlink: @{user.username}'
    return info


def about(update, context):
    bot_description = ('Прывітанне!\nLieksika Bot ведае больш за 300 цікавых і адметных беларускіх словаў. '
                       'І іх спіс будзе пашырацца!\n\n'
                       'Яны захоўваюцца ў выглядзе скрыншотаў з рэсурсаў slounik.org, skarnik.by.\n'
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


def start(update: Update, context: CallbackContext):
    remove_inline_keyboard_from_last_photo(context.bot, update.effective_user.id, context.user_data)
    about(update, context)
    help(update, context)

    user_info_str = get_user_info_str(update.effective_user)
    description = f'#new_user\n\n{user_info_str}'
    context.bot.send_message(contact_chat_id, description)


def dad_joke(update, context):
    remove_inline_keyboard_from_last_photo(context.bot, update.effective_user.id, context.user_data)
    url = "https://icanhazdadjoke.com/"
    headers = {'Accept': 'application/json'}
    r = requests.request("GET", url, headers=headers)
    joke = r.json()['joke']
    update.message.reply_text(joke)


def help(update: Update, context: CallbackContext):
    remove_inline_keyboard_from_last_photo(context.bot, update.effective_user.id, context.user_data)
    msg = (f'Бот умее адказваць на наступныя каманды:\n\n'
           f'/get: атрымаць выпадковае слова\n'
           f'/about: падрабязнае апісанне боту\n'
           f'/feedback: напісаць распрацоўшчыку\n'
           f'/help: паказаць спіс даступных камандаў\n'
           f'/joke: атрымаць жарт :)'
           )
    update.message.reply_text(msg)


def unknown_command(update: Update, context: CallbackContext):
    remove_inline_keyboard_from_last_photo(context.bot, update.effective_user.id, context.user_data)
    logger.info(f'unrecognized command: {update.message.text}')
    update.message.reply_text(f'Выбачайце, каманда не пазнаная: {update.message.text}')
    help(update, context)


def _send_photo(bot, chat_id, photo, user_data):
    buttons = [
        [InlineKeyboardButton(text='Змяніць бягучае', callback_data=RESEND_CURRENT)],
        [InlineKeyboardButton(text='Даслаць наступнае', callback_data=SEND_NEXT)]
    ]
    keyboard = InlineKeyboardMarkup(buttons)
    res = bot.send_photo(
        chat_id=chat_id,
        photo=photo,
        reply_markup=keyboard
    )
    user_data[K_LAST_PHOTO_MESSAGE_ID] = res.message_id


def send_random_word(update: Update, context: CallbackContext):
    chat_id = update.effective_user.id
    remove_inline_keyboard_from_last_photo(context.bot, chat_id, context.user_data)
    ix = np.random.randint(0, len(photo_file_ids))
    photo = photo_file_ids[ix][1]
    logger.info(f'sending photo. chat_id: {chat_id}, file_id: {photo}')
    _send_photo(context.bot, chat_id, photo, context.user_data)


def photo_inline_keyboard_handler(update, context):
    query = update.callback_query
    chat_id = query.from_user.id
    data = query.data
    ix = np.random.randint(0, len(photo_file_ids))
    photo = photo_file_ids[ix][1]
    logger.info(f'inline_keyboard_handler. chat_id: {chat_id}, new file_id: {photo}')
    if data == RESEND_CURRENT:
        res = context.bot.edit_message_media(
            chat_id=chat_id,
            message_id=query.message.message_id,
            media=InputMediaPhoto(media=photo),
            reply_markup=query.message.reply_markup
        )
        context.bot.answer_callback_query(callback_query_id=query.id)
    elif data == SEND_NEXT:
        remove_inline_keyboard_from_last_photo(context.bot, chat_id, context.user_data)
        _send_photo(context.bot, query.from_user.id, photo, context.user_data)
        context.bot.answer_callback_query(callback_query_id=query.id)
    else:
        raise ValueError(f'could not parse data: {data}')


# ********** feedback conversation methods **********

def feedback_start(update, context):
    remove_inline_keyboard_from_last_photo(context.bot, update.effective_user.id, context.user_data)
    if update.message is None:
        return None
    update.message.reply_text(f'Калі ласка, апішыце праблему ці сваю параду. Вы можаце далучыць фота, дакумент, '
                              f'даслаць стыкер - я падтрымліваю ўсе фарматы.\n'
                              f'Паведамленне будзе перасланае распрацоўшчыку.\n\n'
                              f'Каб перарваць размову, выкарыстайце каманду /cancel')
    chat_id = update.effective_user.id
    if chat_id not in conversation_context:
        conversation_context[chat_id] = dict()
    return FEEDBACK_RECEIVING


def feedback_received(update, context: CallbackContext):
    if update.message is None:
        return None
    chat_id = update.effective_user.id
    conversation_context[chat_id][K_FB_MESSAGE_ID] = update.message.message_id
    reply_markup = InlineKeyboardMarkup([[
        InlineKeyboardButton('Так', callback_data=FEEDBACK_VERIFY),
        InlineKeyboardButton('Не', callback_data=FEEDBACK_REJECT)
    ]])
    res = update.message.reply_text(
        f'Вы ўпэўненыя, што хочаце даслаць гэтае паведамленне?',
        reply_markup=reply_markup,
        reply_to_message_id=conversation_context[chat_id][K_FB_MESSAGE_ID]
    )
    conversation_context[chat_id][K_FB_MESSAGE_WITH_INLINE_KEYBOARD_ID] = res.message_id
    return FEEDBACK_VERIFICATION


def clean_on_feedback_conversation_end(chat_id, bot):
    """ remove fields with message_ids from conversation context dict """
    if K_FB_MESSAGE_ID in conversation_context[chat_id]:
        del conversation_context[chat_id][K_FB_MESSAGE_ID]
    # remove inline keyboard
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
    context.bot.send_message(chat_id, 'Вашае паведамленне дасланае.\nВялікі дзякуй!')
    context.bot.answer_callback_query(callback_query_id=query.id)
    clean_on_feedback_conversation_end(chat_id, context.bot)
    return ConversationHandler.END


def feedback_conversation_canceled(update: Update, context):
    chat_id = update.effective_user.id
    logger.info(f'conversation canceled. user_id: {chat_id}')
    context.bot.send_message(chat_id, 'Размова перарваная', reply_markup=None)
    clean_on_feedback_conversation_end(chat_id, context.bot)
    if update.callback_query is not None:
        context.bot.answer_callback_query(callback_query_id=update.callback_query.id)
    return ConversationHandler.END


def feedback_conversation_timeout(bot, update, *rest):
    chat_id = update.effective_user.id
    logger.info(f'conversation timeout. chat_id: {chat_id}')
    update.message.reply_text(
        f'Размова перарваная: перавышаны час чакання адказу. Паспрабуйце яшчэ раз.',
        reply_markup=ReplyKeyboardRemove())
    clean_on_feedback_conversation_end(chat_id, bot)


# ********** end of feedback conversation methods **********

def conversation_input_not_recognized(update, context):
    if update.message is None:
        return None
    update.message.reply_text(f'Калі ласка, кіруйцеся інструкцыямі.\n'
                              f'Каб перарваць размову, выкарыстайце каманду /cancel')


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
            FEEDBACK_RECEIVING: [
                CommandHandler('cancel', feedback_conversation_canceled),
                MessageHandler(Filters.all, feedback_received)
            ],
            FEEDBACK_VERIFICATION: [
                CallbackQueryHandler(feedback_verified, pattern=f'^{FEEDBACK_VERIFY}$'),
                CallbackQueryHandler(feedback_conversation_canceled, pattern=f'^{FEEDBACK_REJECT}$'),
            ],
            ConversationHandler.TIMEOUT: [MessageHandler(Filters.all, feedback_conversation_timeout)]
        },
        fallbacks=[CommandHandler('cancel', feedback_conversation_canceled),
                   MessageHandler(Filters.all, conversation_input_not_recognized)],
        allow_reentry=True,
        conversation_timeout=20 * 60
    )
    dp.add_handler(conversation_feedback)

    dp.add_handler(CommandHandler('start', start))
    dp.add_handler(CommandHandler('about', about))
    dp.add_handler(CommandHandler('get', send_random_word))
    dp.add_handler(CommandHandler('help', help))
    dp.add_handler(CommandHandler('joke', dad_joke))
    dp.add_handler(CallbackQueryHandler(photo_inline_keyboard_handler))
    dp.add_handler(MessageHandler(Filters.command, unknown_command))

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
