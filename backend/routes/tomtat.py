import os
import re
import ast

def summarize_python(file_path):
    output_lines = [f"=== TÓM TẮT FILE PYTHON: {os.path.basename(file_path)} ==="]
    
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    try:
        tree = ast.parse(content)
        
        # 1. Thống kê biến toàn cục
        global_vars = []
        for node in tree.body:
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        global_vars.append(target.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                global_vars.append(node.target.id)
        if global_vars:
            output_lines.append(f"\n[Biến Toàn Cục ({len(global_vars)})]:\n  " + ", ".join(global_vars))

        # 2. Thống kê Class và các Fields/Methods bên trong
        classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
        if classes:
            output_lines.append(f"\n[Classes / Data Models ({len(classes)})]:")
            for cls in classes:
                fields = []
                methods = []
                for item in cls.body:
                    if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                        fields.append(item.target.id)
                    elif isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append(item.name)
                
                info = f"  - Class {cls.name}"
                if fields:
                    info += f" | Fields: [{', '.join(fields)}]"
                if methods:
                    info += f" | Methods: [{', '.join(methods)}]"
                output_lines.append(info)

        # 3. Thống kê Functions và Endpoints API
        functions = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if functions:
            output_lines.append(f"\n[Hàm & API Endpoints ({len(functions)})]:")
            for fn in functions:
                decorators = []
                for dec in fn.decorator_list:
                    if isinstance(dec, ast.Call) and hasattr(dec.func, "attr"):
                        decorators.append(f"@{dec.func.attr}")
                    elif isinstance(dec, ast.Name):
                        decorators.append(f"@{dec.id}")
                
                args = [a.arg for a in fn.args.args]
                dec_str = f" [{' '.join(decorators)}]" if decorators else ""
                output_lines.append(f"  - def {fn.name}({', '.join(args)}){dec_str}")

    except Exception as e:
        output_lines.append(f"\n[Lỗi phân tích AST Python: {e}]")
        
    return "\n".join(output_lines)


def summarize_html(file_path):
    output_lines = [f"=== TÓM TẮT FILE HTML: {os.path.basename(file_path)} ==="]
    
    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 1. Trích xuất tất cả ID quan trọng
    ids = sorted(list(set(re.findall(r'id=["\']([^"\']+)["\']', content))))
    if ids:
        output_lines.append(f"\n[Danh Sách DOM IDs ({len(ids)})]:\n  " + ", ".join(ids))

    # 2. Trích xuất các Modals, Screens, Tabs chính
    modals = re.findall(r'id=["\']([^"\']*(?:modal|screen|tab|popup|view)[^"\']*)["\']', content, re.IGNORECASE)
    modals = sorted(list(set(modals)))
    if modals:
        output_lines.append(f"\n[Screens / Modals / Tabs ({len(modals)})]:\n  " + ", ".join(modals))

    # 3. Trích xuất các đường dẫn Fetch/API Endpoint trong JS
    api_calls = re.findall(r'fetch\(["\'`](/api/[^"\'`\?]+|/admin/[^"\'`\?]+|/users/[^"\'`\?]+)', content)
    api_calls = sorted(list(set(api_calls)))
    if api_calls:
        output_lines.append(f"\n[Các API Endpoints Đang Gọi ({len(api_calls)})]:")
        for api in api_calls:
            output_lines.append(f"  - {api}")

    # 4. Trích xuất các biến toàn cục trong khối <script>
    js_vars = re.findall(r'(?:let|var|const)\s+([a-zA-Z0-9_$]+)\s*=', content)
    js_vars = sorted(list(set(js_vars)))
    if js_vars:
        output_lines.append(f"\n[Biến JS Toàn Cục ({len(js_vars)})]:\n  " + ", ".join(js_vars))

    # 5. Trích xuất các hàm Javascript
    js_funcs = re.findall(r'function\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)|(?:async\s+)?function\s+([a-zA-Z0-9_$]+)', content)
    func_list = []
    for f in js_funcs:
        name = f[0] if f[0] else f[2]
        params = f[1] if f[1] else ""
        if name:
            func_list.append(f"{name}({params})")
    
    func_list = sorted(list(set(func_list)))
    if func_list:
        output_lines.append(f"\n[Hàm JavaScript ({len(func_list)})]:")
        for fn in func_list:
            output_lines.append(f"  - {fn}")

    return "\n".join(output_lines)


def main():
    print("=" * 50)
    print("TOOL TÓM TẮT CẤU TRÚC FILE PYTHON / HTML")
    print("=" * 50)
    
    file_name = input("Nhập tên file cần quét (ví dụ: player_dashboard.html hoặc main.py): ").strip()
    
    if not os.path.exists(file_name):
        print(f"❌ Không tìm thấy file '{file_name}' trong thư mục hiện tại!")
        return

    ext = os.path.splitext(file_name)[1].lower()
    
    if ext == ".py":
        summary = summarize_python(file_name)
    elif ext in [".html", ".htm"]:
        summary = summarize_html(file_name)
    else:
        print(f"❌ Tool chỉ hỗ trợ file .py hoặc .html/.htm (file của bạn là {ext})")
        return

    output_file = f"TOM_TAT_{os.path.splitext(file_name)[0]}.txt"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(summary)

    print(f"\n✅ Đã quét xong! Kết quả đã được ghi vào file: {output_file}")
    print("Bạn có thể mở file này để kiểm tra hoặc gửi nội dung cho tôi.")

if __name__ == "__main__":
    main()