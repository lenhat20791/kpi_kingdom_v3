import os
import ast
import re

def inspect_py_file(file_path):
    """Phân tích backend Python: In toàn bộ fields của Model và tham số của hàm."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        try:
            node = ast.parse(f.read(), filename=file_path)
        except SyntaxError:
            return ""
    
    classes_output = []
    functions_output = []

    for body_item in node.body:
        # 1. Trích xuất Model / Schema / Class
        if isinstance(body_item, ast.ClassDef):
            fields = []
            for sub_item in body_item.body:
                # Bắt biến có type annotation (Pydantic / SQLModel / Dataclass)
                if isinstance(sub_item, ast.AnnAssign) and isinstance(sub_item.target, ast.Name):
                    fields.append(sub_item.target.id)
                # Bắt biến gán thông thường (SQLAlchemy Column = ...)
                elif isinstance(sub_item, ast.Assign):
                    for target in sub_item.targets:
                        if isinstance(target, ast.Name):
                            fields.append(target.id)
            
            # Giữ 100% tên cột, gom gọn gàng
            if fields:
                # Loại bỏ duplicate nếu có
                unique_fields = list(dict.fromkeys(fields))
                classes_output.append(f"  📦 Class: {body_item.name} [{', '.join(unique_fields)}]")
            else:
                classes_output.append(f"  📦 Class: {body_item.name}")

        # 2. Trích xuất Hàm và Chữ ký tham số (Arguments)
        elif isinstance(body_item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = []
            for a in body_item.args.args:
                if a.arg != "self" and a.arg != "cls":
                    args.append(a.arg)
            args_str = f"({', '.join(args)})"
            functions_output.append(f"  ⚙️  Hàm: {body_item.name}{args_str}")

    output = []
    if classes_output:
        output.extend(classes_output)
    if functions_output:
        output.extend(functions_output)

    return "\n".join(output)


def inspect_js_logic(code_text):
    """Trích xuất API Endpoints, 100% tên hàm JS và biến trạng thái toàn cục."""
    details = []
    
    # 1. Trích xuất API Endpoints (Fetch & Axios)
    api_calls = set()
    fetch_matches = re.findall(r"fetch\s*\(\s*[`'\"]([^`'\"]+)[`'\"](?:\s*,\s*\{\s*method:\s*[`'\"](\w+)[`'\"])?", code_text, re.IGNORECASE)
    for url, method in fetch_matches:
        method = method.upper() if method else "GET"
        api_calls.add(f"[{method}] {url}")

    axios_matches = re.findall(r"axios\.(get|post|put|delete|patch)\s*\(\s*[`'\"]([^`'\"]+)[`'\"]", code_text, re.IGNORECASE)
    for method, url in axios_matches:
        api_calls.add(f"[{method.upper()}] {url}")

    if api_calls:
        details.append("  🌐 API Endpoints gọi từ client:")
        for api in sorted(api_calls):
            details.append(f"     ➔ {api}")

    # 2. Trích xuất 100% Tên hàm JS (Nén dạng dòng để không tốn line)
    func_names = []
    
    # Regular function: function myFunc(a, b)
    matches_func = re.findall(r"function\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)", code_text)
    for name, args in matches_func:
        args_clean = ", ".join([a.strip() for a in args.split(",") if a.strip()])
        func_names.append(f"{name}({args_clean})")

    # Arrow / Expression: const myFunc = (a, b) =>
    matches_arrow = re.findall(r"(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>", code_text)
    for name, args in matches_arrow:
        args_clean = ", ".join([a.strip() for a in args.split(",") if a.strip()])
        func_names.append(f"{name}({args_clean})")

    if func_names:
        unique_funcs = list(dict.fromkeys(func_names))
        # Format nén: Mỗi dòng chứa 6-8 hàm, giúp 180 hàm chỉ tốn ~20-25 dòng
        details.append(f"  ⚡ JS Logic ({len(unique_funcs)} hàm):")
        chunk_size = 6
        for i in range(0, len(unique_funcs), chunk_size):
            chunk = unique_funcs[i:i + chunk_size]
            details.append(f"     • {', '.join(chunk)}")

    # 3. Trích xuất State / Global Variables
    state_vars = re.findall(r"(?:const|let|var)\s+([a-zA-Z0-9_$]+State|[a-zA-Z0-9_$]+Data|currentUser|gameState|player[A-Z]\w*)\s*=", code_text)
    if state_vars:
        unique_states = list(dict.fromkeys(state_vars))
        details.append(f"  💾 Key States: [{', '.join(unique_states)}]")

    return details


def inspect_html_file(file_path):
    """Phân tích cấu trúc giao diện HTML, Form Inputs và logic JS nội tuyến."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    details = []
    
    # 1. Page Title
    title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
    if title_match:
        details.append(f"  🏷️  Title: {title_match.group(1).strip()}")

    # 2. Key UI Sections (Chỉ lấy modal, tab, view chính để tiết kiệm dòng)
    key_sections = set(re.findall(r'id=["\']((?:tab|view|modal|panel|nav)[-_a-zA-Z0-9]*)["\']', content, re.IGNORECASE))
    if key_sections:
        details.append(f"  🧩 UI Sections: [{', '.join(sorted(key_sections))}]")

    # 3. Form Input Names
    form_inputs = set(re.findall(r'<input\s+[^>]*name=["\'](.*?)["\']|<select\s+[^>]*name=["\'](.*?)["\']', content, re.IGNORECASE))
    flattened_inputs = [name for group in form_inputs for name in group if name]
    if flattened_inputs:
        details.append(f"  📝 Form Fields (name): [{', '.join(sorted(set(flattened_inputs)))}]")

    # 4. Quét toàn bộ mã JS nằm trong thẻ <script>
    scripts_content = " ".join(re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", content, re.DOTALL | re.IGNORECASE))
    if scripts_content.strip():
        js_details = inspect_js_logic(scripts_content)
        details.extend(js_details)

    return "\n".join(details)


def generate_blueprint():
    root_dir = "."
    blueprint_content = [
        "==================================================",
        "===      BẢN ĐỒ KIẾN TRÚC TOÀN CẢNH HỆ THỐNG    ===",
        "=== (Context chuẩn dành riêng cho AI Coding)     ===",
        "=================================================="
    ]

    ignored_folders = {"__pycache__", ".venv", "venv", ".git", "node_modules", "dist", "build", ".idea", ".vscode"}
    target_extensions = {".py", ".html", ".js"}

    total_files = 0

    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ignored_folders]

        valid_files = [
            f for f in files 
            if any(f.endswith(ext) for ext in target_extensions) 
            and f not in {"blueprint.py", "blueprint_generator.py", "code_inspector.py"}
        ]
        
        for file in sorted(valid_files):
            full_path = os.path.join(root, file)
            file_structure = ""

            if file.endswith(".py"):
                file_structure = inspect_py_file(full_path)
            elif file.endswith(".html"):
                file_structure = inspect_html_file(full_path)
            elif file.endswith(".js"):
                with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                    file_structure = "\n".join(inspect_js_logic(f.read()))
            
            if file_structure.strip():
                total_files += 1
                blueprint_content.append(f"\n📄 {os.path.normpath(full_path)}")
                blueprint_content.append(file_structure)

    output_filename = "PROJECT_BLUEPRINT_ACCURATE.txt"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(blueprint_content))
    
    total_lines = len("\n".join(blueprint_content).splitlines())
    print(f"🎉 Đã tạo sơ đồ tại: {output_filename}")
    print(f"📊 Thống kê: Quét {total_files} files | Tổng độ dài: {total_lines} dòng (Cực kỳ an toàn cho bộ nhớ AI).")


if __name__ == "__main__":
    generate_blueprint()