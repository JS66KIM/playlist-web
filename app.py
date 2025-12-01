from flask import Flask, render_template, request, redirect, url_for, session
import sqlite3
import csv
import io

# Flask 앱 생성 및 세션 키 설정
app = Flask(__name__)
app.secret_key = 'your-secret-key-here-change-this-in-production'


# =========================
# DB 연결 함수
# =========================
def get_db_connection():
    conn = sqlite3.connect('database/playlist.db', timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


# =========================
# 최초 실행 시 한 번: 중복 정리 + UNIQUE 인덱스 보강
# =========================
def ensure_guardrails():
    conn = get_db_connection()
    cur = conn.cursor()

    # 1) playlist_songs 중복 레코드 정리 (가장 이른 rowid만 유지)
    cur.execute("""
        DELETE FROM playlist_songs
        WHERE rowid NOT IN (
            SELECT MIN(rowid)
            FROM playlist_songs
            GROUP BY playlist_id, song_id
        )
    """)

    # 2) playlist_id + song_id 조합 중복 금지 인덱스 (없으면 생성)
    cur.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ux_playlist_song
        ON playlist_songs(playlist_id, song_id)
    """)

    conn.commit()
    conn.close()


# =========================
# 공통 헬퍼 함수들
# =========================
def search_songs(cur, query):
    """
    곡 검색(또는 전체 목록) 공통 함수
    """
    query = (query or '').strip()
    if query:
        cur.execute("""
            SELECT song_id, title, artist, album, cover_url
            FROM songs
            WHERE title  LIKE ?
               OR artist LIKE ?
               OR album  LIKE ?
            ORDER BY title
        """, (f'%{query}%', f'%{query}%', f'%{query}%'))
    else:
        cur.execute("""
            SELECT song_id, title, artist, album, cover_url
            FROM songs
            ORDER BY title
        """)
    return cur.fetchall()

def get_songs_by_ids(cur, ids):
    """
    선택된 song_id 리스트로 곡 정보 가져오기
    """
    if not ids:
        return []
    # 중복 제거 & 정렬
    ids = list(dict.fromkeys(ids))
    placeholders = ','.join('?' * len(ids))
    cur.execute(f"""
        SELECT song_id, title, artist, album, cover_url
        FROM songs
        WHERE song_id IN ({placeholders})
    """, ids)
    rows = cur.fetchall()

    # ids 순서대로 정렬 (선택된 순서 유지 느낌)
    row_map = {row['song_id']: row for row in rows}
    ordered = [row_map[sid] for sid in ids if sid in row_map]
    return ordered

def handle_playlist_form(mode='create', playlist_id=None):
    """
    플레이리스트 생성(create) / 수정(edit)을 공통으로 처리하는 함수.
    """
    conn = get_db_connection()
    cur = conn.cursor()

    # 기본값들
    title = ''
    description = ''
    cover_url = ''
    search_query = ''
    selected_song_ids = []

    playlist_owner_id = None

    # ---------- 수정 모드: 기존 데이터 불러오기 ----------
    if mode == 'edit':
        cur.execute("""
            SELECT playlist_id, user_id, title, description, cover_url
            FROM playlists
            WHERE playlist_id = ?
        """, (playlist_id,))
        playlist = cur.fetchone()
        if not playlist:
            conn.close()
            return "플레이리스트를 찾을 수 없습니다.", 404

        playlist_owner_id = playlist['user_id']

        title = playlist['title'] or ''
        description = playlist['description'] or ''
        cover_url = playlist['cover_url'] or ''

        # 기존에 선택된 곡들
        cur.execute("""
            SELECT song_id, track_order
            FROM playlist_songs
            WHERE playlist_id = ?
            ORDER BY track_order
        """, (playlist_id,))
        selected_song_ids = [row['song_id'] for row in cur.fetchall()]

    # ---------- POST 요청 처리 (검색 or 저장) ----------
    if request.method == 'POST':
        action = request.form.get('action')  # 'search' 또는 'save'

        # 폼에서 넘어온 값들
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        cover_url = request.form.get('cover_url', '').strip()
        search_query = request.form.get('q', '').strip()

        # song_ids: 선택된 곡들(위 '선택된 노래' + 아래 검색 테이블 모두 포함)
        raw_ids = request.form.getlist('song_ids')
        try:
            selected_song_ids = [int(sid) for sid in raw_ids]
        except ValueError:
            selected_song_ids = []

        # [FIX] 저장/검색 공통: 선택값 중복 제거(순서 유지)
        selected_song_ids = list(dict.fromkeys(selected_song_ids))

        # ----- 1) 검색 버튼 -----
        if action == 'search':
            songs = search_songs(cur, search_query)
            selected_songs = get_songs_by_ids(cur, selected_song_ids)
            conn.close()
            return render_template(
                'create_playlist.html',
                mode=mode,
                playlist_id=playlist_id,
                title_value=title,
                description_value=description,
                cover_url_value=cover_url,
                search_query=search_query,
                songs=songs,
                selected_song_ids=selected_song_ids,
                selected_songs=selected_songs,
                error=None
            )

        # ----- 2) 저장 버튼 -----
        if action == 'save':
            # 제목/설명 필수
            if not title or not description:
                songs = search_songs(cur, search_query)
                selected_songs = get_songs_by_ids(cur, selected_song_ids)
                conn.close()
                return render_template(
                    'create_playlist.html',
                    mode=mode,
                    playlist_id=playlist_id,
                    title_value=title,
                    description_value=description,
                    cover_url_value=cover_url,
                    search_query=search_query,
                    songs=songs,
                    selected_song_ids=selected_song_ids,
                    selected_songs=selected_songs,
                    error="제목과 설명을 모두 입력해주세요."
                )

            # 로그인 체크
            user_id = session.get('user_id')
            if not user_id:
                conn.close()
                return redirect(url_for('login'))

            # 커버가 비어 있으면 선택된 곡들 중 아무 cover_url 하나 가져오기
            if not cover_url and selected_song_ids:
                placeholders = ','.join('?' * len(selected_song_ids))
                cur.execute(f"""
                    SELECT cover_url
                    FROM songs
                    WHERE song_id IN ({placeholders})
                      AND cover_url IS NOT NULL
                    LIMIT 1
                """, selected_song_ids)
                row = cur.fetchone()
                if row:
                    cover_url = row['cover_url']

            # ---------- 생성 모드 ----------
            if mode == 'create':
                cur.execute("""
                    INSERT INTO playlists (user_id, title, description, created_at, cover_url)
                    VALUES (?, ?, ?, datetime('now'), ?)
                """, (user_id, title, description, cover_url))
                new_playlist_id = cur.lastrowid

                # [FIX] UPSERT로 안전 삽입(중복오면 track_order 갱신)
                for order, song_id in enumerate(selected_song_ids, start=1):
                    cur.execute("""
                        INSERT INTO playlist_songs (playlist_id, song_id, track_order)
                        VALUES (?, ?, ?)
                        ON CONFLICT(playlist_id, song_id)
                        DO UPDATE SET track_order = excluded.track_order
                    """, (new_playlist_id, song_id, order))

            # ---------- 수정 모드 ----------
            else:
                # 권한 체크
                is_admin = session.get('is_admin')
                current_user_id = session.get('user_id')
                if (not is_admin) and (current_user_id != playlist_owner_id):
                    conn.close()
                    return "수정 권한이 없습니다.", 403

                cur.execute("""
                    UPDATE playlists
                    SET title = ?, description = ?, cover_url = ?
                    WHERE playlist_id = ?
                """, (title, description, cover_url, playlist_id))

                # 기존 곡 구성 초기화 후 업서트
                cur.execute("DELETE FROM playlist_songs WHERE playlist_id = ?", (playlist_id,))
                for order, song_id in enumerate(selected_song_ids, start=1):
                    cur.execute("""
                        INSERT INTO playlist_songs (playlist_id, song_id, track_order)
                        VALUES (?, ?, ?)
                        ON CONFLICT(playlist_id, song_id)
                        DO UPDATE SET track_order = excluded.track_order
                    """, (playlist_id, song_id, order))

            conn.commit()
            conn.close()
            return redirect(url_for('index'))

    # ---------- GET 요청: 초기 진입 ----------
    search_query = ''
    songs = search_songs(cur, search_query)
    selected_songs = get_songs_by_ids(cur, selected_song_ids)
    conn.close()

    return render_template(
        'create_playlist.html',
        mode=mode,
        playlist_id=playlist_id,
        title_value=title,
        description_value=description,
        cover_url_value=cover_url,
        search_query=search_query,
        songs=songs,
        selected_song_ids=selected_song_ids,
        selected_songs=selected_songs,
        error=None
    )

# =========================
# 메인 페이지: 플레이리스트 목록
# =========================
@app.route('/')
def index():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT 
            p.playlist_id,
            p.user_id,
            p.title,
            p.description,
            p.created_at,
            p.cover_url,
            u.username,
            COALESCE(
                p.cover_url,
                (
                    SELECT s.cover_url
                    FROM playlist_songs ps
                    JOIN songs s ON ps.song_id = s.song_id
                    WHERE ps.playlist_id = p.playlist_id
                      AND s.cover_url IS NOT NULL
                    LIMIT 1
                )
            ) AS display_cover_url
        FROM playlists p
        LEFT JOIN users u ON p.user_id = u.user_id
        ORDER BY p.playlist_id DESC
    """)
    playlists = cur.fetchall()
    conn.close()
    return render_template('index.html', playlists=playlists)


# =========================
# 로그인 / 회원가입
# =========================
@app.route('/login', methods=['GET', 'POST'])
def login():
    conn = get_db_connection()
    cur = conn.cursor()

    # 로그인 처리
    if request.method == 'POST' and request.form.get('action') == 'login':
        username = request.form.get('username')
        password = request.form.get('password')

        cur.execute("""
            SELECT user_id, username, password
            FROM users
            WHERE username = ?
        """, (username,))
        user = cur.fetchone()

        if user and user['password'] == password:
            session['user_id'] = user['user_id']
            session['username'] = user['username']

            # admin / 123 계정이면 관리자 플래그 설정
            if username == 'admin' and password == '123':
                session['is_admin'] = True
            else:
                session.pop('is_admin', None)

            conn.close()
            return redirect(url_for('index'))
        else:
            conn.close()
            return render_template('login.html',
                                   login_error="아이디 또는 비밀번호가 올바르지 않습니다.")

    # 회원가입 처리
    if request.method == 'POST' and request.form.get('action') == 'register':
        new_username = request.form.get('new_username')
        new_email = request.form.get('new_email')
        new_password = request.form.get('new_password')

        cur.execute("SELECT * FROM users WHERE username = ?", (new_username,))
        exists = cur.fetchone()

        if exists:
            conn.close()
            return render_template('login.html',
                                   register_error="이미 존재하는 아이디입니다.")

        cur.execute("""
            INSERT INTO users (username, email, password)
            VALUES (?, ?, ?)
        """, (new_username, new_email, new_password))
        conn.commit()

        user_id = cur.lastrowid
        session['user_id'] = user_id
        session['username'] = new_username
        # 회원가입으로 만든 계정은 기본적으로 일반 유저
        session.pop('is_admin', None)

        conn.close()
        return redirect(url_for('index'))

    conn.close()
    return render_template('login.html')


# 로그아웃
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('username', None)
    session.pop('is_admin', None)
    return redirect(url_for('index'))


# =========================
# 플레이리스트 생성 / 수정
# =========================

# 새 플레이리스트
@app.route('/playlists/new', methods=['GET', 'POST'])
def create_playlist():
    return handle_playlist_form(mode='create')


# 플레이리스트 수정
@app.route('/playlists/edit/<int:playlist_id>', methods=['GET', 'POST'])
def edit_playlist(playlist_id):
    return handle_playlist_form(mode='edit', playlist_id=playlist_id)


# 플레이리스트 상세 페이지 (수록곡 포함)
@app.route('/playlists/<int:playlist_id>')
def view_playlist(playlist_id):
    conn = get_db_connection()
    cur = conn.cursor()

    # 플레이리스트 정보 (cover_url 포함)
    cur.execute("""
        SELECT p.playlist_id,
               p.user_id,
               p.title,
               p.description,
               p.created_at,
               p.cover_url,
               u.username
        FROM playlists p
        LEFT JOIN users u ON p.user_id = u.user_id
        WHERE p.playlist_id = ?
    """, (playlist_id,))
    playlist = cur.fetchone()

    if not playlist:
        conn.close()
        return "플레이리스트를 찾을 수 없습니다.", 404

    # 플레이리스트에 포함된 곡 목록 (중복 없어야 하지만 정렬 포함)
    cur.execute("""
        SELECT 
            s.song_id,
            s.title,
            s.artist,
            s.album,
            s.cover_url,
            ps.track_order
        FROM playlist_songs ps
        JOIN songs s ON ps.song_id = s.song_id
        WHERE ps.playlist_id = ?
        ORDER BY ps.track_order
    """, (playlist_id,))
    songs = cur.fetchall()

    # 표시용 cover_url (플레이리스트 커버가 없으면 곡 커버 중 하나 사용)
    display_cover_url = playlist['cover_url']
    if not display_cover_url and songs:
        for s in songs:
            if s['cover_url']:
                display_cover_url = s['cover_url']
                break

    conn.close()
    return render_template('view_playlist.html',
                           playlist=playlist,
                           songs=songs,
                           display_cover_url=display_cover_url)


# 플레이리스트 삭제 (본인 또는 관리자만)
@app.route('/playlists/delete/<int:playlist_id>', methods=['POST'])
def delete_playlist(playlist_id):
    is_admin = session.get('is_admin')
    current_user_id = session.get('user_id')

    if not current_user_id and not is_admin:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT user_id FROM playlists WHERE playlist_id = ?", (playlist_id,))
    row = cur.fetchone()

    if not row:
        conn.close()
        return "플레이리스트를 찾을 수 없습니다.", 404

    playlist_owner = row['user_id']

    if not is_admin and playlist_owner != current_user_id:
        conn.close()
        return "삭제 권한이 없습니다.", 403

    cur.execute("DELETE FROM playlist_songs WHERE playlist_id = ?", (playlist_id,))
    cur.execute("DELETE FROM playlists WHERE playlist_id = ?", (playlist_id,))

    conn.commit()
    conn.close()
    return redirect(url_for('index'))


# =========================
# 노래 관리 (관리자 전용)
# =========================
@app.route('/songs', methods=['GET'])
def manage_songs():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    search_query = request.args.get('q', '').strip()

    conn = get_db_connection()
    cur = conn.cursor()

    if search_query:
        cur.execute("""
            SELECT song_id, title, artist, album, cover_url
            FROM songs
            WHERE title  LIKE ?
               OR artist LIKE ?
               OR album  LIKE ?
            ORDER BY song_id DESC
        """, (f'%{search_query}%', f'%{search_query}%', f'%{search_query}%'))
    else:
        cur.execute("""
            SELECT song_id, title, artist, album, cover_url
            FROM songs
            ORDER BY song_id DESC
        """)

    songs = cur.fetchall()
    conn.close()

    return render_template('manage_songs.html',
                           songs=songs,
                           search_query=search_query)


# 노래 한 곡 추가 (관리자 전용)
@app.route('/songs/add', methods=['POST'])
def add_song():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    title = request.form.get('title')
    artist = request.form.get('artist')
    album = request.form.get('album')
    cover_url = request.form.get('cover_url')

    if not title:
        return redirect(url_for('manage_songs'))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO songs (title, artist, album, cover_url)
        VALUES (?, ?, ?, ?)
    """, (title, artist, album, cover_url))
    conn.commit()
    conn.close()

    return redirect(url_for('manage_songs'))


# CSV로 여러 곡 업로드 (관리자 전용)
@app.route('/songs/upload', methods=['POST'])
def upload_songs_csv():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    file = request.files.get('csv_file')
    if file is None or file.filename == '':
        return redirect(url_for('manage_songs'))

    try:
        text_stream = io.TextIOWrapper(file.stream, encoding='utf-8')
        reader = csv.DictReader(text_stream)
    except Exception:
        return redirect(url_for('manage_songs'))

    conn = get_db_connection()
    cur = conn.cursor()

    for row in reader:
        title = row.get('title')
        artist = row.get('artist')
        album = row.get('album')
        cover_url = row.get('cover_url')

        if title:
            cur.execute("""
                INSERT INTO songs (title, artist, album, cover_url)
                VALUES (?, ?, ?, ?)
            """, (title, artist, album, cover_url))

    conn.commit()
    conn.close()
    return redirect(url_for('manage_songs'))


@app.route('/songs/bulk', methods=['POST'])
def songs_bulk_action():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    # 어떤 버튼이 눌렸는지 구분
    action = request.form.get('action')
    update_id = request.form.get('update_id')

    # 1) 선택 항목 삭제
    if action == 'delete_selected':
        selected_ids = request.form.getlist('selected_ids')
        if selected_ids:
            for sid in selected_ids:
                cur.execute("DELETE FROM playlist_songs WHERE song_id = ?", (sid,))
                cur.execute("DELETE FROM songs WHERE song_id = ?", (sid,))
            conn.commit()
        conn.close()
        return redirect(url_for('manage_songs'))

    # 2) 특정 곡 수정
    if update_id:
        song_id = update_id

        title = request.form.get(f'title_{song_id}')
        artist = request.form.get(f'artist_{song_id}')
        album = request.form.get(f'album_{song_id}')
        cover_url = request.form.get(f'cover_url_{song_id}')

        cur.execute("""
            UPDATE songs
            SET title = ?, artist = ?, album = ?, cover_url = ?
            WHERE song_id = ?
        """, (title, artist, album, cover_url, song_id))

        conn.commit()
        conn.close()
        return redirect(url_for('manage_songs'))

    conn.close()
    return redirect(url_for('manage_songs'))


@app.route('/songs/update/<int:song_id>', methods=['POST'])
def update_song(song_id):
    """
    노래 정보 수정 (관리자 전용)
    """
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    title = request.form.get('title')
    artist = request.form.get('artist')
    album = request.form.get('album')
    cover_url = request.form.get('cover_url')

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        UPDATE songs
        SET title = ?, artist = ?, album = ?, cover_url = ?
        WHERE song_id = ?
    """, (title, artist, album, cover_url, song_id))

    conn.commit()
    conn.close()

    return redirect(url_for('manage_songs'))


# 노래 한 곡 삭제 (관리자 전용)
@app.route('/songs/delete/<int:song_id>', methods=['POST'])
def delete_song(song_id):
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM playlist_songs WHERE song_id = ?", (song_id,))
    cur.execute("DELETE FROM songs WHERE song_id = ?", (song_id,))

    conn.commit()
    conn.close()
    return redirect(url_for('manage_songs'))


# 모든 노래 삭제 (관리자 전용)
@app.route('/songs/delete_all', methods=['POST'])
def delete_all_songs():
    if not session.get('is_admin'):
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("DELETE FROM playlist_songs")
    cur.execute("DELETE FROM songs")

    conn.commit()
    conn.close()
    return redirect(url_for('manage_songs'))


# DB 테이블 목록 확인 (개발용)
@app.route('/test-db')
def test_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = [row['name'] for row in cur.fetchall()]
    conn.close()
    return f"현재 데이터베이스에 존재하는 테이블: {tables}"


if __name__ == '__main__':
    # [FIX] 서버 시작 시 중복 정리 & UNIQUE 인덱스 보강
    ensure_guardrails()
    app.run(debug=True)
