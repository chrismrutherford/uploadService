import os
import uuid
import sqlite3
from datetime import datetime
from flask import Flask, request, render_template, send_file, jsonify, redirect, url_for
from werkzeug.utils import secure_filename
import smtplib
from email.mime.text import MIMEText
import threading

from flask import jsonify

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 * 1024  # 10 GB max file size

# Increase the maximum request body size
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(app.wsgi_app)

# Ensure the upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Database setup
def init_db():
    conn = sqlite3.connect('files.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS files
                 (uuid TEXT PRIMARY KEY, filename TEXT, downloads INTEGER, max_downloads INTEGER, upload_date TEXT)''')
    conn.commit()
    conn.close()

init_db()

@app.route('/', methods=['GET', 'POST'])
def home():
    if request.method == 'POST':
        if 'uuid' in request.form:
            uuid_to_check = request.form['uuid']
            return redirect(url_for('check_file', uuid=uuid_to_check))
    return render_template('home.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'files[]' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    files = request.files.getlist('files[]')

    if not files or files[0].filename == '':
        return jsonify({'error': 'No selected file'}), 400

    results = []
    for file in files:
        if file:
            # Check file size
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)
            if file_size > app.config['MAX_CONTENT_LENGTH']:
                results.append({'filename': file.filename, 'error': 'File too large'})
                continue

            original_filename = secure_filename(file.filename)
            file_uuid = str(uuid.uuid4())
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            new_filename = f"{file_uuid}_{timestamp}_{original_filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], new_filename)
            file.save(file_path)

            upload_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Get max_downloads from form or default to 5
            max_downloads = request.form.get('max_downloads', '5')
            max_downloads = int(max_downloads)
            
            # Save to database
            conn = sqlite3.connect('files.db')
            c = conn.cursor()
            c.execute("INSERT INTO files (uuid, filename, downloads, max_downloads, upload_date) VALUES (?, ?, ?, ?, ?)",
                      (file_uuid, new_filename, 0, max_downloads, upload_date))
            conn.commit()
            conn.close()

            # Send email notification
            client_ip = request.remote_addr
            threading.Thread(target=send_email_notification, args=(new_filename, file_size, file_uuid, client_ip, upload_date)).start()

            results.append({'filename': file.filename, 'uuid': file_uuid, 'message': 'File uploaded successfully'})

    return jsonify(results)

@app.route('/check/<uuid>')
def check_file(uuid):
    conn = sqlite3.connect('files.db')
    c = conn.cursor()
    c.execute("SELECT filename, downloads, max_downloads, upload_date FROM files WHERE uuid = ?", (uuid,))
    result = c.fetchone()
    conn.close()
    
    if result:
        full_filename, downloads, max_downloads, upload_date = result
        # Get original filename (everything after the second underscore)
        original_filename = '_'.join(full_filename.split('_')[2:])
        
        # Get file size
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], full_filename)
        file_size = os.path.getsize(file_path)
        
        # Calculate remaining downloads
        remaining_downloads = "unlimited" if max_downloads == -1 else max_downloads - downloads
        
        return render_template('check.html', 
                               uuid=uuid, 
                               filename=full_filename, 
                               downloads=downloads,
                               remaining_downloads=remaining_downloads,
                               file_size=file_size,
                               upload_date=upload_date)
    return "File not found", 404

@app.route('/download/<uuid>')
def download_file(uuid):
    conn = sqlite3.connect('files.db')
    c = conn.cursor()
    c.execute("SELECT filename, downloads, max_downloads FROM files WHERE uuid = ?", (uuid,))
    result = c.fetchone()
    
    if result:
        full_filename, current_downloads, max_downloads = result
        
        # Check if we've reached max downloads (unless max_downloads is -1)
        if max_downloads != -1 and current_downloads >= max_downloads:
            # Delete the file and database entry
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], full_filename))
            c.execute("DELETE FROM files WHERE uuid = ?", (uuid,))
            conn.commit()
            conn.close()
            return "File has reached maximum downloads and has been deleted", 404
        # Get original filename (everything after the second underscore)
        original_filename = '_'.join(full_filename.split('_')[2:])
        
        # Only increment downloads if max_downloads isn't -1
        if max_downloads != -1:
            c.execute("UPDATE files SET downloads = downloads + 1 WHERE uuid = ?", (uuid,))
            
            # Check if this was the last allowed download
            if current_downloads + 1 >= max_downloads:
                # Schedule file for deletion after sending
                def delete_after_send():
                    os.remove(os.path.join(app.config['UPLOAD_FOLDER'], full_filename))
                    conn = sqlite3.connect('files.db')
                    c = conn.cursor()
                    c.execute("DELETE FROM files WHERE uuid = ?", (uuid,))
                    conn.commit()
                    conn.close()
                threading.Timer(1, delete_after_send).start()
        conn.commit()
        conn.close()
        # Get the original filename (everything after the second underscore)
        download_name = '_'.join(full_filename.split('_')[2:])
        
        return send_file(os.path.join(app.config['UPLOAD_FOLDER'], full_filename), 
                         as_attachment=True, 
                         download_name=download_name)
    
    conn.close()
    return "File not found", 404

@app.route('/delete/<uuid>')
def delete_file(uuid):
    conn = sqlite3.connect('files.db')
    c = conn.cursor()
    c.execute("SELECT filename FROM files WHERE uuid = ?", (uuid,))
    result = c.fetchone()
    
    if result:
        os.remove(os.path.join(app.config['UPLOAD_FOLDER'], result[0]))
        c.execute("DELETE FROM files WHERE uuid = ?", (uuid,))
        conn.commit()
        conn.close()
        return "File deleted successfully"
    
    conn.close()
    return "File not found", 404

def send_email_notification(filename, filesize, file_uuid, client_ip, upload_date):
    sender = "chris@i2x.uk"
    recipient = "chris@i2x.uk"
    subject = "File Uploaded"
    body = f"""A file has been uploaded:
Name: {filename}
Size: {filesize / (1024 * 1024 * 1024):.2f} GB
UUID: {file_uuid}
Client IP: {client_ip}
Upload Date: {upload_date}

Download Link: https://192.168.1.158:5003/check/{file_uuid}
"""

    msg = MIMEText(body)
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient

    try:
        with smtplib.SMTP('localhost', 25) as server:
            server.send_message(msg)
    except Exception as e:
        print(f"Failed to send email: {e}")

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5003)

