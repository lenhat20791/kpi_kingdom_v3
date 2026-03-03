import json
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select
from database import get_db, MarketListing, Player, Inventory, Item, PlayerItem, Companion, CompanionTemplate
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from routes.auth import get_current_user
from sqlalchemy.orm import joinedload

router = APIRouter(prefix="/api/market", tags=["Market"])

# --- DATA MODELS (Khớp với Frontend) ---
class SellRequest(BaseModel):
    username: str
    item_id: int
    amount: int
    price: int
    currency: str
class SellCharmRequest(BaseModel):
    item_id: int
    price: int
    currency: str
class BuyRequest(BaseModel):
    buyer_username: str
    listing_id: int

class CancelRequest(BaseModel):
    buyer_username: str
    listing_id: int

# 1. Định nghĩa Class yêu cầu riêng cho Thẻ bài
class SellCompanionRequest(BaseModel):
    companion_id: str  # Dùng đúng ID số nguyên từ bảng companion
    price: int
    currency: str

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
    # Lấy danh sách mới nhất
    listings = db.exec(select(MarketListing).order_by(MarketListing.created_at.desc())).all()
    result = []
    
    for l in listings:
        seller = db.get(Player, l.seller_id)
        seller_name = seller.username if seller else "Ẩn danh"
        
        # Mở gói JSON (nếu có) dùng chung cho Charm và Thẻ bài
        json_data = {}
        if l.item_data_json:
            try:
                json_data = json.loads(l.item_data_json)
            except:
                pass

        item_res = {
            "id": l.id,
            "seller_id": l.seller_id,
            "seller_name": seller_name,
            "item_id": l.item_id,      # 👈 QUAN TRỌNG: Frontend cần cái này để if/else
            "price": l.price,
            "currency": l.currency,
            "amount": l.amount,        # 👈 Đừng quên số lượng
            "item_data_json": l.item_data_json, # Frontend cần cái này để parse lại
            
            # Các giá trị mặc định
            "item_name": "Vật phẩm lỗi",
            "item_image": "/assets/items/default.png",
            "is_charm": False,
            "is_companion": False
        }

        # 👉 CASE 1: CHARM (999999)
        if l.item_id == 999999:
            item_res.update({
                "item_name": json_data.get("name", "Charm Lỗi"),
                "item_image": json_data.get("image_url", "/assets/items/default.png"),
                "rarity": json_data.get("rarity"),
                "enhance_level": json_data.get("enhance_level", 0),
                "is_charm": True
            })

        # 👉 CASE 2: THẺ BÀI (999998) - QUAN TRỌNG
        elif l.item_id == 999998:
            item_res.update({
                "item_name": json_data.get("name", "Thẻ bài ẩn"),
                "item_image": json_data.get("image", "/assets/card/back.png"), # JSON thẻ bài dùng key 'image'
                "rarity": json_data.get("rarity"),
                "star": json_data.get("star", 1),
                "is_companion": True # Cờ đánh dấu cho Frontend dễ xử lý
            })

        # 👉 CASE 3: ĐỒ THƯỜNG (1, 2, 3...)
        else:
            item = db.get(Item, l.item_id)
            if item:
                item_res.update({
                    "item_name": item.name,
                    "item_image": item.image_url,
                    "is_charm": False
                })
            else:
                # Nếu không tìm thấy item trong DB (dữ liệu rác), bỏ qua vòng lặp này
                continue 

        result.append(item_res)

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
async def buy_market_item(req: BuyRequest, db: Session = Depends(get_db)):
    # 1. Tìm đơn hàng
    listing = db.get(MarketListing, req.listing_id)
    if not listing: 
        raise HTTPException(404, "Vật phẩm không còn tồn tại (hoặc đã bị ai đó mua mất)!")

    # 2. Tìm người mua
    buyer = db.exec(select(Player).where(Player.username == req.buyer_username)).first()
    if not buyer: raise HTTPException(404, "User lỗi")
    
    # Chặn tự mua đồ mình bán
    if listing.seller_id == buyer.id:
        raise HTTPException(400, "Bạn không thể tự mua đồ của chính mình!")

    # ======================================================
    # 👇 LOGIC MỚI: XỬ LÝ ĐỦ 3 LOẠI TIỀN TỆ 👇
    # ======================================================
    cost = listing.price
    currency_type = listing.currency # tri_thuc / chien_tich / vinh_du

    # --- BƯỚC A: TRỪ TIỀN NGƯỜI MUA ---
    if currency_type == "tri_thuc":
        if buyer.tri_thuc < cost: raise HTTPException(400, "Không đủ Tri Thức (Vàng)!")
        buyer.tri_thuc -= cost
        
    elif currency_type == "chien_tich":
        # (Lưu ý: Đảm bảo bảng Player có cột 'chien_tich')
        if buyer.chien_tich < cost: raise HTTPException(400, "Không đủ Chiến Tích (Ruby)!")
        buyer.chien_tich -= cost
        
    elif currency_type == "vinh_du":
        # (Lưu ý: Đảm bảo bảng Player có cột 'vinh_du')
        if buyer.vinh_du < cost: raise HTTPException(400, "Không đủ Vinh Dự (Badge)!")
        buyer.vinh_du -= cost
        
    else:
        raise HTTPException(400, f"Loại tiền tệ không hợp lệ: {currency_type}")

    # --- BƯỚC B: CỘNG TIỀN CHO NGƯỜI BÁN ---
    seller = db.get(Player, listing.seller_id)
    if seller:
        if currency_type == "tri_thuc": seller.tri_thuc += cost
        elif currency_type == "chien_tich": seller.chien_tich += cost
        elif currency_type == "vinh_du": seller.vinh_du += cost

    # ======================================================
    # 👇 PHẦN CÒN LẠI (GIAO HÀNG) GIỮ NGUYÊN 👇
    # ======================================================
    
    # TRƯỜNG HỢP A: ĐÂY LÀ CHARM (Có dữ liệu JSON)
    if listing.item_data_json: 
        import json
        try:
            c_data = json.loads(listing.item_data_json)
            new_charm = PlayerItem(
                player_id=buyer.id,
                name=c_data.get("name", "Charm"),
                image_url=c_data.get("image_url", "/assets/items/default.png"),
                rarity=c_data.get("rarity", "COMMON"),
                stats_data=c_data.get("stats_data", "{}"),
                enhance_level=c_data.get("enhance_level", 0),
                is_equipped=False,
                slot_index=0
            )
            db.add(new_charm)
        except Exception as e:
            print(f"Lỗi tạo charm: {e}")
            raise HTTPException(500, "Lỗi dữ liệu vật phẩm!")

    # TRƯỜNG HỢP B: ĐÂY LÀ ĐỒ THƯỜNG
    else:
        inv_item = db.exec(select(Inventory).where(
            Inventory.player_id == buyer.id,
            Inventory.item_id == listing.item_id
        )).first()

        if inv_item:
            inv_item.amount += listing.amount
        else:
            new_inv = Inventory(
                player_id=buyer.id,
                item_id=listing.item_id,
                amount=listing.amount
            )
            db.add(new_inv)

    # Xóa đơn hàng & Lưu
    db.delete(listing)
    db.commit()

    return {"status": "success", "message": f"Đã mua thành công bằng {cost} {currency_type}!"}

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
# =======================================================
# 2. API ĐĂNG BÁN CHARM (PHIÊN BẢN LƯU JSON ĐẦY ĐỦ)
# =======================================================
@router.post("/sell-charm")
async def sell_charm(
    req: SellCharmRequest, 
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # 1. Kiểm tra Item trong túi Charm (PlayerItem)
    # Lưu ý: Tìm theo ID của PlayerItem chứ không phải Item thường
    item = db.get(PlayerItem, req.item_id)
    
    if not item:
        raise HTTPException(404, "Charm không tồn tại!")
    
    if item.player_id != current_user.id:
        raise HTTPException(403, "Vật phẩm này không phải của bạn!")

    if item.is_equipped:
        raise HTTPException(400, "Phải tháo trang bị trước khi bán!")

    # 2. Đóng gói dữ liệu Charm vào JSON (QUAN TRỌNG NHẤT)
    # Đây là bước tạo "Linh hồn" cho món hàng
    import json
    charm_data = {
        "name": item.name,
        "image_url": item.image_url,
        "rarity": item.rarity,
        "stats_data": item.stats_data,   # Lưu chỉ số ATK/HP
        "enhance_level": item.enhance_level
    }
    
    # Chuyển thành chuỗi JSON
    json_str = json.dumps(charm_data)

    # 3. Tạo đơn hàng mới
    new_listing = MarketListing(
        seller_id=current_user.id,
        seller_name=current_user.full_name, # Hoặc username
        item_id=999999,  # ID giả định cho Charm để tránh trùng Item thường
        item_name=item.name,
        item_image=item.image_url,
        amount=1,
        price=req.price,
        currency=req.currency,
        description=f"Cấp cường hóa: +{item.enhance_level}",
        
        # 👇 QUAN TRỌNG: LƯU JSON VÀO DB 👇
        item_data_json=json_str,
        
        created_at=datetime.now()
    )

    # 4. Xóa Charm khỏi túi người bán (Chuyển lên chợ)
    db.delete(item)
    
    # 5. Lưu đơn hàng
    db.add(new_listing)
    db.commit()

    return {"status": "success", "message": "Đã treo bán Charm thành công!"}

# 2. Tạo Router bán Thẻ bài riêng biệt
@router.post("/sell-companion")
async def sell_companion(
    req: SellCompanionRequest, 
    current_user: Player = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    # Tìm thẻ bài trong bảng companion (Logic này của bạn ĐANG ĐÚNG)
    companion = db.query(Companion).options(joinedload(Companion.template)).filter(
        Companion.id == req.companion_id, # Bây giờ đã nhận chuỗi OK
        Companion.player_id == current_user.id
    ).first()

    if not companion:
        return {"status": "error", "message": "Không tìm thấy thẻ bài hoặc bạn không sở hữu nó."}

    try:
        # Tạm thời chuyển dữ liệu thẻ bài thành JSON để lưu lên Chợ (Giữ nguyên stats của bạn)
        item_data = {
            "name": companion.temp_name or companion.template.name,
            "rarity": companion.template.rarity,  # 👈 Lấy độ hiếm thật (R, SR...) thay vì "N/A" 
            "image": companion.template.image_path, # 👈 Thêm đường dẫn ảnh (VD: /assets/card/r/...)
            "star": companion.star,
            "stats": {
                "hp": companion.hp, 
                "atk": companion.atk
            },
            "ui_id": req.companion_id # Lưu lại ID gốc để debug nếu cần
        }

        # Tạo bản ghi niêm yết (Đã sửa lỗi gạch đỏ ở item_name và category)
        # Chúng ta đưa 'name' vào JSON thay vì cột riêng để tránh lỗi DB
        new_listing = MarketListing(
            seller_id=current_user.id,
            item_id=999998, # Mã riêng cho Companion trên chợ
            item_data_json=json.dumps(item_data), # Toàn bộ thông tin thẻ nằm ở đây
            price=req.price,
            currency=req.currency
        )
        db.add(new_listing)
        
        # Xóa thẻ khỏi túi người chơi (Quan trọng: Đã mang lên chợ thì không còn trong túi)
        db.delete(companion)
        db.commit()
        
        return {"status": "success", "message": f"Đã treo thẻ {companion.temp_name} lên Chợ Đen!"}
    except Exception as e:
        db.rollback()
        return {"status": "error", "message": str(e)}