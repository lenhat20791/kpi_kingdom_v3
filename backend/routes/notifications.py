from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_db, Notification, Player
from routes.auth import get_current_user 
from pydantic import BaseModel
from sqlalchemy import desc

router = APIRouter()

class NotiCreate(BaseModel):
    type: str
    content: str
    is_active: bool = True

# --- API CHO ADMIN QUẢN LÝ ---
@router.post("/create")
async def create_notification(req: NotiCreate, db: Session = Depends(get_db)):
    # Bạn có thể thêm check admin ở đây: if current_user.role != 'admin'...
    new_noti = Notification(type=req.type, content=req.content, is_active=req.is_active)
    db.add(new_noti)
    db.commit()
    return {"status": "success", "msg": "Đã tạo thông báo"}

@router.get("/all")
async def get_all_notifications(db: Session = Depends(get_db)):
    notis = db.exec(select(Notification).order_by(Notification.created_at.desc())).all()
    return notis

@router.delete("/delete/{noti_id}")
async def delete_notification(noti_id: int, db: Session = Depends(get_db)):
    noti = db.get(Notification, noti_id)
    if not noti: raise HTTPException(status_code=404)
    db.delete(noti)
    db.commit()
    return {"status": "success"}

@router.put("/toggle/{noti_id}")
async def toggle_notification(noti_id: int, db: Session = Depends(get_db)):
    noti = db.get(Notification, noti_id)
    if not noti: raise HTTPException(status_code=404)
    noti.is_active = not noti.is_active
    db.add(noti)
    db.commit()
    return {"status": "success", "new_state": noti.is_active}

# --- API CHO NGƯỜI DÙNG (PUBLIC) ---
@router.get("/public")
async def get_public_notifications(db: Session = Depends(get_db)):
    """
    Lấy thông báo cho người dùng:
    - Lấy tất cả thông báo đang Active.
    - Sắp xếp theo thời gian mới nhất lên đầu (created_at DESC).
    """
    notis = db.exec(
        select(Notification)
        .where(Notification.is_active == True)
        .order_by(desc(Notification.created_at)) # 👈 Quan trọng: Mới nhất lên đầu
    ).all()
    
    return notis