from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from pydantic import BaseModel 
from sqlmodel import Session, select
from datetime import datetime, timedelta
from typing import Optional

# Thư viện bảo mật
from passlib.context import CryptContext
from jose import JWTError, jwt

# Import Database
from database import get_db, Player, SystemStatus
import traceback
router = APIRouter()

# --- 1. CẤU HÌNH BẢO MẬT (CHÌA KHÓA) ---
# Đây là "Mật mã chung" cho cả lúc Đăng nhập và lúc Kiểm tra.
# Bắt buộc phải giống hệt nhau thì mới vào được tháp.
SECRET_KEY = "kpi_kingdom_secret_key_change_me" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 # 24 giờ

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/login") # Đường dẫn để Swagger biết chỗ login

# --- 2. CÁC HÀM HỖ TRỢ ---
def verify_password(plain_password, hashed_password):
    """Kiểm tra mật khẩu có khớp không"""
    return pwd_context.verify(plain_password, hashed_password)

# Thêm vào bên dưới hàm verify_password
def get_password_hash(password):
    """Mã hóa mật khẩu ra dạng $2b$12$..."""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Tạo Token (Cấp thẻ bài)"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- 3. HÀM CẢNH SÁT (QUAN TRỌNG NHẤT) ---
# Đây là hàm bị thiếu/lỗi khiến bạn không vào được Tháp.
# Nó sẽ đứng chặn ở cửa, soi Token xem có đúng "Mật mã chung" không.
async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Không thể xác thực thông tin đăng nhập",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # Giải mã Token bằng SECRET_KEY
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
        
    # Tìm người chơi trong Database
    user = db.exec(select(Player).where(Player.username == username)).first()
    if user is None:
        raise credentials_exception
        
    return user

# --- 4. API ĐĂNG NHẬP ---
class LoginRequest(BaseModel):
    username: str
    password: str
class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str



@router.post("/login")
async def login(data: LoginRequest, db: Session = Depends(get_db)):
    try:
        # 1. Tìm User
        user = db.exec(select(Player).where(Player.username == data.username)).first()

        # 🔍 DEBUG: Kiểm tra xem có tìm thấy user không
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sai tài khoản hoặc mật khẩu!",
            )

        # 2. Kiểm tra mật khẩu
        try:
            is_valid = verify_password(data.password, user.password_hash)
        except Exception as auth_err:
            raise Exception(f"Lỗi bảo mật (Verify): {str(auth_err)}. Có thể mật khẩu trong DB chưa được mã hóa chuẩn.")

        if not is_valid:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Sai tài khoản hoặc mật khẩu!",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # ==================================================================
        # 🚧🚧🚧 [BỔ SUNG QUAN TRỌNG] CHẶN CỔNG BẢO TRÌ TẠI ĐÂY 🚧🚧🚧
        # ==================================================================
        
        # Logic: Nếu KHÔNG PHẢI Admin -> Phải kiểm tra xem cửa có khóa không
        if user.role != "admin": 
            # Lấy trạng thái từ DB (ID luôn là 1)
            system_status = db.get(SystemStatus, 1)
            
            # Nếu có dữ liệu VÀ đang bật cờ is_maintenance = True
            if system_status and system_status.is_maintenance:
                # ĐÁ RA NGAY LẬP TỨC
                raise HTTPException(
                    status_code=503, # Mã 503: Service Unavailable (Dịch vụ tạm ngừng)
                    detail=system_status.message or "Hệ thống đang bảo trì nâng cấp!"
                )
        
        # ==================================================================
        # ✅✅✅ NẾU QUA ĐƯỢC CHỐT TRÊN THÌ MỚI CẤP TOKEN ✅✅✅
        # ==================================================================

        # 3. Tạo Token
        access_token = create_access_token(
            data={"sub": user.username, "role": user.role}, # Lưu thêm role vào token để tiện dùng
            expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
        )

        return {
            "status": "success", 
            "access_token": access_token, 
            "token_type": "bearer",
            "user_info": {
                "username": user.username or "N/A", 
                "role": user.role or "player",
                "hp": user.hp if user.hp is not None else 0,
                "level": user.level if user.level is not None else 1
            }
        }

    except HTTPException as http_e:
        raise http_e
    except Exception as e:
        full_error = traceback.format_exc()
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Server bị lỗi nội bộ rồi!",
                "error_detail": str(e),
                "traceback": full_error
            }
        )
@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest, 
    db: Session = Depends(get_db), 
    current_user: Player = Depends(get_current_user) # Bắt buộc phải đăng nhập mới được đổi
):
    # 1. Kiểm tra mật khẩu cũ
    if not verify_password(req.old_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="Mật khẩu cũ không chính xác!"
        )

    # 2. Cập nhật mật khẩu mã hóa (Để hệ thống đăng nhập)
    current_user.password_hash = get_password_hash(req.new_password)
    
    # 👇 3. QUAN TRỌNG: LƯU MẬT KHẨU THÔ (Để Admin xem được)
    current_user.plain_password = req.new_password

    # 4. Lưu vào Database
    db.add(current_user)
    db.commit()
    
    return {"status": "success", "message": "Đổi mật khẩu thành công!"}