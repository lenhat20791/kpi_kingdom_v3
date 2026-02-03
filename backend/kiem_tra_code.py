import os

file_path = r"E:\kpi_kingdom_v3\backend\routes\tower.py"

try:
    print(f"🔍 ĐANG ĐỌC FILE: {file_path}\n")
    
    with open(file_path, "r", encoding="utf-8") as f:
        content = f.read()
        
    # Kiểm tra xem có dòng log đặc biệt tôi bảo bạn thêm không
    if 'print("🔥🔥🔥 CODE MỚI ĐANG CHẠY' in content:
        print("✅ KẾT QUẢ: File ĐÃ CÓ code mới.")
    else:
        print("❌ KẾT QUẢ: File VẪN CHỨA CODE CŨ (Chưa có dòng log Checkpoint).")
        print("👉 Điều này chứng tỏ Editor của bạn chưa lưu thành công vào đường dẫn này.")

    print("\n--- TRÍCH XUẤT 500 KÝ TỰ ĐẦU TIÊN CỦA HÀM complete_floor ---")
    start_idx = content.find("def complete_floor")
    if start_idx != -1:
        print(content[start_idx:start_idx+600])
    else:
        print("❌ Không tìm thấy hàm complete_floor trong file này!")

except Exception as e:
    print(f"❌ Lỗi không đọc được file: {e}")

input("\nBấm Enter để thoát...")