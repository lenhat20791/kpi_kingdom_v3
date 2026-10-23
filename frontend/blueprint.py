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
        # 1. Model / Schema / Class
        if isinstance(body_item, ast.ClassDef):
            fields = []
            for sub_item in body_item.body:
                if isinstance(sub_item, ast.AnnAssign) and isinstance(sub_item.target, ast.Name):
                    fields.append(sub_item.target.id)
                elif isinstance(sub_item, ast.Assign):
                    for target in sub_item.targets:
                        if isinstance(target, ast.Name):
                            fields.append(target.id)
            
            if fields:
                unique_fields = list(dict.fromkeys(fields))
                classes_output.append(f"  📦 Class: {body_item.name} [{', '.join(unique_fields)}]")
            else:
                classes_output.append(f"  📦 Class: {body_item.name}")

        # 2. Hàm và tham số
        elif isinstance(body_item, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in body_item.args.args if a.arg not in ("self", "cls")]
            args_str = f"({', '.join(args)})"
            functions_output.append(f"  ⚙️  Hàm: {body_item.name}{args_str}")

    output = []
    if classes_output:
        output.extend(classes_output)
    if functions_output:
        output.extend(functions_output)

    return "\n".join(output)


def inspect_js_logic(code_text):
    """Trích xuất API Endpoints, tên hàm JS và biến trạng thái."""
    details = []
    
    # 1. API Endpoints
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

    # 2. Tên hàm JS
    func_names = []
    matches_func = re.findall(r"function\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)", code_text)
    for name, args in matches_func:
        args_clean = ", ".join([a.strip() for a in args.split(",") if a.strip()])
        func_names.append(f"{name}({args_clean})")

    matches_arrow = re.findall(r"(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>", code_text)
    for name, args in matches_arrow:
        args_clean = ", ".join([a.strip() for a in args.split(",") if a.strip()])
        func_names.append(f"{name}({args_clean})")

    if func_names:
        unique_funcs = list(dict.fromkeys(func_names))
        details.append(f"  ⚡ JS Logic ({len(unique_funcs)} hàm):")
        chunk_size = 6
        for i in range(0, len(unique_funcs), chunk_size):
            chunk = unique_funcs[i:i + chunk_size]
            details.append(f"     • {', '.join(chunk)}")

    # 3. State / Global Variables
    state_vars = re.findall(r"(?:const|let|var)\s+([a-zA-Z0-9_$]+State|[a-zA-Z0-9_$]+Data|currentUser|gameState|player[A-Z]\w*)\s*=", code_text)
    if state_vars:
        unique_states = list(dict.fromkeys(state_vars))
        details.append(f"  💾 Key States: [{', '.join(unique_states)}]")

    return details


def inspect_html_file(file_path):
    """Phân tích HTML: Title, UI Sections, Form Names, Scripts inline."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    details = []
    
    title_match = re.search(r"<title>(.*?)</title>", content, re.IGNORECASE)
    if title_match:
        details.append(f"  🏷️  Title: {title_match.group(1).strip()}")

    key_sections = set(re.findall(r'id=["\']((?:tab|view|modal|panel|nav)[-_a-zA-Z0-9]*)["\']', content, re.IGNORECASE))
    if key_sections:
        details.append(f"  🧩 UI Sections: [{', '.join(sorted(key_sections))}]")

    form_inputs = set(re.findall(r'<input\s+[^>]*name=["\'](.*?)["\']|<select\s+[^>]*name=["\'](.*?)["\']', content, re.IGNORECASE))
    flattened_inputs = [name for group in form_inputs for name in group if name]
    if flattened_inputs:
        details.append(f"  📝 Form Fields (name): [{', '.join(sorted(set(flattened_inputs)))}]")

    scripts_content = " ".join(re.findall(r"<script(?:\s+[^>]*)?>(.*?)</script>", content, re.DOTALL | re.IGNORECASE))
    if scripts_content.strip():
        js_details = inspect_js_logic(scripts_content)
        details.extend(js_details)

    return "\n".join(details)


def inspect_css_file(file_path):
    """Phân tích CSS: CSS Variables (:root), Animations và UI Custom Classes."""
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Bỏ comment CSS để tránh bắt nhầm
    clean_css = re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)
    details = []

    # 1. Trích xuất CSS Variables trong :root (Theme colors, global size)
    root_match = re.search(r":root\s*\{([^}]+)\}", clean_css)
    if root_match:
        vars_found = re.findall(r"(--[a-zA-Z0-9-_]+)\s*:\s*([^;]+);", root_match.group(1))
        if vars_found:
            css_vars = [f"{v[0]}: {v[1].strip()}" for v in vars_found]
            preview = ", ".join(css_vars[:6]) + (f" ... (+{len(css_vars)-6} vars)" if len(css_vars) > 6 else "")
            details.append(f"  🎨 Theme Variables: [{preview}]")

    # 2. Trích xuất Keyframe Animations
    animations = re.findall(r"@keyframes\s+([a-zA-Z0-9-_]+)", clean_css)
    if animations:
        details.append(f"  ✨ Animations: [{', '.join(sorted(set(animations)))}]")

    # 3. Trích xuất Custom Classes chính (Loại bỏ các pseudo-class như :hover, :active)
    raw_classes = re.findall(r"\.([a-zA-Z0-9-_]+)(?:[:\s{,.])", clean_css)
    # Lọc bỏ class quá ngắn hoặc số
    valid_classes = [c for c in set(raw_classes) if len(c) > 2 and not c.isdigit()]
    
    if valid_classes:
        valid_classes.sort()
        chunk_size = 8
        details.append(f"  🎨 UI Classes ({len(valid_classes)} classes):")
        for i in range(0, len(valid_classes), chunk_size):
            chunk = valid_classes[i:i + chunk_size]
            details.append(f"     • {', '.join(chunk)}")

    return "\n".join(details)


def generate_blueprint():
    root_dir = "."
    blueprint_content = [
        "==================================================",
        "===      BẢN ĐỒ KIẾN TRÚC TOÀN CẢNH HỆ THỐNG    ===",
        "=== (Context chuẩn dành riêng cho AI Coding)     ===",
        "=================================================="
    ]

    # Các thư mục cần bỏ qua
    ignored_folders = {"__pycache__", ".venv", "venv", ".git", "node_modules", "dist", "build", ".idea", ".vscode"}
    # Hỗ trợ cả Python, HTML, JS và CSS
    target_extensions = {".py", ".html", ".js", ".css"}

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
            elif file.endswith(".css"):
                file_structure = inspect_css_file(full_path)
            
            if file_structure.strip():
                total_files += 1
                blueprint_content.append(f"\n📄 {os.path.normpath(full_path)}")
                blueprint_content.append(file_structure)

    output_filename = "PROJECT_BLUEPRINT_ACCURATE.txt"
    with open(output_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(blueprint_content))
    
    total_lines = len("\n".join(blueprint_content).splitlines())
    print(f"🎉 Đã quét toàn bộ hệ thống (kèm thư mục CSS) tại: {output_filename}")
    print(f"📊 Thống kê: Quét {total_files} files | Tổng độ dài: {total_lines} dòng.")


if __name__ == "__main__":
    generate_blueprint()