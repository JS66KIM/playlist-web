from flask import Flask, render_template, request, redirect, url_for
import sqlite3
import csv
import io


# Flask 앱 생성
# __name__ 은 현재 파일 이름을 의미하며,
# Flask가 이 파일을 기준으로 템플릿 폴더 등을 찾을 수 있게 함.
app = Flask(__name__)

# ---------------------------------------------
# 1) 데이터베이스 연결 함수
# ---------------------------------------------
def get_db_connection():
    """
    SQLite 데이터베이스(playlist.db)에 연결하는 함수.
    - sqlite3.connect() 로 DB 파일을 엶
    - row_factory 를 지정하면 컬럼명을 key 로 사용 가능 (딕셔너리처럼)
    - 매번 연결한 뒤에는 꼭 conn.close() 필요
    """
    conn = sqlite3.connect('database/playlist.db')  # DB 파일 위치
    conn.row_factory = sqlite3.Row  # SELECT 결과를 딕셔너리 형태로 받기 위해 설정
    return conn

# ---------------------------------------------
# 2) 메인 페이지 ("/") 라우트
# ---------------------------------------------
@app.route('/')
def index():
    """
    메인 페이지에서 플레이리스트 목록을 보여주는 함수.
    1. DB 연결
    2. playlists 테이블에서 모든 플레이리스트 가져오기
    3. HTML 파일(index.html) 로 전달
    """
    conn = get_db_connection()  # DB 연결
    cur = conn.cursor()         # SQL 실행 준비

    # 플레이리스트 목록 조회 SQL
    # LEFT JOIN 으로 만든 사람(users.username)도 함께 가져옴
    cur.execute("""
        SELECT p.playlist_id,
               p.title,
               p.description,
               p.created_at,
               u.username
        FROM playlists p
        LEFT JOIN users u ON p.user_id = u.user_id
        ORDER BY p.playlist_id DESC
    """)

    playlists = cur.fetchall()  # 결과 가져오기
    conn.close()                # DB 연결 닫기

    # 템플릿에 playlists 데이터를 넘김
    return render_template('index.html', playlists=playlists)

# ---------------------------------------------
# 3) DB 연결 및 테이블 목록 확인용 라우트
# (개발할 때만 사용, 실제 서비스에는 필요 없음)
# ---------------------------------------------
@app.route('/test-db')
def test_db():
    """
    DB 연결이 잘 되는지, 테이블들이 정상적으로 존재하는지 확인하는 테스트 페이지.
    http://127.0.0.1:5000/test-db 로 확인 가능
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # sqlite_master는 SQLite의 시스템 테이블 (모든 테이블 정보 저장)
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row['name'] for row in cur.fetchall()]

    conn.close()
    return f"현재 데이터베이스에 존재하는 테이블: {tables}"



@app.route('/playlists/new', methods=['GET', 'POST'])
def create_playlist():
    """
    새 플레이리스트를 생성하는 페이지.
    - GET  : 화면에 폼 + 곡 검색/목록을 보여줌
    - POST : 사용자가 작성한 제목/설명 + 선택한 곡들을 DB에 저장
    """

    conn = get_db_connection()
    cur = conn.cursor()

    # ---------- [POST] 폼 제출: 플레이리스트 저장 ----------
    if request.method == 'POST':
        # 폼에서 넘어온 값들 꺼내기
        title = request.form.get('title')
        description = request.form.get('description')

        # 로그인 기능이 아직 없으니까 user_id 는 임시로 1번 사용자라고 가정
        user_id = 1

        # 선택된 곡 ID 들 (체크박스 name="song_ids")
        selected_song_ids = request.form.getlist('song_ids')

        # 플레이리스트 기본 정보 저장
        cur.execute("""
            INSERT INTO playlists (user_id, title, description, created_at)
            VALUES (?, ?, ?, datetime('now'))
        """, (user_id, title, description))
        
        # 방금 INSERT 한 playlist 의 id 가져오기
        playlist_id = cur.lastrowid

        # 선택된 곡들을 playlist_songs 테이블에 넣기
        # track_order 는 1부터 순서대로
        for order, song_id in enumerate(selected_song_ids, start=1):
            cur.execute("""
                INSERT INTO playlist_songs (playlist_id, song_id, track_order)
                VALUES (?, ?, ?)
            """, (playlist_id, song_id, order))

        # 변경사항 저장
        conn.commit()
        conn.close()

        # 저장 후 메인 페이지로 이동
        return redirect(url_for('index'))

    # ---------- [GET] 페이지 처음 접속: 검색 + 곡 목록 ----------
    # 검색어 받기 (?q=검색어)
    search_query = request.args.get('q', '').strip()

    if search_query:
        # 검색어가 있을 때: 제목/아티스트/앨범에 포함되면 보여줌
        cur.execute("""
            SELECT song_id, title, artist, album
            FROM songs
            WHERE title  LIKE ?
               OR artist LIKE ?
               OR album  LIKE ?
            ORDER BY title
        """, (f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'))
    else:
        # 검색어 없으면 전체 곡 목록
        cur.execute("""
            SELECT song_id, title, artist, album
            FROM songs
            ORDER BY title
        """)

    songs = cur.fetchall()
    conn.close()

    # 템플릿에 곡 목록과 검색어 전달
    return render_template('create_playlist.html',
                           songs=songs,
                           search_query=search_query)

# 플레이리스트 상세보기 (노래 목록 포함)
@app.route('/playlists/<int:playlist_id>')
def view_playlist(playlist_id):
    """
    특정 플레이리스트의 상세 정보와 포함된 노래 목록을 보여주는 페이지
    """
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 플레이리스트 기본 정보 가져오기
    cur.execute("""
        SELECT p.playlist_id,
               p.title,
               p.description,
               p.created_at,
               u.username
        FROM playlists p
        LEFT JOIN users u ON p.user_id = u.user_id
        WHERE p.playlist_id = ?
    """, (playlist_id,))
    
    playlist = cur.fetchone()
    
    if not playlist:
        conn.close()
        return "플레이리스트를 찾을 수 없습니다.", 404
    
    # 플레이리스트에 포함된 노래 목록 가져오기
    cur.execute("""
        SELECT s.song_id,
               s.title,
               s.artist,
               s.album,
               ps.track_order
        FROM playlist_songs ps
        JOIN songs s ON ps.song_id = s.song_id
        WHERE ps.playlist_id = ?
        ORDER BY ps.track_order
    """, (playlist_id,))
    
    songs = cur.fetchall()
    conn.close()
    
    return render_template('view_playlist.html', 
                         playlist=playlist, 
                         songs=songs)


# ---------------------------------------------
# 5) 노래 관리 페이지 (songs 테이블 관리)
# ---------------------------------------------
@app.route('/songs', methods=['GET'])
def manage_songs():
    """
    노래 관리 페이지
    - songs 테이블의 전체 목록을 보여줌
    - 노래 개별 삭제 버튼
    - 전체 삭제 버튼
    - 노래 추가 / CSV 업로드 폼은 템플릿에서 제공
    """
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT song_id, title, artist, album
        FROM songs
        ORDER BY song_id DESC
    """)
    songs = cur.fetchall()
    conn.close()

    return render_template('manage_songs.html', songs=songs)


# 개별 노래 추가 (한 곡씩 등록)
@app.route('/songs/add', methods=['POST'])
def add_song():
    """
    한 곡씩 직접 입력해서 songs 테이블에 추가하는 처리.
    manage_songs.html 의 폼에서 POST 요청을 보냄.
    """
    title = request.form.get('title')
    artist = request.form.get('artist')
    album = request.form.get('album')

    if not title:
        # 제목은 필수라고 가정
        return redirect(url_for('manage_songs'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO songs (title, artist, album)
        VALUES (?, ?, ?)
    """, (title, artist, album))
    conn.commit()
    conn.close()

    return redirect(url_for('manage_songs'))


# CSV 파일로 여러 곡 한 번에 추가
@app.route('/songs/upload', methods=['POST'])
def upload_songs_csv():
    """
    CSV 파일 업로드로 여러 곡을 한 번에 추가하는 처리.
    - CSV 형식 예시 (첫 줄은 헤더):
        title,artist,album
        노래제목1,가수1,앨범1
        노래제목2,가수2,앨범2
    """
    file = request.files.get('csv_file')

    # 파일이 없거나 이름이 비어 있으면 그냥 돌아감
    if file is None or file.filename == '':
        return redirect(url_for('manage_songs'))

    # 파일 내용을 텍스트 형태로 읽기 (utf-8 기준)
    try:
        text_stream = io.TextIOWrapper(file.stream, encoding='utf-8')
        reader = csv.DictReader(text_stream)  # 첫 줄을 헤더로 사용 (title, artist, album)
    except Exception:
        # CSV 파싱에 실패하면 그냥 목록 페이지로 돌아가기
        return redirect(url_for('manage_songs'))

    conn = get_db_connection()
    cur = conn.cursor()

    for row in reader:
        title = row.get('title')
        artist = row.get('artist')
        album = row.get('album')

        if title:  # 제목이 있는 행만 저장
            cur.execute("""
                INSERT INTO songs (title, artist, album)
                VALUES (?, ?, ?)
            """, (title, artist, album))

    conn.commit()
    conn.close()

    return redirect(url_for('manage_songs'))


# 개별 노래 삭제
@app.route('/songs/delete/<int:song_id>', methods=['POST'])
def delete_song(song_id):
    """
    특정 song_id 한 곡만 삭제.
    이후 playlist_songs 에서도 해당 곡을 참조하는 행을 지워줘야
    데이터가 깔끔해짐.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # 먼저 playlist_songs 에서 관련 레코드 삭제
    cur.execute("DELETE FROM playlist_songs WHERE song_id = ?", (song_id,))
    # 그 다음 실제 노래 삭제
    cur.execute("DELETE FROM songs WHERE song_id = ?", (song_id,))

    conn.commit()
    conn.close()

    return redirect(url_for('manage_songs'))


# 전체 노래 삭제
@app.route('/songs/delete_all', methods=['POST'])
def delete_all_songs():
    """
    songs 테이블의 모든 노래 삭제.
    - playlist_songs 테이블에서 해당 곡들을 참조하는 행도 함께 삭제.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # 먼저 모든 플레이리스트-노래 관계 삭제
    cur.execute("DELETE FROM playlist_songs")
    # 그리고 모든 노래 삭제
    cur.execute("DELETE FROM songs")

    conn.commit()
    conn.close()

    return redirect(url_for('manage_songs'))

# 플레이리스트 삭제
@app.route('/playlists/delete/<int:playlist_id>', methods=['POST'])
def delete_playlist(playlist_id):
    """
    플레이리스트 삭제 (작성자만 삭제 가능)
    - user_id가 일치하는지 확인
    - playlist_songs 테이블의 관련 데이터도 함께 삭제
    """
    # 현재 로그인한 사용자 (임시로 1번 사용자)
    current_user_id = 1
    
    conn = get_db_connection()
    cur = conn.cursor()
    
    # 플레이리스트의 작성자 확인
    cur.execute("""
        SELECT user_id FROM playlists WHERE playlist_id = ?
    """, (playlist_id,))
    
    result = cur.fetchone()
    
    if not result:
        conn.close()
        return "플레이리스트를 찾을 수 없습니다.", 404
    
    # user_id 확인
    if result['user_id'] != current_user_id:
        conn.close()
        return "삭제 권한이 없습니다. 본인이 만든 플레이리스트만 삭제할 수 있습니다.", 403
    
    # 권한이 있으면 삭제 진행
    # 1. playlist_songs 테이블에서 관련 노래 관계 삭제
    cur.execute("DELETE FROM playlist_songs WHERE playlist_id = ?", (playlist_id,))
    
    # 2. playlists 테이블에서 플레이리스트 삭제
    cur.execute("DELETE FROM playlists WHERE playlist_id = ?", (playlist_id,))
    
    conn.commit()
    conn.close()
    
    return redirect(url_for('index'))

# ---------------------------------------------
#. Flask 실행
# ---------------------------------------------
if __name__ == '__main__':
    # debug=True → 코드 바뀌면 서버 자동 재시작 + 에러 상세 확인 가능
    app.run(debug=True)