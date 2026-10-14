#!/usr/bin/env bash
# Kiểm tra kết nối từ Ubuntu thật. HTTP 200 chưa đủ: phát hiện một số trang chặn/WAF.
set -uo pipefail
urls=(
  'https://www.msa.gov.cn/html/cnmsa/hxaq/article/2026/544f7fd8c8124640ae1fa1b09b2af27d.html'
  'https://www.sealagom.com/coastal/China%20Coastal/Hainan/'
  'https://www.sealagom.com/coastal/China%20Coastal/Guangdong/'
)
for url in "${urls[@]}"; do
  echo "--- $url"
  tmp="$(mktemp)"
  code="$(curl --location --compressed --max-time 28 --retry 1 \
    -A 'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36' \
    -o "$tmp" -sS -w '%{http_code}' "$url")" || code=000
  echo "HTTP $code | bytes $(wc -c < "$tmp")"
  if grep -Eiq '当前访问疑似黑客攻击|已被云盾拦截|Access Denied|403 Forbidden|captcha' "$tmp"; then
    echo 'WARNING: trang trả về nội dung chặn truy cập/challenge.'
  elif grep -Eiq '琼航警|粤航警|航警|航行警告|China Coastal|Full content|Hainan' "$tmp"; then
    echo 'Có dấu hiệu nội dung nguồn; crawler cần kiểm tra phân tích tiếp.'
  else
    echo 'Chưa xác nhận được nội dung cảnh báo; xem log nếu crawler không có kết quả.'
  fi
  rm -f "$tmp"
done
