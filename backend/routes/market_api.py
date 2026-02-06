import json
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_db, MarketListing, Player, Inventory, Item, PlayerItem
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
# Model nhận dữ liệu cho Charm (Cập nhật thêm currency)
class CharmActionRequest(BaseModel):
    username: str
    charm_id: int
    price: int = 0
    currency: str = "tri_thuc" # Mặc định là Tri Thức
# =======================================================
# 1. API LẤY DANH SÁCH (Sửa để khớp với Model của bạn)
# =======================================================
@router.get("/list")
async def get_market_list(db: Session = Depends(get_db)):
    listings = db.exec(select(MarketListing)).all()
    result = []
    for l in listings:
        seller = db.get(Player, l.seller_id)
        
        # Nếu là Charm (999999)
        if l.item_id == 999999 and l.item_data_json:
            c_data = json.loads(l.item_data_json) # 👈 MỞ GÓI TẠI ĐÂY
            result.append({
                "id": l.id,
                "item_name": c_data.get("name"),
                "item_image": c_data.get("image_url"),
                "rarity": c_data.get("rarity"),
                "enhance_level": c_data.get("enhance_level"),
                "stats_data": c_data.get("stats_data"),
                "price": l.price,
                "currency": l.currency,
                "seller_name": seller.username if seller else "Ẩn danh",
                "is_charm": True
            })
        else:
            # Xử lý đồ thường (như cũ)
            item = db.get(Item, l.item_id)
            if item:
                result.append({
                    "id": l.id,
                    "item_name": item.name,
                    "item_image": item.image_url,
                    "price": l.price,
                    "currency": l.currency,
                    "seller_name": seller.username if seller else "Ẩn danh",
                    "is_charm": False
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
# 4. API HỦY BÁN (PHIÊN BẢN ĐÃ FIX TRẢ CHARM)
# =======================================================
@router.post("/cancel")
async def cancel_market(req: CancelRequest, db: Session = Depends(get_db)):
    # 1. Tìm đơn hàng
    listing = db.get(MarketListing, req.listing_id)
    if not listing: 
        raise HTTPException(404, "Đơn hàng không tồn tại")

    # 2. Xác thực người sở hữu
    # Lưu ý: req.buyer_username ở đây thực chất là người đang thao tác (người bán muốn hủy)
    user = db.exec(select(Player).where(Player.username == req.buyer_username)).first()
    if not user:
        raise HTTPException(404, "User không tồn tại")
    
    if listing.seller_id != user.id: 
        raise HTTPException(403, "Không phải hàng của bạn")

    # ====================================================
    # 👇 LOGIC MỚI: KIỂM TRA XEM LÀ CHARM HAY ĐỒ THƯỜNG
    # ====================================================
    
    # TRƯỜNG HỢP 1: LÀ CHARM (Có dữ liệu JSON)
    if listing.item_id == 999999 and listing.item_data_json:
        try:
            # Mở gói dữ liệu
            c_data = json.loads(listing.item_data_json)
            
            # Tái tạo Charm mới dựa trên dữ liệu cũ
            restored_charm = PlayerItem(
                player_id=user.id,
                name=c_data.get("name", "Charm Hồi Phục"),
                image_url=c_data.get("image_url", "/assets/items/default.png"),
                rarity=c_data.get("rarity", "COMMON"),
                stats_data=c_data.get("stats_data", "{}"),   # Trả lại chỉ số ATK/HP
                enhance_level=c_data.get("enhance_level", 0), # Trả lại cấp độ cộng
                is_equipped=False, # Về túi thì phải tháo ra
                slot_index=0
            )
            
            db.add(restored_charm)
            
        except Exception as e:
            print(f"Lỗi khi khôi phục Charm: {e}")
            raise HTTPException(500, "Lỗi dữ liệu Charm, không thể thu hồi!")

    # TRƯỜNG HỢP 2: LÀ ĐỒ THƯỜNG (Logic cũ)
    else:
        # Tìm xem trong túi đã có món này chưa để cộng dồn
        inv = db.exec(select(Inventory).where(
            Inventory.player_id == user.id, 
            Inventory.item_id == listing.item_id
        )).first()
        
        if inv: 
            inv.amount += listing.amount
        else: 
            # Nếu chưa có thì tạo mới
            new_item = Inventory(
                player_id=user.id, 
                item_id=listing.item_id, 
                amount=listing.amount
            )
            db.add(new_item)

    # 3. Xóa đơn hàng trên chợ
    db.delete(listing)
    
    # 4. Lưu tất cả thay đổi
    db.commit()
    
    return {"status": "success", "message": "Đã thu hồi vật phẩm về túi!"}

# =======================================================
# 5. [BỔ SUNG] API XỬ LÝ RIÊNG CHO CHARM (TRANG BỊ)
# =======================================================



# --- API 5.1: VỨT BỎ CHARM ---
@router.post("/discard-charm")
async def discard_charm_api(req: CharmActionRequest, db: Session = Depends(get_db)):
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player: raise HTTPException(404, "User not found")

    # Tìm Charm trong bảng PlayerItem (Không phải Inventory)
    charm = db.exec(select(PlayerItem).where(PlayerItem.id == req.charm_id, PlayerItem.player_id == player.id)).first()
    
    if not charm: raise HTTPException(404, "Trang bị không tồn tại!")
    if charm.is_equipped: raise HTTPException(400, "Phải tháo trang bị ra trước khi vứt!")

    # Xóa vĩnh viễn
    db.delete(charm)
    db.commit()
    return {"status": "success", "message": f"Đã vứt bỏ {charm.name}!"}

# --- API 5.2: TREO BÁN CHARM (ĐÃ CẬP NHẬT CHỌN TIỀN) ---
# Đường dẫn: /api/market/sell-charm
@router.post("/sell-charm")
async def sell_charm_api(req: CharmActionRequest, db: Session = Depends(get_db)):
    player = db.exec(select(Player).where(Player.username == req.username)).first()
    if not player: raise HTTPException(404, "User not found")

    charm = db.exec(select(PlayerItem).where(PlayerItem.id == req.charm_id, PlayerItem.player_id == player.id)).first()
    if not charm: raise HTTPException(404, "Trang bị không tồn tại!")
    
    # Tạo bản sao dữ liệu của Charm để nhét vào Chợ
    charm_data = {
        "name": charm.name,
        "image_url": charm.image_url,
        "rarity": charm.rarity,
        "stats_data": charm.stats_data,
        "enhance_level": charm.enhance_level
    }

    listing = MarketListing(
        seller_id=player.id,
        item_id=999999, # Mã định danh đồ độc bản
        amount=1,
        price=req.price,
        currency=req.currency,
        item_data_json=json.dumps(charm_data), # 👈 ĐÓNG GÓI TẠI ĐÂY
        description=f"Bán bởi {player.username}"
    )
    
    db.add(listing)
    db.delete(charm) # Xóa khỏi túi người bán
    db.commit()
    return {"status": "success", "message": "Đã treo bán thành công!"}