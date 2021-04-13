from requests_oauthlib import OAuth1Session, OAuth1
import json
import requests
from datetime import datetime, timedelta, timezone
import pytz
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import client
from oauth2client import tools
from oauth2client.file import Storage
from pathlib import Path
import logging
import time
import sys
import os
import urllib
import twitkey

# logging
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

'''
基本情報設定
'''

#googleapi関連の設定
API_TRY_MAX = 2
SCOPES = ['https://www.googleapis.com/auth/photoslibrary']
API_SERVICE_NAME = 'photoslibrary'
API_VERSION = 'v1'
TOKEN_FILE = 'credentials.json'
image_dir = '/tmp'
exts = ['.jpg', '.png', '.mp4']
### 対象のAlbum名を指定
album_name = twitkey.ALBUM_NAME


#前日の00:00:00,当日00:00:00のtimestampを取得
today = datetime.now(pytz.timezone('UTC'))
yesterday = today - timedelta(days=1)
yesterday_dt = datetime.strptime((yesterday.strftime("%Y/%m/%d 00:00:00 +0000")), '%Y/%m/%d %H:%M:%S %z')
today_dt = datetime.strptime((today.strftime("%Y/%m/%d 00:00:00 +0000")), '%Y/%m/%d %H:%M:%S %z')

SEARCHRANGE_START = yesterday_dt
SEARCHRANGE_END = today_dt
TL = "https://api.twitter.com/1.1/statuses/user_timeline.json"

CK = twitkey.CONSUMER_KEY
CS = twitkey.CONSUMER_SECRET
AT = twitkey.ACCESS_TOKEN
AS = twitkey.ACCESS_TOKEN_SECRET


#画像保存フォルダがなければ作成
def create_image_dir(new_dir_path):
    if not os.path.isdir(new_dir_path):
        os.makedirs(new_dir_path)
        logger.debug('makedir {}'.format(new_dir_path))

'''
Twitter
'''

# OAuth認証 セッションを開始
twitter = OAuth1Session(CK, CS, AT, AS) 

params = {
    "screen_name":twitkey.USERID , 
    "count":200,                
    "include_entities":True,    
    "exclude_replies":False,    
    "include_rts":False         
} 

def getTL():
    global req,timeline,content
    req = twitter.get(TL,params=params)
    if req.status_code == 200:
        timeline = json.loads(req.text)
        logger.info("GetTL OK")
    else:
        logger.error("Failed: %d" % req.status_code)
    return(timeline)

def yesterday_tl():
    period_tl = []
    for n in range(0, len(timeline)):
        if datetime.strptime(timeline[n]['created_at'], "%a %b %d %H:%M:%S %z %Y") < SEARCHRANGE_END and SEARCHRANGE_START <= datetime.strptime(timeline[n]['created_at'], "%a %b %d %H:%M:%S %z %Y"):
            period_tl.append(n)
    return period_tl

def saveImg(period_tl):
    for n in period_tl:
        if 'extended_entities' in timeline[n]:
            content = timeline[n]["extended_entities"]["media"]
            for m in range(0, len(content)):
                if content[m]['type'] == "photo":
                    image_url = content[m]["media_url"] + ":orig"
                    filename = image_dir + "/" + content[m]["id_str"] + ".jpg"
                    logger.info('download filename is {}'.format(filename))
                    try:
                        urllib.request.urlretrieve(image_url, filename)
                        logger.info("Image is saved successfully")
                    except:
                        logger.error("Image save error")
                elif content[m]['type'] == "video":
                    video_url = content[m]["media_url"] + ":orig"
                    filename = image_dir + "/" + content[m]["id_str"] + ".mp4"
                    try:
                        urllib.request.urlretrieve(video_url, filename)
                        logger.info("Movie is saved successfully")
                    except:
                        logger.error("Movie save error")
        time.sleep(0.5)


'''
google photos api 関連
'''

def get_authenticated_service():
    store = Storage(TOKEN_FILE)
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets(TOKEN_FILE, SCOPES)
        creds = tools.run_flow(flow, store)
    return build(API_SERVICE_NAME, API_VERSION, http=creds.authorize(Http()))

def execute_service_api(service_api, service_name):
    for i in range(API_TRY_MAX):
        try:
            response = service_api.execute()
            return response
        except Exception as e:
            logger.error(e)
            if i < (API_TRY_MAX - 1):
                time.sleep(3)
    else:
        logger.error('{} retry out'.format(service_name))
        sys.exit(1)

def get_album_id_list(service):
    """
    アルバム名および対応する album id の一覧を返す
    """
    nextPageToken = ''
    album_id_list = {}
    while True:
        album_list = execute_service_api(
                            service.albums().list(
                                    pageSize=50,
                                    pageToken=nextPageToken),
                            'service.albums().list().execute()')
        if len(album_list) == 0 :
            break
        for album in album_list['albums']:
            album_id_list[album['title']] = album['id']
            mediaItemsCount = 0
            if 'mediaItemsCount' in album:
                mediaItemsCount = int(album['mediaItemsCount'])
            logger.debug('{:20} {:3d}'.format(album['title'], mediaItemsCount))
        if 'nextPageToken' not in album_list:
            break
        nextPageToken = album_list['nextPageToken']
    return album_id_list

def create_new_album(album_name):
    logger.debug('create album: {}'.format(album_name))
    new_album = {'album': {'title': album_name}}
    response = service.albums().create(body=new_album).execute()
    logger.debug('id: {}, title: {}'.format(response['id'], response['title']))
    return response['id']

def upload_image(service, image_file, album_id):
    for i in range(API_TRY_MAX):
        try:
            with open(str(image_file), 'rb') as image_data:
                url = 'https://photoslibrary.googleapis.com/v1/uploads'
                headers = {
                    'Authorization': "Bearer " + service._http.request.credentials.access_token,
                    'Content-Type': 'application/octet-stream',
                    'X-Goog-Upload-File-Name': image_file.name,
                    'X-Goog-Upload-Protocol': "raw",
                }
                response = requests.post(url, data=image_data, headers=headers)
            # アップロードの応答で upload token が返る
            upload_token = response.content.decode('utf-8')
            break
        except Exception as e:
            logger.error(e)
            if i < (API_TRY_MAX - 1):
                time.sleep(3)
    else:
        logger.error('upload retry out')
        # エラーでリトライアウトした場合は終了
        sys.exit(1)

    new_item = {'albumId': album_id,
                'newMediaItems': [{'simpleMediaItem': {'uploadToken': upload_token}}]}
    response = execute_service_api(
                    service.mediaItems().batchCreate(body=new_item),
                    'service.mediaItems().batchCreate().execute()')
    status = response['newMediaItemResults'][0]['status']
    logger.info('batchCreate status: {}'.format(status))
    return status

'''
実行
'''

if __name__ == "__main__":
#    create_image_dir(image_dir)
    timeline = getTL()
    period_tl = yesterday_tl()
    saveImg(period_tl)
    service = get_authenticated_service()
    album_id_list = get_album_id_list(service)
    # 対象のアルバム存在有無
    if album_id_list[album_name] == '':
        create_new_album(album_name)
        album_id_list = get_album_id_list(service)
    album_id = album_id_list[album_name]

    path = Path(image_dir)
    if path.is_dir():
        images = sorted([img for img in path.glob('*') if img.suffix in exts])
        if len(images) > 0:
            album_media_set = set()
            album_media_count = 0
            for image_file in images:
                album_media_count += 1
                if image_file.name not in album_media_set:
                    logger.info('{:3d} {} uploading... '.format(album_media_count, image_file.name))
                    status = upload_image(service, image_file, album_id)
                else:
                    logger.debug('{:3d} {} exists'.format(album_media_count, image_file.name))

def lambda_handler(event, context):
#    create_image_dir(image_dir)
    timeline = getTL()
    period_tl = yesterday_tl()
    saveImg(period_tl)
    service = get_authenticated_service()
    album_id_list = get_album_id_list(service)
    # 対象のアルバム存在有無
    if album_id_list[album_name] == '':
        create_new_album(album_name)
        album_id_list = get_album_id_list(service)
    album_id = album_id_list[album_name]

    path = Path(image_dir)
    if path.is_dir():
        images = sorted([img for img in path.glob('*') if img.suffix in exts])
        if len(images) > 0:
            album_media_set = set()
            album_media_count = 0
            for image_file in images:
                album_media_count += 1
                if image_file.name not in album_media_set:
                    logger.debug('{:3d} {} uploading... '.format(album_media_count, image_file.name))
                    status = upload_image(service, image_file, album_id)
                else:
                    logger.debug('{:3d} {} exists'.format(album_media_count, image_file.name))
