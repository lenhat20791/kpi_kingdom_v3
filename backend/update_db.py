from sqlmodel import create_engine, text
import os

# --- SỬA DÒNG NÀY ---
# Thêm os.path.dirname(...) một lần nữa để lùi ra thư mục gốc (E:\kpi_kingdom_v3)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) 
# --------------------

DB_PATH = os.path.join(BASE_DIR, "data", "game.db")
sqlite_url = f"sqlite:///{DB_PATH}"

engine = create_engine(sqlite_url)

def migrate_db():
    print(f"🔄 Đang kết nối tới: {DB_PATH}")
    # ... (Phần dưới giữ nguyên)
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE player ADD COLUMN revive_at DATETIME"))
            print("✅ Đã thêm cột 'revive_at' thành công!")
        except Exception as e:
            if "duplicate column name" in str(e):
                print("⚠️ Cột 'revive_at' đã tồn tại, không cần thêm nữa.")
            else:
                print(f"❌ Lỗi: {e}")

if __name__ == "__main__":
    migrate_db()