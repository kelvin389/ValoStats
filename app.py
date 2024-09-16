import requests
import json
import time
# loading from .env
from dotenv import load_dotenv
from os import getenv
# flask
from flask import Flask, request, render_template
from flask_socketio import SocketIO, emit, join_room, leave_room

URL_BASE = "https://api.henrikdev.xyz/valorant"
RATE_LIMIT_SLEEP_TIME = 60

app = Flask(__name__)
socketio = SocketIO(app)

# configure API key and Flask secret keys from .env file
load_dotenv()
api_key = getenv("API_KEY")
app.config["SECRET_KEY"] = getenv("FLASK_SECRET")

@app.route("/")
@app.route("/index")
def index():
    return render_template("index.html")

@app.route("/match_history")
def match_history():
    username = request.args.get("username")
    return render_template("match_history.html", username=username)

@socketio.on("connect")
def connect():
    room = request.sid
    join_room(room)
    print(f"client joined room {room}")
    
@socketio.on("disconnect")
def disconnect():
    room = request.sid
    leave_room(room)
    print(f"client joined room {room}")

@socketio.on("load-init-matches")
def load_init_matches(username, start_index, end_index):
    pieces = username.split("#")
    name = pieces[0]
    tag = pieces[1]

    # reset start and end when puuid changes
    puuid = query_account_info(name, tag)["data"]["puuid"]
    load_more_matches(puuid, start_index, end_index)
    emit("set-puuid", puuid, to=request.sid)

@socketio.on("load-more-matches")
def load_more_matches(puuid, start_index, end_index):
    load_match_history(puuid, start_index, end_index)

# TODO: this queries the match again. the previously queried data can probably just be used for efficiency
@socketio.on("load-specific-match")
def load_specific_match(match_id): 
    match_info = query_match_info(match_id)["data"]
    info = get_relevent_info_large(match_info)
    emit("display-specific-match", (match_id, info), to=request.sid)

def load_match_history(puuid, start_index, end_index):
    # show loading text on page
    emit("show-loading", to=request.sid)

    # query API for MatchID of recent matches
    data = query_match_history(puuid, "na", start_index, end_index)
    matches = data["History"]


    for match in matches:
        id = match["MatchID"]
        match_info = query_match_info(id)["data"]
        info = get_relevent_info_small(match_info, puuid)
        emit("append-match-history", info, to=request.sid)
    emit("hide-loading", to=request.sid)


    # code below loads the matches in batches.
    # replaced by above for loop which loads matches as the api responds (more responsive)
    """
    # query API for match info of every match.
    match_infos = []
    for match in matches:
        id = match["MatchID"]
        print(id)
        info = query_match_info(id)["data"]
        match_infos.append(info)

    # hide loading text just before the content is sent and shown
    emit("hide-loading")

    # filter by useful data and send to frontend
    for match_info in match_infos:
        info = get_relevent_info_small(match_info, puuid)
        emit("append-match-history", info)
    """

def query_account_info(name, tag):
    url_ext = f"/v1/account/{name}/{tag}"
    params = {
        "api_key": api_key
    }
    #response = requests.get(URL_BASE + url_ext, params)
    response = query_get(URL_BASE + url_ext, params)
    return response.json()

def query_match_history(puuid, region, start_index, end_index):
    #queue = "all"

    url_ext = "/v1/raw"
    headers = {
        "Authorization": api_key
    }
    data = {
        "type": "matchhistory",
        "value": puuid,
        "region": region,
        "queries": f"?startIndex={start_index}&endIndex={end_index}"
        #"queries": f"?startIndex={start_index}&endIndex={end_index}&queue={queue}"
    }
    #response = requests.post(URL_BASE + url_ext, headers=headers, json=data)
    response = query_post(URL_BASE + url_ext, headers, data)
    print(response.json())
    return response.json()
    
def query_match_info(match_id):
    url_ext = f"/v2/match/{match_id}"
    params = {
        "api_key": api_key
    }
    #response = requests.get(URL_BASE + url_ext, params)
    response = query_get(URL_BASE + url_ext, params)
    return response.json()

# filter through match info and extract only information that is relevent to show on the frontend.
# this reduces the amount of data being sent through socketio due to the majority of match info being useless (for my use case)
def get_relevent_info_small(match_info, puuid):
    #f = open("data.txt", "w")
    #f.write(json.dumps(match_info))
    #f.close()
    info = {}
    info["match_id"] = match_info["metadata"]["matchid"]
    info["map"] = match_info["metadata"]["map"]
    info["start_time"] = match_info["metadata"]["game_start"] * 1000 # convert from seconds to ms since epoch
    info["mode"] = match_info["metadata"]["mode"]
    all_players = match_info["players"]["all_players"]
    for player in all_players:
        if player["puuid"] == puuid:
            info["character"] = player["character"].lower()
            info["tier"] = player["currenttier"]
            info["stats"] = player["stats"]

            team_name = player["team"].lower()
            if (info["mode"].lower() != "deathmatch"):
                info["team_info"] = match_info["teams"][team_name]
            else:
                info["team_info"] = {}
            break
    
    #print(info)
    return info

def get_relevent_info_large(match_info):
    info = {}
    info["match_id"] = match_info["metadata"]["matchid"]
    info["map"] = match_info["metadata"]["map"]
    info["start_time"] = match_info["metadata"]["game_start"] * 1000 # convert from seconds to ms since epoch
    info["mode"] = match_info["metadata"]["mode"]

    info["rounds"] = match_info["rounds"]
    info["num_rounds"] = len(match_info["rounds"])

    info["players_red"] = match_info["players"]["red"]
    info["players_blue"] = match_info["players"]["blue"]

    #print(info)
    return info


def query_get(url, params):
    # retry 5 times then just give up
    for i in range(5):
        response = requests.get(url, params)

        if response.status_code == 429:
            print(response.json())
            print(response.headers)
            print(f"rate limited while trying {url}. waiting {RATE_LIMIT_SLEEP_TIME} second and retrying")
            time.sleep(RATE_LIMIT_SLEEP_TIME)
        elif response.status_code == 200:
            break
        else:
            print("UNEXPECTED RESPONSE:", response, response.reason)
            break
    return response



def query_post(url, headers, json):
    # retry 5 times then just give up
    for i in range(5):
        response = requests.post(url, headers=headers, json=json)

        if response.status_code == 429:
            print(response.json())
            print(response.headers)
            print(f"rate limited while trying {url}. waiting {RATE_LIMIT_SLEEP_TIME} second and retrying")
            time.sleep(RATE_LIMIT_SLEEP_TIME)
        elif response.status_code == 200:
            break
        else:
            print("UNEXPECTED RESPONSE:", response, response.reason)
            break
    return response


if __name__ == "__main__":
    #print("api key:", api_key)
    #print("flask secret token:", app.config["SECRET_KEY"])
    app.run(host='0.0.0.0', port=5001, debug=True)

