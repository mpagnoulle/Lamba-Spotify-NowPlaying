import os, json, time, boto3, requests, re

# Connecting to DynamoDB
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table("mxpg_spotnp")

# Fetch our secrets for env
clientId = os.environ["client_id"]
clientSecret = os.environ["client_secret"]
refreshToken = os.environ["refresh_token"]

# Spotify API endpoints
currentlyPlayingEP = "https://api.spotify.com/v1/me/player/currently-playing"
lastPlayedEP = "https://api.spotify.com/v1/me/player/recently-played"


"""
  Lambda handler
"""
def lambda_handler(event, context):
    # Default vars
    lastRequestAt = 0
    
    currentSong = { "title": "", "artist": "", "coverURL": "", "isPlaying": False, 'isCached': True, "externalURL": "" }

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
    currentSong['externalURL'] = dbResponse["Item"]["externalURL"]

    if lastRequestAt < time.time(): # If the last request was more than 5s ago, make a new one
      reqResult = makeRequest(currentlyPlayingEP, accessToken)

      if reqResult.status_code == 200: # If something is playing
        currentSong = setCurrentSong(currentSong, reqResult.json()["item"])
        updateIsPlaying(reqResult.json()["is_playing"])
      elif reqResult.status_code == 204: # If nothing is playing
        reqResult = makeRequest(lastPlayedEP, accessToken)
        updateIsPlaying(False)

        if reqResult.status_code == 200:
          currentSong = setCurrentSong(currentSong, reqResult.json()["items"][0]["track"])

      updateLastReqTime() # Update the last request time in the DB

    return {
        "statusCode": 200,
        "headers": {
            "Access-Control-Allow-Origin": "https://mxpg.eu",
            "content-type": "application/json",
        },
        "body": json.dumps(
            {
                "songTitle": currentSong['title'],
                "artistName": currentSong['artist'],
                "coverURL": currentSong['coverURL'],
                "externalURL": currentSong['externalURL'],
                "isPlaying": currentSong['isPlaying'],
                "isCached": currentSong['isCached'],
            }
        ),
    }

"""
  Gets a new access token from the Spotify API
  Endpoint: https://accounts.spotify.com/api/token
"""
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

"""
  Makes a request to the Spotify API
  Returns the request object
"""
def makeRequest(url, accessToken):
    try:
      headers = { 'Authorization': 'Bearer ' + accessToken,
                  'Content-Type': 'application/json', 
                  'Accept': 'application/json'
      }

      return requests.get(url, headers=headers)
    except Exception as e:
        print("ERR:" + str(e))

"""
  Updates the current song in the DB
  Returns currentSong whether it has changed or not
"""
def setCurrentSong(currentSong, reqJSON):
  builtArtistName = buildArtistName(reqJSON["artists"])
  builtSongTitle = buildSongTitle(reqJSON["name"])

  if currentSong['title'] != builtSongTitle or currentSong['artist'] != builtArtistName: # If the song has changed
      currentSong['isCached'] = False
      currentSong['title'] = builtSongTitle
      currentSong['artist'] = builtArtistName
      currentSong['coverURL'] = reqJSON["album"]["images"][1]["url"]
      currentSong['externalURL'] = reqJSON["external_urls"]["spotify"]
              
      updateSongInfo(currentSong) # Update the song info in the DB
  return currentSong
  

"""
  Builds the artist name from the artists array
  Returns a string
"""
def buildArtistName(artists):
    artistsBuilt = ""
    count = 0
    for artist in artists:
      if count > 0:
        artistsBuilt += ', '
      artistsBuilt += artist['name']
      count += 1
    artistsBuilt.strip()
    return artistsBuilt

"""
  Builds the song title
  Returns a string
"""
def buildSongTitle(title):
  pat = r'\(feat.*?\)|\(with.*?\)'
  titleBuilt = re.sub(pat, '', title, flags=re.IGNORECASE)
  titleBuilt.strip()
  return titleBuilt

"""
  Updates the song info in the DB
"""
def updateSongInfo(songData):
    try:
      table.put_item(
          Item={
              "mxpg_type": "current_song",
              "songTitle": songData['title'],
              "artistName": songData['artist'],
              "coverURL": songData['coverURL'],
              "isPlaying": songData['isPlaying'],
              "externalURL": songData['externalURL'],
          }
      )
    except Exception as e:
        print("ERR:" + str(e))

"""
  Updates the last request time in the DB
"""
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

"""
  Updates the isPlaying value in the DB
"""
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
