import os
import ast
import re

# ==============================================================================
# 🎯 CẤU HÌNH MỤC TIÊU CẦN SOI (PRESETS)
# Thay đổi PRESET_NAME hoặc chỉnh sửa danh sách bên dưới khi cần soi tính năng khác
# ==============================================================================
PRESETS = {
    "skill_tower": {
        "description": "Chẩn đoán lỗi kích hoạt Kỹ năng trong Tháp",
        "target_files": [
            "database.py",
            "skills.py",
            "tower.py",
            "player_dashboard.html"
        ],
        "target_classes": [
            "Player", "PlayerSkill", "SkillTemplate", "TowerCompleteRequest", "StartCombatRequest"
        ],
        "target_functions": [
            # Backend functions
            "equip_skill", "learn_skill", "get_status", "start_floor_combat", "complete_floor",
            # Frontend JS functions
            "startTowerCombat", "setupCombatUI", "handleTowerAnswer", "playVFX", 
            "selectSkill", "apiAction", "loadSkillTab", "triggerPassiveVFX"
        ],
        "target_keywords": [
            "equipped_skill", "vfx_class", "base_mult", "fallback"
        ]
    }
}

ACTIVE_MODULE = "skill_tower"

# ==============================================================================
# 🔍 CÁC BỘ PHÂN TÍCH CHUYÊN SÂU
# ==============================================================================

def find_file_path(filename, root_dir="."):
    """Tự động tìm đường dẫn thực tế của file trong toàn bộ dự án."""
    for root, dirs, files in os.walk(root_dir):
        if any(ignored in root for ignored in ["__pycache__", ".venv", "venv", ".git", "node_modules"]):
            continue
        if filename in files:
            return os.path.join(root, filename)
    return None


def extract_python_targets(file_path, target_classes, target_functions):
    """Trích xuất nguyên văn code của các Class và Hàm mục tiêu trong file Python."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        source_code = f.read()

    try:
        tree = ast.parse(source_code, filename=file_path)
    except SyntaxError:
        return ["  ❌ Lỗi SyntaxError khi phân tích cú pháp AST."]

    lines = source_code.splitlines()
    extracted = []

    for node in tree.body:
        # Bóc tách Class mục tiêu
        if isinstance(node, ast.ClassDef) and node.name in target_classes:
            start_line = node.lineno - 1
            end_line = getattr(node, "end_lineno", start_line + 20)
            class_code = "\n".join(lines[start_line:end_line])
            extracted.append(f"📦 [MODEL/CLASS] {node.name}:\n```python\n{class_code}\n```")

        # Bóc tách Hàm mục tiêu
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in target_functions:
            start_line = node.lineno - 1
            end_line = getattr(node, "end_lineno", start_line + 30)
            func_code = "\n".join(lines[start_line:end_line])
            extracted.append(f"⚙️ [BACKEND FUNCTION] {node.name}():\n```python\n{func_code}\n```")

    return extracted


def extract_js_functions_from_html(file_path, target_functions):
    """Trích xuất nguyên văn thân hàm JS từ khối <script> trong file HTML hoặc .js."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    extracted = []

    for func_name in target_functions:
        # Bắt hàm dạng: function funcName(...) { ... }
        pattern_func = rf"(function\s+{func_name}\s*\([^)]*\)\s*\{{)"
        match = re.search(pattern_func, content)
        
        # Bắt hàm dạng: const funcName = (...) => { ... }
        if not match:
            pattern_arrow = rf"((?:const|let|var)\s+{func_name}\s*=\s*(?:async\s*)?\([^)]*\)\s*=>\s*\{{)"
            match = re.search(pattern_arrow, content)

        if match:
            start_idx = match.start()
            # Thuật toán đếm ngoặc { } để cắt đúng toàn bộ thân hàm
            brace_count = 0
            found_start = False
            end_idx = start_idx

            for i in range(match.end() - 1, len(content)):
                if content[i] == '{':
                    brace_count += 1
                    found_start = True
                elif content[i] == '}':
                    brace_count -= 1
                
                if found_start and brace_count == 0:
                    end_idx = i + 1
                    break
            
            func_body = content[start_idx:end_idx]
            extracted.append(f"⚡ [FRONTEND JS FUNCTION] {func_name}():\n```javascript\n{func_body}\n```")

    return extracted


# ==============================================================================
# 🚀 HÀM THỰC THI CHÍNH
# ==============================================================================

def run_inspector():
    config = PRESETS.get(ACTIVE_MODULE)
    if not config:
        print(f"❌ Không tìm thấy cấu hình preset: {ACTIVE_MODULE}")
        return

    output = [
        "==================================================",
        f"===   BẢN BÁO CÁO CỤC BỘ: {ACTIVE_MODULE.upper()} ===",
        f"===   Mục đích: {config['description']}",
        "==================================================\n"
    ]

    print(f"🔍 Bắt đầu quét cục bộ chuyên đề: [{ACTIVE_MODULE}]...")

    for filename in config["target_files"]:
        real_path = find_file_path(filename)
        if not real_path:
            output.append(f"\n⚠️ Không tìm thấy file: {filename}")
            continue

        output.append(f"\n==================================================")
        output.append(f"📄 TẬP TIN: {os.path.normpath(real_path)}")
        output.append(f"==================================================")

        if filename.endswith(".py"):
            results = extract_python_targets(real_path, config["target_classes"], config["target_functions"])
            if results:
                output.extend(results)
            else:
                output.append("  (Không tìm thấy Class/Hàm mục tiêu nào trong file này)")

        elif filename.endswith(".html") or filename.endswith(".js"):
            results = extract_js_functions_from_html(real_path, config["target_functions"])
            if results:
                output.extend(results)
            else:
                output.append("  (Không tìm thấy Hàm JS mục tiêu nào trong file này)")

    output_filename = f"INSPECT_{ACTIVE_MODULE.upper()}.txt"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(output))

    print(f"🎉 Đã tạo báo cáo chi tiết tại: {output_filename}")


if __name__ == "__main__":
    run_inspector()