import pandas as pd
from sqlmodel import Session, select
import sys
import os
from auth import get_password_hash

# Thêm thư mục backend vào hệ thống để có thể import database.py
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Player, engine, generate_username

def import_players_from_excel(file_path: str, default_password: str = "123456", grade: int = 6):
    """
    Đọc file Excel và nạp học sinh vào Database.
    File Excel cần có ít nhất một cột mang tên 'Họ và tên'.
    """
    try:
        # 1. Đọc file Excel
        df = pd.read_excel(file_path)
        
        # 2. Tìm cột 'Họ và tên' (không phân biệt hoa thường)
        target_col = None
        for col in df.columns:
            if "họ và tên" in str(col).lower():
                target_col = col
                break
        
        if target_col is None:
            return {"success": False, "message": "Không tìm thấy cột 'Họ và tên' trong file!"}

        players_added = 0
        with Session(engine) as session:
            for index, row in df.iterrows():
                full_name = str(row[target_col]).strip()
                if not full_name or full_name == "nan":
                    continue
                
                # Tạo username từ tên có dấu
                base_username = generate_username(full_name)
                unique_username = base_username
                
                # 3. Xử lý trùng lặp (nếu trùng thì thêm số _2, _3...)
                counter = 2
                while True:
                    statement = select(Player).where(Player.username == unique_username)
                    existing_player = session.exec(statement).first()
                    if not existing_player:
                        break
                    unique_username = f"{base_username}_{counter}"
                    counter += 1
                
                # 4. Tạo đối tượng Player mới
                new_player = Player(
                    username=unique_username,
                    full_name=full_name,
                    password_hash=get_password_hash(default_password),
                    role="player",
                    grade=grade,
                    kpi=0,    
                    tri_thuc=0,
                    chien_tich=0,
                    vinh_du=0,
                    hp=100,
                    hp_max=100, 
                    level=1,         
                    exp=0,
                    skill_points=0,
                    stats_json="{}",
                    titles_json="[]"
                )
                session.add(new_player)
                players_added += 1
            
            session.commit()
            
        return {"success": True, "message": f"Đã nạp thành công {players_added} học sĩ vào vương quốc!"}

    except Exception as e:
        # Trả về lỗi chi tiết để dễ sửa
        return {"success": False, "message": f"Lỗi hệ thống: {str(e)}"}
if __name__ == "__main__":
    print("🚀 Đang khởi động quá trình nạp dữ liệu...")
    
    # Lưu kết quả vào biến result
    result = import_players_from_excel("danh sach lop.xlsx") 
    
    # In ra tin nhắn thông báo (Nó sẽ báo "Đã nạp thành công X học sĩ")
    print(f"📢 Thông báo: {result['message']}")
    print("✅ Hoàn tất!")
