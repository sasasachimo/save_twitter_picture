from requests_oauthlib import OAuth1Session, OAuth1
import json
import os
import urllib
import requests
import sys
from datetime import datetime, timedelta, timezone
import pytz
from googleapiclient.discovery import build
from httplib2 import Http
from oauth2client import client,tools
from oauth2client.file import Storage
from pathlib import Path
import logging
import time
import key

# logging setting
logging.basicConfig(level=logging.ERROR)
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# google api config
API_TRY_MAX = 2
SCOPES = ['https://www.googleapis.com/auth/photoslibrary']
API_SERVICE_NAME = 'photoslibrary'
API_VERSION = 'v1'
TOKEN_FILE = 'credentials.json'

# twitter api config
TL = "https://api.twitter.com/1.1/statuses/user_timeline.json"
CK = key.CONSUMER_KEY
CS = key.CONSUMER_SECRET
AT = key.ACCESS_TOKEN
AS = key.ACCESS_TOKEN_SECRET

# store file config
image_dir = '/tmp'
exts = ['.jpg', '.png', '.mp4', 'gif']

# set using album name
album_name = key.ALBUM_NAME

# set yesterday and today timestamp
today = datetime.now(pytz.timezone('UTC'))
yesterday = today - timedelta(days=1)
yesterday_dt = datetime.strptime((yesterday.strftime("%Y/%m/%d 00:00:00 +0000")), '%Y/%m/%d %H:%M:%S %z')
today_dt = datetime.strptime((today.strftime("%Y/%m/%d 00:00:00 +0000")), '%Y/%m/%d %H:%M:%S %z')
SEARCHRANGE_START = yesterday_dt
SEARCHRANGE_END = today_dt

# script for Twitter
# oauth
twitter = OAuth1Session(CK, CS, AT, AS) 

# get TL of target userid (200 Tweet)
def getTL():
    global req,timeline
    params = {
        "screen_name":key.USERID , 
        "count":200,                
        "include_entities":True,    
        "exclude_replies":False,
        "include_rts":False         
    }
    req = twitter.get(TL,params=params)
    if req.status_code == 200:
        timeline = json.loads(req.text)
        logger.info("GetTL OK")
    else:
        logger.error("Failed: %d" % req.status_code)
    return(timeline)

# extract only yesterday(UTC) TL
def yesterday_tl():
    period_tl = []
    for n in range(0, len(timeline)):
        if datetime.strptime(timeline[n]['created_at'], "%a %b %d %H:%M:%S %z %Y") < SEARCHRANGE_END and SEARCHRANGE_START <= datetime.strptime(timeline[n]['created_at'], "%a %b %d %H:%M:%S %z %Y"):
            period_tl.append(n)
    return period_tl

# download media (Movieが怪しいというかアップできてないがapiの仕様っぽい。やり方ありそうだけど放置)
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
                    filename = image_dir + "/" + content[m]["id_str"] + ".gif"
                    try:
                        urllib.request.urlretrieve(video_url, filename)
                        logger.info("Movie is saved successfully")
                    except:
                        logger.error("Movie save error")
        time.sleep(0.5)

# script for Google photo
# set oauth
def get_authenticated_service():
    store = Storage(TOKEN_FILE)
    creds = store.get()
    if not creds or creds.invalid:
        flow = client.flow_from_clientsecrets(TOKEN_FILE, SCOPES)
        creds = tools.run_flow(flow, store)
    return build(API_SERVICE_NAME, API_VERSION, http=creds.authorize(Http()))

# execute service api
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

# get album id list
def get_album_id_list(service):
    nextPageToken = ''
    album_id_list = {}
    while True:
        album_list = execute_service_api(
                            service.albums().list(
                                    pageSize=50,
                                    pageToken=nextPageToken),
                            'service.albums().list().execute()')
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

# create new album
def create_new_album(album_name):
    logger.debug('create album: {}'.format(album_name))
    new_album = {'album': {'title': album_name}}
    response = service.albums().create(body=new_album).execute()
    logger.debug('id: {}, title: {}'.format(response['id'], response['title']))
    return response['id']

# upload image def
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
            upload_token = response.content.decode('utf-8')
            break
        except Exception as e:
            logger.error(e)
            if i < (API_TRY_MAX - 1):
                time.sleep(3)
    else:
        logger.error('upload retry out')
        sys.exit(1)

    new_item = {'albumId': album_id,
                'newMediaItems': [{'simpleMediaItem': {'uploadToken': upload_token}}]}
    response = execute_service_api(
                    service.mediaItems().batchCreate(body=new_item),
                    'service.mediaItems().batchCreate().execute()')
    status = response['newMediaItemResults'][0]['status']
    logger.debug('batchCreate status: {}'.format(status))
    return status

def execute_upload_image():
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

def lambda_handler(event, context):
    # Twitter 
    timeline = getTL()
    period_tl = yesterday_tl()
    saveImg(period_tl)
    # Google photo
    service = get_authenticated_service()
    album_id_list = get_album_id_list(service)
    if album_id_list[album_name] == '':
        create_new_album(album_name)
        album_id_list = get_album_id_list(service)
    album_id = album_id_list[album_name]
    execute_upload_image()
 
if __name__ == "__main__":
    image_dir = './tmp'
    # Twitter 
    timeline = getTL()
    period_tl = yesterday_tl()
    saveImg(period_tl)
    # Google photo
    service = get_authenticated_service()
    album_id_list = get_album_id_list(service)
    if album_id_list[album_name] == '':
        create_new_album(album_name)
        album_id_list = get_album_id_list(service)
    album_id = album_id_list[album_name]
    execute_upload_image()