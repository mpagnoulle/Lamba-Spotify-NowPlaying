import os, json, time, boto3, requests

# Connecting to DynamoDB
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("mxpg_spotnp")

# Fetch our secrets for env
clientId = os.environ["client_id"]
clientSecret = os.environ["client_secret"]
refreshToken = os.environ["refresh_token"]

def lambda_handler(event, context):
    # Default vars
    lastRequestAt = 0
    
    currentSong = { "title": "", "artist": "", "coverURL": "", "isPlaying": False, 'isCached': True }

    # Get expiration time, access token and last request time from DB
    dbResponse = table.get_item(Key={"mxpg_type": "prod"})
    expiresAt = dbResponse["Item"]["expiresAt"]
    accessToken = dbResponse["Item"]["accessToken"]
    lastRequestAt = dbResponse["Item"]["lastRequestAt"]

    if expiresAt <= time.time(): # If the token is expired, get a new one
        getNewAccessToken(refreshToken)

    # Get the current song from DB
    dbResponse = table.get_item(Key={"mxpg_type": "current_song"})
    currentSong['title'] = dbResponse["Item"]["songTitle"]
    currentSong['artist'] = dbResponse["Item"]["artistName"]
    currentSong['coverURL'] = dbResponse["Item"]["coverURL"]
    currentSong['isPlaying'] = dbResponse["Item"]["isPlaying"]

    if lastRequestAt < time.time(): # If the last request was more than 5s ago, make a new one
      headers = { 'Authorization': 'Bearer ' + accessToken,
                  'Content-Type': 'application/json', 
                  'Accept': 'application/json'
      }

      req = requests.get('https://api.spotify.com/v1/me/player/currently-playing', headers=headers)

      # Check if currently playing
      try:
          currentSong['isCached'] = False

          if req.status_code == 200:
            builtArtistName = buildArtistName(req.json()["item"]["artists"])
            if currentSong['title'] != req.json()["item"]["name"] or currentSong['artist'] != builtArtistName or currentSong["isPlaying"] != req.json()["is_playing"]: # If the song has changed
                currentSong['title'] = req.json()["item"]["name"]
                currentSong['artist'] = builtArtistName
                currentSong['coverURL'] = req.json()["item"]["album"]["images"][1]["url"]
                currentSong['isPlaying'] =  req.json()["is_playing"]
                        
                updateSongInfo(currentSong)
          else:
            updateIsPlaying(False)
          updateLastReqTime()
      except Exception as e:
          print("ERR:" + str(e))

    return {
        "statusCode": 200,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "content-type": "application/json",
        },
        "body": json.dumps(
            {
                "songTitle": currentSong['title'],
                "artistName": currentSong['artist'],
                "coverURL": currentSong['coverURL'],
                "isPlaying": currentSong['isPlaying'],
                "isCached": currentSong['isCached'],
            }
        ),
    }


def getNewAccessToken(refreshToken):
    try:
      data = {
          "client_id": clientId,
          "client_secret": clientSecret,
          "grant_type": "refresh_token",
          "refresh_token": refreshToken,
      }

      req = requests.post("https://accounts.spotify.com/api/token", data=data)
      spotiToken = req.json()
      
      # Place the expiration time, and access token into the DB
      table.update_item(
          Key={
              'mxpg_type': 'prod'
          },
          UpdateExpression='SET expiresAt = :val, accessToken = :val2',
          ExpressionAttributeValues={
              ':val': int(time.time()) + 3300,
              ':val2': spotiToken["access_token"]
          }
      )
    except Exception as e:
        print("ERR:" + str(e))

def buildArtistName(artists):
    artistsBuilt = ""
    count = 0
    for artist in artists:
      if count > 0:
        artistsBuilt += ', '
      artistsBuilt += artist['name']
      count += 1
    return artistsBuilt

def updateSongInfo(songData):
    try:
      table.put_item(
          Item={
              "mxpg_type": "current_song",
              "songTitle": songData['title'],
              "artistName": songData['artist'],
              "coverURL": songData['coverURL'],
              "isPlaying": songData['isPlaying'],
          }
      )
    except Exception as e:
        print("ERR:" + str(e))

def updateLastReqTime():
  table.update_item(
      Key={
          'mxpg_type': 'prod'
      },
      UpdateExpression='SET lastRequestAt = :val',
      ExpressionAttributeValues={
          ':val': int(time.time()) + 5
      }
  )

def updateIsPlaying(isPlaying):
  table.update_item(
      Key={
          'mxpg_type': 'current_song'
      },
      UpdateExpression='SET isPlaying = :val',
      ExpressionAttributeValues={
          ':val': isPlaying
      }
  )
