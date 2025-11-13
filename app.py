from flask import Flask, render_template
import sqlite3

app = Flask(__name__)

# db connection
def get_db_connection():
    conn = sqlite3.connect('database/playlist.db')
    conn.row_factory = sqlite3.Row  # dict처럼 사용 가능하게
    return conn


@app.route('/')
def index():
    return render_template('index.html')

if __name__ == "__main__":
    app.run(debug=True)
