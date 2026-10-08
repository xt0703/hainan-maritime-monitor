# Hainan Maritime Warning Monitor

Theo dõi cảnh báo hàng hải của Hainan MSA / China MSA liên quan đến bắn đạn thật, huấn luyện quân sự và diễn tập; chuẩn hóa tọa độ, hiển thị trên bản đồ và lưu lịch sử.

## Kiến trúc
- `crawler/`: tải và phân tích thông báo
- `data/notices.json`: cơ sở dữ liệu chuẩn hóa
- `docs/`: web app Leaflet để triển khai bằng GitHub Pages
- `.github/workflows/update.yml`: kiểm tra mỗi giờ, cập nhật dữ liệu và triển khai Pages

## Nguồn
1. `https://www.hn.msa.gov.cn/` (ưu tiên)
2. `https://www.msa.gov.cn/` (nguồn chính thức dự phòng)

## Từ khóa
`实弹射击`, `射击训练`, `军事训练`, `军事演习`, `军事活动`, `军事任务`

## Chạy cục bộ
```bash
python -m pip install -r requirements.txt
python crawler/main.py
python -m http.server 8000 -d docs
```
Sau đó mở `http://localhost:8000`.

## GitHub Pages
Workflow đã chứa job deploy Pages. Nếu repository chưa bật Pages, vào repository **Settings → Pages → Source: GitHub Actions** một lần.

## Lưu ý
- Múi giờ nguồn Trung Quốc: UTC+8 (`Asia/Shanghai`).
- Hiển thị giờ Việt Nam: UTC+7 (`Asia/Ho_Chi_Minh`).
- Không dùng dữ liệu này thay thế NAVTEX/SafetyNET hoặc thông báo hàng hải chính thức khi ra quyết định an toàn hàng hải.
