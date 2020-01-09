import json
import logging
import os
import shutil

import telegram
import tqdm
from PIL import Image
from telegram.ext import CallbackContext

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)
logger = logging.getLogger(__name__)


def error_handler(update: telegram.Update, context: CallbackContext):
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def upload_photos_and_store_file_ids(bot, chat_id, photos_dp_list, json_file_fp='photo_file_ids.json'):
    logger.info(f'uploading photos to bot')

    photo_file_ids = {}
    for cur_dp in photos_dp_list:
        cur_photos_fps = get_photos_fps_from_dp(cur_dp)
        for fp in tqdm.tqdm(cur_photos_fps, desc=cur_dp):
            with open(fp, 'rb') as fin:
                res = bot.send_photo(chat_id, fin)
            # it doesn't matter which of scaled images file_id would be saved.
            # but sort images by resolution just in case
            sorted_rev = sorted(res.photo, key=lambda x: max(x['height'], x['width']), reverse=True)
            item = sorted_rev[0]
            file_id = item["file_id"]
            basename = os.path.basename(fp)
            photo_file_ids[basename] = file_id

    logger.info(f'storing photo file_ids to {json_file_fp}')
    with open(json_file_fp, 'w') as fout:
        json.dump(photo_file_ids, fout)


def send_photos_by_file_ids(bot, chat_id, file_ids: dict):
    for k, v in file_ids.items():
        r = bot.send_photo(chat_id, photo=v)
        logger.info(f'sent "{k}" with file_id: "{v}"')


def sort_vertical_from_horizontal_photos(photos_dp):
    vertical_dp = os.path.join(photos_dp, 'vertical')
    horizontal_dp = os.path.join(photos_dp, 'horizontal')
    os.makedirs(vertical_dp, exist_ok=True)
    os.makedirs(horizontal_dp, exist_ok=True)

    photos_fps = get_photos_fps_from_dp(photos_dp)

    for ix, fp in enumerate(photos_fps, start=1):
        img = Image.open(fp)
        width, height = img.size
        if height >= width:
            shutil.copy(fp, vertical_dp)
        else:
            shutil.copy(fp, horizontal_dp)


def get_photos_fps_from_dp(photos_dp):
    photos_fps = [os.path.join(photos_dp, x) for x in os.listdir(photos_dp)
                  if os.path.splitext(x)[-1].lower() in ['.png', '.jpg', '.jpeg']]
    return photos_fps


def crop_and_save_photo_dir(photos_dp, left, up, width, height):
    cropped_dp = os.path.join(photos_dp, f'{os.path.basename(photos_dp)}_cropped')
    os.makedirs(cropped_dp, exist_ok=True)
    photos_fps = get_photos_fps_from_dp(photos_dp)
    for fp in photos_fps:
        cropped_fp = os.path.join(cropped_dp, os.path.basename(fp))
        img = Image.open(fp)
        cropped = img.crop((left, up, left + width, up + height))
        cropped.save(cropped_fp)


def main():
    chat_id = os.environ.get('CONTACT_CHAT_ID')

    # photos_dp_list = [
    #     '/media/storage/lieksika_bot/screens/cropped/12.31.2019/high_nav_bar_vertical_cropped',
    #     '/media/storage/lieksika_bot/screens/cropped/12.31.2019/lo_nav_bar_horizontal_cropped',
    #     '/media/storage/lieksika_bot/screens/cropped/12.31.2019/lo_nav_bar_vertical_cropped'
    # ]
    # upload_photos_and_store_file_ids(dp.bot, chat_id, photos_dp_list)

    # with open('photo_file_ids.json', 'rb') as fin:
    #     photo_file_ids = json.load(fin)
    # send_photos_by_file_ids(dp.bot, chat_id, photo_file_ids)

    # # filter horizontal from vertical photos
    # photos_dp = '/media/storage/lieksika_bot/screens/new'
    # sort_vertical_from_horizontal_photos(photos_dp)

    # # crop photos
    # root_photos_dp = '/media/storage/lieksika_bot/screens/12.30.19'
    # crop_and_save_photo_dir(f'{root_photos_dp}/high_nav_bar_vertical', 0, 117, 1065, 2019)
    # crop_and_save_photo_dir(f'{root_photos_dp}/lo_nav_bar_horizontal', 116, 72, 2119, 930)
    # crop_and_save_photo_dir(f'{root_photos_dp}/lo_nav_bar_vertical', 0, 117, 1065, 2118)


if __name__ == '__main__':
    main()
