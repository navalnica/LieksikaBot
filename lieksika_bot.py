import json
import logging
import os

import numpy as np
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from telegram.ext import Updater, CallbackContext, CommandHandler, MessageHandler, Filters, CallbackQueryHandler

# *************** global variables ***************

# TODO: reformat as separate class with attributes

RESEND_CURRENT, KEEP_CURRENT = range(2)
last_photo_message_id_key = 'last_photo_message_id'

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)

with open('photo_file_ids.json') as fin:
    photo_file_ids = json.load(fin)
    photo_file_ids = list(photo_file_ids.items())

contact_chat_id = os.environ.get('CONTACT_CHAT_ID')
if not contact_chat_id:
    raise EnvironmentError('CONTACT_CHAT_ID variable not found in environment')


# *************** end of global variables ***************


def error_handler(update: Update, context: CallbackContext):
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def remove_inline_keyboard_from_last_photo(bot, chat_id, user_data):
    if last_photo_message_id_key in user_data:
        bot.edit_message_reply_markup(
            chat_id,
            user_data[last_photo_message_id_key],
            reply_markup=None
        )
        del user_data[last_photo_message_id_key]


def start(update: Update, context: CallbackContext):
    remove_inline_keyboard_from_last_photo(context.bot, update.effective_user.id, context.user_data)
    bot_description = ('Прывітанне! Lieksika Bot умее дасылаць цікавыя беларускія словы. '
                       'Каб атрымаць выпадковае слова, карыстайце каманду /get. '
                       'У будучыні плануецца дадаць магчымасць рэгулярнай рассылкі словаў, напрыклад штодня, '
                       'а таксама магчымасць запамінаць, якія словы вы праглядалі раней, каб не паўтарацца.')
    update.message.reply_text(bot_description)
    help(update, context)

    u = update.effective_user
    description = (f'New bot user!\n\n'
                   f'id: {u.id}\n'
                   f'full name: {u.full_name}\n'
                   f'language code: {u.language_code}')
    if u.username is not None:
        description += f'\nlink: @{u.username}'
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
           f'/get: даслаць выпадковае слова\n'
           f'/joke: даслаць жарт)\n'
           f'/help: паказаць спіс даступных камандаў'
           )
    update.message.reply_text(msg)


def unknown_command(update: Update, context: CallbackContext):
    remove_inline_keyboard_from_last_photo(context.bot, update.effective_user.id, context.user_data)
    logger.info(f'unrecognized command: {update.message.text}')
    update.message.reply_text(f'Выбачайце, каманда не пазнаная: {update.message.text}')
    help(update, context)


def _send_photo(bot, chat_id, photo, user_data):
    buttons = [[
        InlineKeyboardButton(text='Іншае', callback_data=str(RESEND_CURRENT)),
        InlineKeyboardButton(text='Захаваць', callback_data=str(KEEP_CURRENT))
    ]]
    keyboard = InlineKeyboardMarkup(buttons)
    res = bot.send_photo(
        chat_id=chat_id,
        photo=photo,
        reply_markup=keyboard
    )
    user_data[last_photo_message_id_key] = res.message_id


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
    data = int(query.data)
    ix = np.random.randint(0, len(photo_file_ids))
    photo = photo_file_ids[ix][1]
    logger.info(f'inline_keyboard_handler. chat_id: {chat_id}, new file_id: {photo}')
    if data == RESEND_CURRENT:
        res = context.bot.edit_message_media(
            chat_id=chat_id,
            message_id=query.message['message_id'],
            media=InputMediaPhoto(media=photo),
            reply_markup=query.message.reply_markup
        )
    elif data == KEEP_CURRENT:
        remove_inline_keyboard_from_last_photo(context.bot, chat_id, context.user_data)
        _send_photo(context.bot, query.from_user.id, photo, context.user_data)
    else:
        raise ValueError(f'could not parse data: {data}')


def main():
    heroku_app_name = "dtowddf-bot"

    token = os.environ.get('BOT_TOKEN')
    if not token:
        raise EnvironmentError('BOT_TOKEN variable not found in environment')

    mode = os.environ.get('MODE')
    if not mode or mode not in ['heroku', 'local']:
        raise EnvironmentError('MODE (heroku|local) variable not found in environment')
    logger.info(f'running in {mode} mode')

    port = os.environ.get('PORT')
    if mode == 'heroku':
        if port is None:
            raise EnvironmentError('PORT variable not found in environment')
        else:
            port = int(port)

    updater = Updater(token, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler('start', start))
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
        updater.start_polling()
    updater.idle()


if __name__ == '__main__':
    main()
