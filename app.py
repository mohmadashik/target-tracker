from flask import Flask, render_template, request, redirect, url_for, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
import os
import sqlite3
import shutil
from datetime import datetime
import google.oauth2.credentials
import google_auth_oauthlib.flow
import googleapiclient.discovery

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///progress_tracker.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.secret_key = 'your_secret_key'

db = SQLAlchemy(app)
migrate = Migrate(app, db)

SCOPES = ['https://www.googleapis.com/auth/drive.file']
CLIENT_SECRETS_FILE = 'credentials.json'

class Target(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    target = db.Column(db.Integer, nullable=False)
    progress = db.Column(db.Integer, default=0)

@app.route('/')
def index():
    targets = Target.query.all()
    return render_template('index.html', targets=targets)

@app.route('/create_target', methods=['POST'])
def create_target():
    name = request.form['name']
    target_count = int(request.form['target'])
    new_target = Target(name=name, target=target_count)
    db.session.add(new_target)
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/update_progress', methods=['POST'])
def update_progress():
    target_id = int(request.form['target_id'])
    change = int(request.form['change'])
    target = Target.query.get(target_id)
    if target:
        target.progress += change
        if target.progress < 0:
            target.progress = 0
        elif target.progress > target.target:
            target.progress = target.target
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/backup')
def backup():
    backup_filename = f'progress_tracker_backup_{datetime.now().strftime("%Y%m%d%H%M%S")}.db'
    shutil.copy('progress_tracker.db', backup_filename)
    return redirect(url_for('authorize', action='upload', filename=backup_filename))

@app.route('/restore', methods=['POST'])
def restore():
    return redirect(url_for('authorize', action='restore'))

@app.route('/authorize')
def authorize():
    action = request.args.get('action')
    filename = request.args.get('filename', None)

    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for('oauth2callback', action=action, filename=filename, _external=True)

    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')

    return redirect(authorization_url)

@app.route('/oauth2callback')
def oauth2callback():
    action = request.args.get('action')
    filename = request.args.get('filename', None)

    flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE, scopes=SCOPES)
    flow.redirect_uri = url_for('oauth2callback', action=action, filename=filename, _external=True)

    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)

    credentials = flow.credentials

    if action == 'upload':
        upload_file_to_drive(credentials, filename)
    elif action == 'restore':
        restore_from_drive(credentials)

    return redirect(url_for('index'))

def upload_file_to_drive(credentials, filename):
    drive_service = googleapiclient.discovery.build('drive', 'v3', credentials=credentials)
    file_metadata = {'name': filename, 'parents': ['your_drive_folder_id']}
    media = googleapiclient.http.MediaFileUpload(filename)
    drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    os.remove(filename)

def restore_from_drive(credentials):
    drive_service = googleapiclient.discovery.build('drive', 'v3', credentials=credentials)
    results = drive_service.files().list(q="mimeType='application/x-sqlite3' and name contains 'progress_tracker_backup'",
                                         spaces='drive',
                                         fields='files(id, name)',
                                         orderBy='createdTime desc').execute()
    items = results.get('files', [])

    if not items:
        return

    file_id = items[0]['id']
    request = drive_service.files().get_media(fileId=file_id)
    filename = 'progress_tracker_restore.db'
    with open(filename, 'wb') as f:
        downloader = googleapiclient.http.MediaIoBaseDownload(f, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()

    con = sqlite3.connect('progress_tracker.db')
    cur = con.cursor()
    cur.executescript('''
        DROP TABLE IF EXISTS target;
    ''')
    con.close()
    os.remove('progress_tracker.db')
    shutil.move(filename, 'progress_tracker.db')
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
