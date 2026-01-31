from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_db, MarketListing, Player, Inventory, Item
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

router = APIRouter(prefix="/api/market", tags=["Market"])

# --- DATA MODELS (Khớp với Frontend) ---
class SellRequest(BaseModel):
    username: str
    item_id: int
    amount: int
    price: int
    currency: str

class BuyRequest(BaseModel):
    buyer_username: str
    listing_id: int

class CancelRequest(BaseModel):
    buyer_username: str
    listing_id: int

# =======================================================
# 1. API LẤY DANH SÁCH (Sửa để khớp với Model của bạn)
# =======================================================
@router.get("/list")
async def get_market_list(db: Session = Depends(get_db)):
    # ❌ Bỏ .where(status="active") vì bảng của bạn không có cột status
    listings = db.exec(select(MarketListing)).all()
    
    result = []
    for l in listings:
        # Lấy thông tin Item
        item = db.get(Item, l.item_id)
        
        # Lấy thông tin người bán từ ID (Vì model bạn chỉ lưu seller_id)
        seller = db.get(Player, l.seller_id)
        seller_name = seller.username if seller else "Ẩn danh"
        
        if item:
            # Logic an toàn để lấy ảnh (Check nhiều trường hợp tên cột)
            img_url = getattr(item, "item_image", None) or getattr(item, "image_url", None) or getattr(item, "image", None) or "/assets/images/items/default.png"

            result.append({
                "id": l.id,
                "item_name": getattr(item, "name", "Vật phẩm lạ"),
                "item_image": img_url,
                "amount": l.amount,
                "price": l.price,
                "currency": l.currency,
                "seller_name": seller_name,
                "description": l.description # Model bạn có field này
            })
    return result

# =======================================================
# 2. API ĐĂNG BÁN
# =======================================================
@router.post("/sell")
def sell_to_market(req: SellRequest, db: Session = Depends(get_db)):
    # Tìm user theo username frontend gửi lên
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player:
        raise HTTPException(404, "User không tồn tại")
    
    # Check item ownership
    inv = db.exec(select(Inventory).where(
        Inventory.player_id == player.id, 
        Inventory.item_id == req.item_id
    )).first()
    
    if not inv or inv.amount < req.amount:
        raise HTTPException(400, "Không đủ vật phẩm để bán")

    # Trừ đồ trong kho
    inv.amount -= req.amount
    if inv.amount == 0: db.delete(inv)
    else: db.add(inv)
    
    # Tạo Listing (Dùng đúng cột trong Model của bạn)
    listing = MarketListing(
        seller_id=player.id, # Dùng ID thay vì Name
        item_id=req.item_id,
        amount=req.amount,
        price=req.price,
        currency=req.currency,
        created_at=str(datetime.now()),
        description=f"Bán bởi {player.username}"
    )
    db.add(listing)
    db.commit()
    
    return {"status": "success", "message": "Đã treo bán lên chợ!"}

# =======================================================
# 3. API MUA HÀNG
# =======================================================
@router.post("/buy")
def buy_market_item(req: BuyRequest, db: Session = Depends(get_db)):
    listing = db.get(MarketListing, req.listing_id)
    if not listing: 
        raise HTTPException(404, "Đơn hàng không tồn tại")
    
    buyer = db.exec(select(Player).where(Player.username == req.buyer_username)).first()
    if not buyer:
         raise HTTPException(404, "Người mua không hợp lệ")

    seller = db.get(Player, listing.seller_id)
    
    # Chặn tự mua đồ mình
    if buyer.id == seller.id:
        raise HTTPException(400, "Không thể tự mua đồ của mình")

    # 1. Check tiền
    buyer_balance = getattr(buyer, listing.currency, 0)
    if buyer_balance < listing.price:
        raise HTTPException(400, f"Bạn không đủ {listing.currency}!")

    # 2. Giao dịch tiền
    setattr(buyer, listing.currency, buyer_balance - listing.price)
    
    seller_balance = getattr(seller, listing.currency, 0)
    setattr(seller, listing.currency, seller_balance + listing.price)

    # 3. Chuyển đồ cho Buyer
    buyer_inv = db.exec(select(Inventory).where(
        Inventory.player_id == buyer.id, 
        Inventory.item_id == listing.item_id
    )).first()
    
    if buyer_inv: 
        buyer_inv.amount += listing.amount
    else: 
        db.add(Inventory(player_id=buyer.id, item_id=listing.item_id, amount=listing.amount))

    # 4. Xóa listing (Vì bảng không có cột status nên mua xong là xóa)
    db.delete(listing) 
    
    db.add(buyer)
    db.add(seller)
    db.commit()
    return {"status": "success", "message": "Mua hàng thành công!"}

# =======================================================
# 4. API HỦY BÁN
# =======================================================
@router.post("/cancel")
def cancel_market(req: CancelRequest, db: Session = Depends(get_db)):
    listing = db.get(MarketListing, req.listing_id)
    if not listing: raise HTTPException(404, "Đơn hàng không tồn tại")

    user = db.exec(select(Player).where(Player.username == req.buyer_username)).first()
    
    if listing.seller_id != user.id: 
        raise HTTPException(403, "Không phải hàng của bạn")

    # Trả đồ về kho
    inv = db.exec(select(Inventory).where(
        Inventory.player_id == user.id, 
        Inventory.item_id == listing.item_id
    )).first()
    
    if inv: inv.amount += listing.amount
    else: db.add(Inventory(player_id=user.id, item_id=listing.item_id, amount=listing.amount))

    # Xóa khỏi chợ
    db.delete(listing)
    
    db.commit()
    return {"status": "success", "message": "Đã hủy bán, vật phẩm đã về kho!"}