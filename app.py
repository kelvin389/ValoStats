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
REQUEST_TIMEOUT_CONNECT = 5
REQUEST_TIMEOUT_READ = 4

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
    print(f"client left room {room}")

@socketio.on("load-init-matches")
def load_init_matches(username, start_index, end_index):
    pieces = username.split("#")
    name = ""
    tag = ""
    if len(pieces) >= 2:
        name = pieces[0]
        tag = pieces[1]

    # reset start and end when puuid changes
    puuid = query_puuid(name, tag)
    if puuid:
        emit("set-puuid", puuid, to=request.sid)
        load_more_matches(puuid, start_index, end_index)
    else:
        print("BAD TAG")
        emit("show-bad-user-error")

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

def query_account_info(name, tag):
    url_ext = f"/v1/account/{name}/{tag}"
    params = {
        "api_key": api_key
    }
    response = query_get(URL_BASE + url_ext, params)
    return response.json() if response else None

def query_puuid(name, tag):
    acc_info = query_account_info(name, tag)
    if acc_info:
        return acc_info["data"]["puuid"]
    return None
    

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

    response = query_post(URL_BASE + url_ext, headers, data)
    return response.json()
    
def query_match_info(match_id):
    url_ext = f"/v2/match/{match_id}"
    params = {
        "api_key": api_key
    }
    response = query_get(URL_BASE + url_ext, params)
    return response.json()

# filter through match info and extract only information that is relevent to show on the frontend.
# this reduces the amount of data being sent through socketio due to the majority of match info being useless (for my use case)
def get_relevent_info_small(match_info, puuid):
    info = {}
    info["match_id"] = match_info["metadata"]["matchid"]
    info["map"] = match_info["metadata"]["map"]
    info["start_time"] = match_info["metadata"]["game_start"] * 1000 # convert from seconds to ms since epoch
    info["mode"] = match_info["metadata"]["mode"]
    all_players = match_info["players"]["all_players"]

    max_non_self_kills = -1
    for player in all_players:
        # track highest kills out of all other players if mode is deathmatch
        if info["mode"].lower() == "deathmatch":
            max_non_self_kills = max(player["stats"]["kills"], max_non_self_kills)

        if player["puuid"] == puuid:
            info["character"] = player["character"].lower()
            info["tier"] = player["currenttier"]
            info["stats"] = player["stats"]

            # for normal matches, gather remaining team info and return
            if info["mode"].lower() != "deathmatch":
                team_name = player["team"].lower()
                info["team_info"] = match_info["teams"][team_name]
                return info

    # only deathmatches should reach this point.
    # gather remaining info for deathmatch and return
    won = True if match_info["rounds"][0]["winning_team"] == puuid else False
    info["team_info"] = {"has_won": won, "rounds_won": info["stats"]["kills"], "rounds_lost": max_non_self_kills}

    return info

def get_relevent_info_large(match_info):
    info = {}
    info["match_id"] = match_info["metadata"]["matchid"]
    info["map"] = match_info["metadata"]["map"]
    info["start_time"] = match_info["metadata"]["game_start"] * 1000 # convert from seconds to ms since epoch
    info["mode"] = match_info["metadata"]["mode"]

    info["rounds"] = match_info["rounds"]
    info["num_rounds"] = len(match_info["rounds"])

    if info["mode"].lower() == "deathmatch":
        info["players_dm"] = match_info["players"]["all_players"]
    else:
        info["players_red"] = match_info["players"]["red"]
        info["players_blue"] = match_info["players"]["blue"]

    return info


# wrapper function for requests.get() that accounts for rate limiting
def query_get(url, params):
    # retry 5 times then just give up.
    # i is also used to slightly increase sleep time between retries
    for i in range(5):
        try:
            print("sent get", url)
            response = requests.get(url, params, timeout=(REQUEST_TIMEOUT_CONNECT, REQUEST_TIMEOUT_READ))
            print("got resp")

            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                print(response.json())
                print(response.headers)
                print(f"rate limited while trying {url}. waiting {RATE_LIMIT_SLEEP_TIME + i} seconds and retrying")
                time.sleep(RATE_LIMIT_SLEEP_TIME + i)
            else:
                print("UNEXPECTED RESPONSE:", response, response.reason)
                break
        except:
            print(f"request for {url} timed out")

    return None

# wrapper function for requests.post() that accounts for rate limiting
def query_post(url, headers, json):
    # retry 5 times then just give up.
    # i is also used to slightly increase sleep time between retries
    for i in range(5):
        try:
            print("sent post")
            response = requests.post(url, headers=headers, json=json, timeout=(REQUEST_TIMEOUT_CONNECT, REQUEST_TIMEOUT_READ))
            print("got resp")

            if response.status_code == 200:
                return response
            elif response.status_code == 429:
                print(response.json())
                print(response.headers)
                print(f"rate limited while trying {url}. waiting {RATE_LIMIT_SLEEP_TIME + i} seconds and retrying")
                time.sleep(RATE_LIMIT_SLEEP_TIME + i)
            else:
                print("UNEXPECTED RESPONSE:", response, response.reason)
                break
        except:
            print(f"request for {url} timed out")
    return None


if __name__ == "__main__":
    #print("api key:", api_key)
    #print("flask secret token:", app.config["SECRET_KEY"])
    app.run(host='0.0.0.0', port=5001, debug=True)

