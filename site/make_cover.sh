#!/usr/bin/env bash
# 產生封面影片與預覽圖（docs/media/）。需要 ffmpeg 與 python3。原始影片來自 Pexels（免費授權）：
#   電腦版：Sarowar Hussain〈Timelapse of Brooklyn Bridge and NYC skyline lit up at dusk〉
#           https://www.pexels.com/video/time-lapse-video-of-boats-traveling-on-river-against-city-background-5636798/
#   手機版：Anatolii Grytsenko〈Breathtaking New York City skyline at twilight〉
#           https://www.pexels.com/video/breathtaking-new-york-city-skyline-at-twilight-32458596/
# 電腦版：河面做成長曝光般的柔順質感（也讓檔案小很多），再加速 2 倍。
# 兩支都把開頭疊到結尾淡入淡出，循環播放時看不出接縫。
# 用法：bash site/make_cover.sh [原始影片資料夾]（資料夾裡沒有原檔會自動下載）
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=${1:-.cover-src}
OUT=docs/media
mkdir -p "$SRC" "$OUT"

fetch() { [ -s "$SRC/$1" ] || curl -fL --retry 3 -o "$SRC/$1" "$2"; }
fetch wide.mp4 https://videos.pexels.com/video-files/5636798/5636798-hd_1920_1080_30fps.mp4
fetch tall.mp4 https://videos.pexels.com/video-files/32458596/13843680_1080_1920_30fps.mp4
calc() { python3 -c "print(round($1, 3))"; }
dur() { ffprobe -v error -show_entries format=duration -of csv=p=0 "$1"; }

# 循環：取 0～D 秒，把開頭 X 秒疊到結尾淡入，輸出長度 D−X，最後一格正好接回第一格
seam() {  # 前段濾鏡輸出標籤 D X
  echo "$1trim=0:$2,setpts=PTS-STARTPTS,split[a][b];[a]trim=$3:$2,setpts=PTS-STARTPTS[body];\
[b]trim=0:$3,setpts=PTS-STARTPTS[head];[body][head]xfade=transition=fade:duration=$3:offset=$(calc "$2 - 2 * $3")"
}
enc() {  # 輸入參數 濾鏡 寬 高 CRF 輸出
  local args=$1
  # shellcheck disable=SC2086
  ffmpeg -v error -y $args -filter_complex "$2,scale=$3:$4:flags=lanczos,setsar=1,format=yuv420p[v]" -map "[v]" -an \
    -c:v libx264 -preset slow -crf "$5" -profile:v high -level:v 4.1 -g 60 -movflags +faststart -tag:v avc1 "$6"
}
poster() { ffmpeg -v error -y -i "$1" -frames:v 1 -q:v "$3" "$2"; }

# 電腦版：遮罩 0.58 以下漸漸套用 20 格平均（水面），岸邊的船和天際線保持清楚
ffmpeg -v error -y -f lavfi -i "color=black:s=1920x1080,format=gray" -frames:v 1 \
  -vf "geq=lum='clip((Y/H-0.58)/0.12,0,1)*255'" "$SRC/mask.png"
D=$(calc "($(dur "$SRC/wide.mp4") - 1.2) / 2 - 0.1")
WIDE=$(seam "[0:v]split[base][w];[w]tmix=frames=20,format=yuva420p[wt];[1:v]format=gray[m];[wt][m]alphamerge[wa];\
[base][wa]overlay=shortest=1,trim=start=1,setpts=PTS-STARTPTS,setpts=PTS/2,fps=30," "$D" 1.5)
enc "-i $SRC/wide.mp4 -loop 1 -i $SRC/mask.png" "$WIDE" 1920 1080 29 "$OUT/cover-1080.mp4"
enc "-i $SRC/wide.mp4 -loop 1 -i $SRC/mask.png" "$WIDE" 1280 720 28 "$OUT/cover-720.mp4"

# 手機版：原速
D=$(calc "$(dur "$SRC/tall.mp4") - 0.1")
TALL=$(seam "[0:v]fps=30," "$D" 1.2)
enc "-i $SRC/tall.mp4" "$TALL" 720 1280 27 "$OUT/cover-tall.mp4"

poster "$OUT/cover-1080.mp4" "$OUT/cover-1080.jpg" 5
poster "$OUT/cover-720.mp4" "$OUT/cover-720.jpg" 5
poster "$OUT/cover-tall.mp4" "$OUT/cover-tall.jpg" 5
ls -la "$OUT"
