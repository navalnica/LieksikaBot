import os

from lieksika_bot import LieksikaBot


def get_env_var(var, valid_options=None):
    var = os.environ.get(var)
    if var is None:
        raise EnvironmentError(f'{var} env variable is not specified')
    if valid_options is not None:
        if var not in valid_options:
            raise EnvironmentError(f'{var} env variable must be in "{valid_options}"')
    return var


def main():
    token = get_env_var('BOT_TOKEN')
    # token = get_env_var('BOT_TOKEN_TEST')
    mode = get_env_var('MODE', valid_options=['heroku', 'local'])
    contact_chat_id = get_env_var('CONTACT_CHAT_ID')

    port = os.environ.get('PORT')
    heroku_app_name = os.environ.get('APP_NAME')

    photos_file_ids_fp = 'photo_file_ids.json'
    # photos_file_ids_fp = 'photo_file_ids_test.json'

    if mode == 'heroku':
        if port is None:
            raise EnvironmentError('PORT variable not found in environment')
        else:
            port = int(port)
        if heroku_app_name is None:
            raise EnvironmentError('APP_NAME variable not found in environment')

    bot = LieksikaBot(token, contact_chat_id, mode, photos_file_ids_fp)
    if mode == 'heroku':
        bot.set_heroku_mode(heroku_app_name, port)
    bot.run()


if __name__ == '__main__':
    main()
