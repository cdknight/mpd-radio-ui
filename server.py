from flask import Flask, render_template, send_file, jsonify
from flask_socketio import SocketIO, emit, send

from mpd import MPDClient
from mpd.base import CommandError

from mutagen import File
from io import BytesIO
from pathlib import Path

import config

import os
import time
import threading

app = Flask(__name__)
app.config["SECRET_KEY"] = config.SECRET_KEY # TODO change this

socketio = SocketIO(app, async_mode='eventlet')

mpd_client = MPDClient()
# we do this by default since this is running on the local machine
mpd_client.connect(config.MPD_HOST, config.MPD_PORT) 

global mpd_current_song
global client_count

# TODO don't hardcode this
music_directory = config.MPD_MUSIC_DIRECTORY

mpd_current_song = ''
client_count = 0

background_task_running = False

@app.route("/")
def index():
    print(mpd_client.currentsong())
    return render_template("index.html", stream_url=config.STREAM_URL)

@app.route("/album_art")
def album_art():
    if not mpd_current_song:
        return jsonify({"status": 404, "msg": "No song playing or no clients connected"}), 404
    try:
        current_song_albumart = mpd_client.albumart(mpd_current_song).get('binary')
        if current_song_albumart:
            album_art_bytes = BytesIO(current_song_albumart)
            return send_file(album_art_bytes, mimetype='image/jpeg')
        else: 
            raise CommandError('missing album art')
    # mpd is being a bad
    except CommandError:
        # Try reading directly from the file
        music_file = os.path.join(music_directory, mpd_current_song)
        file = File(music_file)

        # try the APIC method
        apic_data = file.get('APIC:')
        if apic_data:
            return send_file(BytesIO(apic_data.data), mimetype='image/jpeg')

        # try pictures for FLACs
        for picture in file.pictures:
            print(picture)
            return send_file(BytesIO(picture.data), mimetype='image/jpeg')


        # try to get cover art from the directory
        # https://github.com/mpv-player/mpv/issues/3056
        # look for [Ff]older.jpg or cover.jpg
        dirname = os.path.dirname(music_file)

        for album_image in ("cover.jpg", "folder.jpg", "Folder.jpg"):
            album_image_abspath = Path(dirname)/Path(album_image)
            if album_image_abspath.exists():
                return send_file(album_image_abspath)

        return jsonify({"status": 404}), 404


@socketio.on('connect')
def connect():
    global client_count
    client_count += 1

    socketio.emit("subscriber_connect", client_count)

    # Only start this task once
    if not background_task_running:
        print("Starting mpd monitor thread")
        socketio.start_background_task(mpd_status_change)

    socketio.emit('mpd_track_change', currentsong_cleaned())

@socketio.on('disconnect')
def disconnect():
    global client_count
    client_count -= 1

    socketio.emit("subscriber_connect", client_count)


def mpd_status_change():
    global mpd_current_song 
    background_task_running = True

    while True:
        # TODO can we just use the id key?
        tmp_current_song = mpd_client.currentsong().get('file')

        # change the song on all clients if the song changed
        if tmp_current_song != mpd_current_song:
            mpd_current_song = tmp_current_song 
            socketio.emit('mpd_track_change', currentsong_cleaned())

        # wait a second before changing the track info
        socketio.sleep(1) 

def currentsong_cleaned():
    # remove file since we don't want people to see that
    current_song_data = mpd_client.currentsong()
    del current_song_data['file']

    return current_song_data

print(mpd_client.listfiles())

if __name__ == "__main__":
    socketio.run(app, host=config.HOST, port=config.PORT)
