import os

from lieksika_bot import LieksikaBot


def main():
    # token = os.environ.get('BOT_TOKEN_TEST')
    token = os.environ.get('BOT_TOKEN')
    contact_chat_id = os.environ.get('CONTACT_CHAT_ID')
    mode = os.environ.get('MODE')
    heroku_app_name = os.environ.get('APP_NAME')
    port = os.environ.get('PORT')

    photos_file_ids_fp = 'photo_file_ids.json'
    # photos_file_ids_fp = 'photo_file_ids_test.json'

    bot = LieksikaBot(token, contact_chat_id, photos_file_ids_fp)
    if mode == 'heroku':
        bot.set_heroku_mode(heroku_app_name, port)
    bot.run()


if __name__ == '__main__':
    main()
