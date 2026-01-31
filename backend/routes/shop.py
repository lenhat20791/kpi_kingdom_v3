from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_db, Inventory, Item, Player
from typing import List

router = APIRouter(prefix="/admin/shop", tags=["Admin Shop"])

# 1. API LẤY DANH SÁCH TẤT CẢ VẬT PHẨM (Để Admin quản lý)
@router.get("/items", response_model=List[Item])
async def get_all_items(db: Session = Depends(get_db)):
    items = db.exec(select(Item)).all()
    return items

# 2. API TẠO VẬT PHẨM MỚI
@router.post("/items/add")
async def add_item(item_data: Item, db: Session = Depends(get_db)):
    db.add(item_data)
    db.commit()
    db.refresh(item_data)
    return {"message": f"Đã thêm vật phẩm: {item_data.name}", "item": item_data}

# 3. API XÓA VẬT PHẨM
@router.delete("/items/delete/{item_id}")
async def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = db.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Không tìm thấy vật phẩm")
    db.delete(item)
    db.commit()
    return {"message": "Đã xóa vật phẩm thành công"}