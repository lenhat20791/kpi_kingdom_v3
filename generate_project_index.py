from pathlib import Path
import ast
import re
from datetime import datetime


# ============================================================
# CẤU HÌNH
# ============================================================

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "PROJECT_INDEX.txt"

# Các thư mục không cần quét
IGNORE_DIRS = {
    ".git",
    ".idea",
    ".vscode",
    "__pycache__",
    ".pytest_cache",
    "node_modules",
    "venv",
    ".venv",
    "env",
    ".env",
    "dist",
    "build",
}

# Các file không cần quét
IGNORE_FILES = {
    "PROJECT_INDEX.txt",
    "generate_project_index.py",
}

SUPPORTED_EXTENSIONS = {
    ".py",
    ".sql",
    ".html",
    ".htm",
    ".js",
    ".ts",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
}


# ============================================================
# HÀM HỖ TRỢ
# ============================================================

def relative_path(path):
    return path.relative_to(ROOT).as_posix()


def safe_read(path):
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def clean_docstring(text):
    if not text:
        return ""

    text = " ".join(text.strip().split())

    if len(text) > 120:
        text = text[:117] + "..."

    return text


def section(title):
    return [
        "",
        "=" * 70,
        title,
        "=" * 70,
    ]


# ============================================================
# QUÉT CẤU TRÚC FILE
# ============================================================

def collect_files():
    files = []

    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue

        if path.name in IGNORE_FILES:
            continue

        if any(part in IGNORE_DIRS for part in path.parts):
            continue

        if path.suffix.lower() in SUPPORTED_EXTENSIONS:
            files.append(path)

    return sorted(files)


# ============================================================
# PHÂN TÍCH PYTHON
# ============================================================

def analyze_python(path):
    result = {
        "functions": [],
        "classes": [],
        "variables": [],
        "imports": [],
    }

    source = safe_read(path)

    if not source.strip():
        return result

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return result

    for node in ast.walk(tree):

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = []

            for arg in node.args.args:
                args.append(arg.arg)

            doc = clean_docstring(ast.get_docstring(node))

            result["functions"].append({
                "name": node.name,
                "args": ", ".join(args),
                "line": node.lineno,
                "doc": doc,
            })

        elif isinstance(node, ast.ClassDef):
            result["classes"].append({
                "name": node.name,
                "line": node.lineno,
            })

        elif isinstance(node, ast.Assign):
            for target in node.targets:

                if isinstance(target, ast.Name):
                    result["variables"].append({
                        "name": target.id,
                        "line": node.lineno,
                    })

        elif isinstance(node, ast.Import):
            for alias in node.names:
                result["imports"].append(alias.name)

        elif isinstance(node, ast.ImportFrom):
            if node.module:
                result["imports"].append(node.module)

    return result


# ============================================================
# PHÂN TÍCH SQL
# ============================================================

def analyze_sql(path):
    source = safe_read(path)

    tables = []
    columns = {}

    # Tìm CREATE TABLE
    table_pattern = re.compile(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
        r"[`\"\[]?(\w+)[`\"\]]?"
        r"\s*\((.*?)\)",
        re.IGNORECASE | re.DOTALL,
    )

    for match in table_pattern.finditer(source):
        table_name = match.group(1)
        body = match.group(2)

        tables.append(table_name)

        cols = []

        for line in body.splitlines():
            line = line.strip().rstrip(",")

            if not line:
                continue

            if re.match(
                r"^(PRIMARY|FOREIGN|UNIQUE|CHECK|CONSTRAINT)",
                line,
                re.IGNORECASE,
            ):
                continue

            parts = re.split(r"\s+", line)

            if len(parts) >= 2:
                column = parts[0].strip("`\"[]")
                data_type = parts[1]

                cols.append(f"{column}: {data_type}")

        columns[table_name] = cols

    return tables, columns


# ============================================================
# TÌM API / ĐƯỜNG DẪN MẠNG
# ============================================================

def find_api_routes(path):
    source = safe_read(path)

    routes = []

    # FastAPI
    fastapi_pattern = re.compile(
        r'@\w+\.(get|post|put|patch|delete|options|head)\(\s*[\'"]([^\'"]+)',
        re.IGNORECASE,
    )

    for match in fastapi_pattern.finditer(source):
        routes.append(
            f"{match.group(1).upper()} {match.group(2)}"
        )

    # Flask
    flask_pattern = re.compile(
        r'@\w+\.route\(\s*[\'"]([^\'"]+)[\'"]'
        r'(?:.*?methods\s*=\s*\[([^\]]+)\])?',
        re.IGNORECASE | re.DOTALL,
    )

    for match in flask_pattern.finditer(source):
        path_name = match.group(1)
        methods = match.group(2)

        if methods:
            methods = re.sub(r"[\'\"\s]", "", methods)
            methods = methods.split(",")

            for method in methods:
                routes.append(f"{method.upper()} {path_name}")
        else:
            routes.append(f"GET/POST {path_name}")

    return routes


# ============================================================
# TÌM BIẾN JS
# ============================================================

def find_javascript_variables(path):
    source = safe_read(path)

    pattern = re.compile(
        r"\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)"
    )

    return sorted(set(pattern.findall(source)))


# ============================================================
# TÌM ID HTML
# ============================================================

def find_html_elements(path):
    source = safe_read(path)

    ids = re.findall(
        r'\bid\s*=\s*["\']([^"\']+)["\']',
        source,
        re.IGNORECASE,
    )

    buttons = re.findall(
        r"<button[^>]*>(.*?)</button>",
        source,
        re.IGNORECASE | re.DOTALL,
    )

    cleaned_buttons = []

    for button in buttons:
        text = re.sub(r"<[^>]+>", "", button)
        text = " ".join(text.split())

        if text:
            cleaned_buttons.append(text[:100])

    return sorted(set(ids)), sorted(set(cleaned_buttons))


# ============================================================
# TÌM QUAN HỆ KHÓA NGOẠI ĐƠN GIẢN
# ============================================================

def find_foreign_keys(path):
    source = safe_read(path)

    pattern = re.compile(
        r"FOREIGN\s+KEY\s*\(\s*(\w+)\s*\)"
        r"\s*REFERENCES\s+(\w+)\s*\(\s*(\w+)\s*\)",
        re.IGNORECASE,
    )

    relationships = []

    for match in pattern.finditer(source):
        relationships.append(
            f"{match.group(1)} -> {match.group(2)}.{match.group(3)}"
        )

    return relationships


# ============================================================
# MAIN
# ============================================================

def main():

    files = collect_files()

    python_data = []
    sql_data = []
    api_routes = []
    js_variables = []
    html_data = []
    relationships = []

    for path in files:

        ext = path.suffix.lower()

        if ext == ".py":

            data = analyze_python(path)

            python_data.append({
                "path": relative_path(path),
                "data": data,
            })

            api_routes.extend(
                (relative_path(path), route)
                for route in find_api_routes(path)
            )

        elif ext == ".sql":

            tables, columns = analyze_sql(path)

            sql_data.append({
                "path": relative_path(path),
                "tables": tables,
                "columns": columns,
            })

            relationships.extend(
                (relative_path(path), relation)
                for relation in find_foreign_keys(path)
            )

        elif ext in {".js", ".ts"}:

            variables = find_javascript_variables(path)

            if variables:
                js_variables.append(
                    (relative_path(path), variables)
                )

        elif ext in {".html", ".htm"}:

            ids, buttons = find_html_elements(path)

            if ids or buttons:
                html_data.append({
                    "path": relative_path(path),
                    "ids": ids,
                    "buttons": buttons,
                })

    lines = []

    # --------------------------------------------------------
    # HEADER
    # --------------------------------------------------------

    lines.append("PROJECT INDEX")
    lines.append("BẢN MỤC LỤC RÚT GỌN CỦA DỰ ÁN")
    lines.append("")
    lines.append(f"Thư mục dự án: {ROOT}")
    lines.append(
        f"Thời điểm tạo: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    lines.append(f"Tổng số file được quét: {len(files)}")

    # --------------------------------------------------------
    # 1. CẤU TRÚC FILE
    # --------------------------------------------------------

    lines.extend(section("1. CẤU TRÚC FILE"))

    for path in files:
        lines.append(f"- {relative_path(path)}")

    # --------------------------------------------------------
    # 2. PYTHON
    # --------------------------------------------------------

    lines.extend(section("2. HÀM VÀ LỚP PYTHON"))

    for item in python_data:

        path = item["path"]
        data = item["data"]

        if not (
            data["functions"]
            or data["classes"]
            or data["variables"]
        ):
            continue

        lines.append(f"\n[{path}]")

        for cls in data["classes"]:
            lines.append(
                f"  CLASS: {cls['name']} "
                f"(dòng {cls['line']})"
            )

        for func in data["functions"]:

            text = (
                f"  FUNCTION: {func['name']}"
                f"({func['args']})"
                f" (dòng {func['line']})"
            )

            if func["doc"]:
                text += f" - {func['doc']}"

            lines.append(text)

        for var in data["variables"]:
            lines.append(
                f"  VARIABLE: {var['name']} "
                f"(dòng {var['line']})"
            )

    # --------------------------------------------------------
    # 3. DATABASE
    # --------------------------------------------------------

    lines.extend(section("3. BẢNG DỮ LIỆU"))

    found_table = False

    for item in sql_data:

        if not item["tables"]:
            continue

        found_table = True

        lines.append(f"\n[{item['path']}]")

        for table in item["tables"]:

            lines.append(f"  TABLE: {table}")

            for column in item["columns"].get(table, []):
                lines.append(f"    - {column}")

    if not found_table:
        lines.append("Không phát hiện CREATE TABLE trong file SQL.")

    # --------------------------------------------------------
    # 4. QUAN HỆ DỮ LIỆU
    # --------------------------------------------------------

    lines.extend(section("4. QUAN HỆ DỮ LIỆU"))

    if relationships:

        for path, relation in relationships:
            lines.append(
                f"- {relation} [{path}]"
            )

    else:
        lines.append(
            "Không phát hiện quan hệ FOREIGN KEY rõ ràng."
        )

    # --------------------------------------------------------
    # 5. API
    # --------------------------------------------------------

    lines.extend(section("5. ĐƯỜNG DẪN API / MẠNG"))

    if api_routes:

        seen = set()

        for path, route in api_routes:

            key = (path, route)

            if key in seen:
                continue

            seen.add(key)

            lines.append(
                f"- {route} [{path}]"
            )

    else:
        lines.append(
            "Không phát hiện đường dẫn API tự động."
        )

    # --------------------------------------------------------
    # 6. JAVASCRIPT
    # --------------------------------------------------------

    lines.extend(section("6. BIẾN JAVASCRIPT"))

    for path, variables in js_variables:

        lines.append(f"\n[{path}]")

        for variable in variables:
            lines.append(f"  VARIABLE: {variable}")

    # --------------------------------------------------------
    # 7. HTML
    # --------------------------------------------------------

    lines.extend(section("7. THÀNH PHẦN GIAO DIỆN"))

    for item in html_data:

        lines.append(f"\n[{item['path']}]")

        for element_id in item["ids"]:
            lines.append(
                f"  HTML ID: {element_id}"
            )

        for button in item["buttons"]:
            lines.append(
                f"  BUTTON: {button}"
            )

    # --------------------------------------------------------
    # 8. HƯỚNG DẪN CHO AI
    # --------------------------------------------------------

    lines.extend(section("8. QUY TẮC SỬ DỤNG FILE NÀY CHO AI"))

    lines.extend([
        "- Đọc PROJECT_INDEX.txt trước khi sửa hoặc thêm chức năng.",
        "- Không tự ý đổi tên bảng dữ liệu đã tồn tại.",
        "- Không tự ý đổi tên cột dữ liệu.",
        "- Không tạo hàm mới nếu đã có hàm cùng chức năng.",
        "- Kiểm tra đường dẫn API trước khi tạo đường dẫn mới.",
        "- Kiểm tra cấu trúc thư mục trước khi tạo file mới.",
        "- Khi thay đổi cấu trúc quan trọng, hãy chạy lại file tạo PROJECT_INDEX.",
        "- PROJECT_INDEX chỉ là bản đồ dự án, không thay thế mã nguồn thật.",
    ])

    # --------------------------------------------------------
    # GHI FILE
    # --------------------------------------------------------

    OUTPUT.write_text(
        "\n".join(lines),
        encoding="utf-8",
    )

    print("=" * 60)
    print("ĐÃ TẠO PROJECT_INDEX.txt")
    print("=" * 60)
    print(f"Vị trí: {OUTPUT}")
    print(f"Số file đã quét: {len(files)}")
    print()
    print("Hãy mở PROJECT_INDEX.txt để kiểm tra.")


if __name__ == "__main__":
    main()