from flask import Flask, render_template
import sqlite3

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

# ---------------------------------------------
# 4) Flask 실행
# ---------------------------------------------
if __name__ == '__main__':
    # debug=True → 코드 바뀌면 서버 자동 재시작 + 에러 상세 확인 가능
    app.run(debug=True)
