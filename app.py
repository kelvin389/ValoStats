import requests
import json
# loading from .env
from dotenv import load_dotenv
from os import getenv
# flask
from flask import Flask, request, render_template, redirect, url_for, jsonify
from flask_socketio import SocketIO, emit

URL_BASE = "https://api.henrikdev.xyz/valorant"
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
    return render_template("match_history.html")

@socketio.on("load-init-matches")
def change_puuid(username):
    pieces = username.split("#")
    name = pieces[0]
    tag = pieces[1]

    # reset start and end when puuid changes
    global puuid
    global start
    global end
    puuid = query_account_info(name, tag)["data"]["puuid"]
    start = 0
    end = 5
    load_more_matches()

@socketio.on("load-more-matches")
def load_more_matches():
    global puuid
    global start
    global end
    load_match_history(puuid, start, end)
    start += 5
    end += 5

# TODO: this queries the match again. the previously queried data can probably just be used for efficiency
@socketio.on("load-specific-match")
def load_specific_match(match_id): 
    match_info = query_match_info(match_id)["data"]
    info = get_relevent_info_large(match_info)
    socketio.emit("display-specific-match", info)

def load_match_history(puuid, start_index, end_index):
    # show loading text on page
    socketio.emit("show-loading")

    # query API for MatchID of recent matches
    data = query_match_history(puuid, "na", start_index, end_index)
    matches = data["History"]

    # query API for match info of every match.
    match_infos = []
    for match in matches:
        id = match["MatchID"]
        info = query_match_info(id)["data"]
        match_infos.append(info)

    # hide loading text just before the content is sent and shown
    socketio.emit("hide-loading")

    # filter by useful data and send to frontend
    for match_info in match_infos:
        info = get_relevent_info_small(match_info, puuid)
        socketio.emit("append-match-history", info)

def query_account_info(name, tag):
    url_ext = f"/v1/account/{name}/{tag}"
    params = {
        "api_key": api_key
    }
    response = requests.get(URL_BASE + url_ext, params)
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
    response = requests.post(URL_BASE + url_ext, headers=headers, json=data)
    return response.json()
    
def query_match_info(match_id):
    url_ext = f"/v2/match/{match_id}"
    params = {
        "api_key": api_key
    }
    response = requests.get(URL_BASE + url_ext, params)
    return response.json()

# filter through match info and extract only information that is relevent to show on the frontend.
# this reduces the amount of data being sent through socketio due to the majority of match info being useless
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
            info["team_info"] = match_info["teams"][team_name]
            break
    
    #print(info)
    return info

def get_relevent_info_large(match_info):
    info = {}
    info["match_id"] = match_info["metadata"]["matchid"]
    info["map"] = match_info["metadata"]["map"]
    info["start_time"] = match_info["metadata"]["game_start"] * 1000 # convert from seconds to ms since epoch
    info["mode"] = match_info["metadata"]["mode"]

    info["num_rounds"] = len(match_info["rounds"])

    info["players_red"] = match_info["players"]["red"]
    info["players_blue"] = match_info["players"]["blue"]

    #print(info)
    return info

if __name__ == "__main__":
    #print("api key:", api_key)
    #print("flask secret token:", app.config["SECRET_KEY"])
    app.run(host='0.0.0.0', port=5001, debug=True)

