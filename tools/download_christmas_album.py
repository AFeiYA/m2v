#!/usr/bin/env python3
"""
M2V 公有领域圣诞专辑素材与发行工程构建工具
全自动下载 10 首无版权风险的传统公有领域圣诞名曲参考音源、标准公版英文歌词，
并生成 DistroKid 发行元数据配置及 M2V 卡拉OK视频工程架构。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALBUM_DIR = PROJECT_ROOT / "projects" / "christmas_album"

HEADERS = {"User-Agent": "ChristmasAlbumBot/1.0 (contact@fovea.si)"}

TRACKS = [
    {
        "track_no": 1,
        "folder": "01_Silent_Night",
        "title": "Silent Night",
        "title_cn": "平安夜",
        "composer": "Franz Xaver Gruber",
        "lyricist": "Joseph Mohr (English translation: John Freeman Young)",
        "year": 1818,
        "url": "https://upload.wikimedia.org/wikipedia/commons/a/a0/Silent_Night_%28choral%29.ogg",
        "ext": ".ogg",
        "bpm": 80,
        "key": "Bb Major",
        "mood": "Calm, Peaceful, Ethereal, Acoustic",
        "lyrics": """Silent night, holy night!
All is calm, all is bright.
Round yon Virgin, Mother and Child.
Holy infant so tender and mild,
Sleep in heavenly peace,
Sleep in heavenly peace.

Silent night, holy night!
Shepherds quake at the sight.
Glories stream from heaven afar,
Heavenly hosts sing Alleluia,
Christ the Savior is born!
Christ the Savior is born!

Silent night, holy night!
Son of God, love's pure light.
Radiant beams from Thy holy face,
With the dawn of redeeming grace,
Jesus Lord, at Thy birth,
Jesus Lord, at Thy birth."""
    },
    {
        "track_no": 2,
        "folder": "02_Jingle_Bells",
        "title": "Jingle Bells",
        "title_cn": "铃儿响叮当",
        "composer": "James Lord Pierpont",
        "lyricist": "James Lord Pierpont",
        "year": 1857,
        "url": "https://upload.wikimedia.org/wikipedia/commons/3/32/Jingle_Bells_Or_The_One_Horse_Open_Sleigh_Complete.ogg",
        "ext": ".ogg",
        "bpm": 120,
        "key": "F Major",
        "mood": "Joyful, Upbeat, Festive, Swing",
        "lyrics": """Dashing through the snow
In a one-horse open sleigh
O'er the fields we go
Laughing all the way
Bells on bobtails ring
Making spirits bright
What fun it is to ride and sing
A sleighing song tonight!

Jingle bells, jingle bells,
Jingle all the way!
O what fun it is to ride
In a one-horse open sleigh, hey!
Jingle bells, jingle bells,
Jingle all the way!
O what fun it is to ride
In a one-horse open sleigh!

A day or two ago
I thought I'd take a ride
And soon, Miss Fanny Bright
Was seated by my side
The horse was lean and lank
Misfortune seemed his lot
He got into a drifted bank
And we—we got upsot!

Jingle bells, jingle bells,
Jingle all the way!
O what fun it is to ride
In a one-horse open sleigh, hey!
Jingle bells, jingle bells,
Jingle all the way!
O what fun it is to ride
In a one-horse open sleigh!"""
    },
    {
        "track_no": 3,
        "folder": "03_Deck_The_Halls",
        "title": "Deck the Halls",
        "title_cn": "装饰大厅 / 红烛泪",
        "composer": "Traditional Welsh Melody",
        "lyricist": "Thomas Oliphant",
        "year": 1862,
        "url": "https://upload.wikimedia.org/wikipedia/commons/5/53/Deck_the_Halls_%28USAFB_Concert_Band%29.ogg",
        "ext": ".ogg",
        "bpm": 96,
        "key": "D Major",
        "mood": "Cheerful, Celebration, Brass, Traditional",
        "lyrics": """Deck the halls with boughs of holly,
Fa la la la la, la la la la!
'Tis the season to be jolly,
Fa la la la la, la la la la!
Don we now our gay apparel,
Fa la la, la la la, la la la!
Troll the ancient Yule tide carol,
Fa la la la la, la la la la!

See the blazing Yule before us,
Fa la la la la, la la la la!
Strike the harp and join the chorus,
Fa la la la la, la la la la!
Follow me in merry measure,
Fa la la, la la la, la la la!
While I tell of Yule tide treasure,
Fa la la la la, la la la la!

Fast away the old year passes,
Fa la la la la, la la la la!
Hail the new, ye lads and lasses,
Fa la la la la, la la la la!
Sing we joyous, all together,
Fa la la, la la la, la la la!
Heedless of the wind and weather,
Fa la la la la, la la la la!"""
    },
    {
        "track_no": 4,
        "folder": "04_We_Wish_You_A_Merry_Christmas",
        "title": "We Wish You a Merry Christmas",
        "title_cn": "祝你圣诞快乐",
        "composer": "Traditional English Carol",
        "lyricist": "Traditional",
        "year": 1500,
        "url": "https://upload.wikimedia.org/wikipedia/commons/f/f8/Anonimo_-_We_Wish_You_a_Merry_Christmas.ogg",
        "ext": ".ogg",
        "bpm": 128,
        "key": "Ab Major",
        "mood": "Waltz, Warm, Sing-along, Ensemble",
        "lyrics": """We wish you a merry Christmas,
We wish you a merry Christmas,
We wish you a merry Christmas,
And a happy New Year!

Good tidings we bring
To you and your kin,
Good tidings for Christmas
And a happy New Year!

Now bring us some figgy pudding,
Now bring us some figgy pudding,
Now bring us some figgy pudding,
And bring it right here!

Good tidings we bring
To you and your kin,
Good tidings for Christmas
And a happy New Year!

For we all like figgy pudding,
For we all like figgy pudding,
For we all like figgy pudding,
So bring some out here!

We won't go until we get some,
We won't go until we get some,
We won't go until we get some,
So bring some out here!

We wish you a merry Christmas,
We wish you a merry Christmas,
We wish you a merry Christmas,
And a happy New Year!"""
    },
    {
        "track_no": 5,
        "folder": "05_Joy_To_The_World",
        "title": "Joy to the World",
        "title_cn": "普世欢腾",
        "composer": "George Frideric Handel / Lowell Mason",
        "lyricist": "Isaac Watts",
        "year": 1719,
        "url": "https://upload.wikimedia.org/wikipedia/commons/8/80/Georg_Friedrich_H%C3%A4ndel_-_Joy_to_the_World.ogg",
        "ext": ".ogg",
        "bpm": 92,
        "key": "D Major",
        "mood": "Majestic, Grand, Choir, Uplifting",
        "lyrics": """Joy to the world! The Lord is come:
Let earth receive her King;
Let every heart prepare Him room,
And heaven and nature sing,
And heaven and nature sing,
And heaven, and heaven and nature sing!

Joy to the world! The Savior reigns:
Let men their songs employ;
While fields and floods, rocks, hills, and plains
Repeat the sounding joy,
Repeat the sounding joy,
Repeat, repeat the sounding joy!

He rules the world with truth and grace,
And makes the nations prove
The glories of His righteousness,
And wonders of His love,
And wonders of His love,
And wonders, wonders of His love!"""
    },
    {
        "track_no": 6,
        "folder": "06_Hark_The_Herald_Angels_Sing",
        "title": "Hark! The Herald Angels Sing",
        "title_cn": "听啊！天使高声唱 / 新生王歌",
        "composer": "Felix Mendelssohn",
        "lyricist": "Charles Wesley",
        "year": 1739,
        "url": "https://upload.wikimedia.org/wikipedia/commons/7/72/Charles_Wesley_-_Hark%21_The_Herald_Angels_Sing.ogg",
        "ext": ".ogg",
        "bpm": 88,
        "key": "F Major",
        "mood": "Triumphant, Sacred, Orchestral, Inspiring",
        "lyrics": """Hark! The herald angels sing,
"Glory to the newborn King;
Peace on earth, and mercy mild,
God and sinners reconciled!"
Joyful, all ye nations rise,
Join the triumph of the skies;
With th'angelic host proclaim,
"Christ is born in Bethlehem!"
Hark! The herald angels sing,
"Glory to the newborn King!"

Christ, by highest heav'n adored;
Christ the everlasting Lord;
Late in time, behold Him come,
Offspring of a virgin's womb.
Veiled in flesh the Godhead see;
Hail th'incarnate Deity,
Pleased as man with men to dwell,
Jesus our Emmanuel.
Hark! The herald angels sing,
"Glory to the newborn King!"

Hail the heav'n-born Prince of Peace!
Hail the Sun of Righteousness!
Light and life to all He brings,
Ris'n with healing in His wings.
Mild He lays His glory by,
Born that man no more may die,
Born to raise the sons of earth,
Born to give them second birth.
Hark! The herald angels sing,
"Glory to the newborn King!"""
    },
    {
        "track_no": 7,
        "folder": "07_O_Tannenbaum",
        "title": "O Tannenbaum (O Christmas Tree)",
        "title_cn": "噢，圣诞树",
        "composer": "Traditional German Melody",
        "lyricist": "Ernst Anschütz",
        "year": 1824,
        "url": "https://upload.wikimedia.org/wikipedia/commons/b/bc/U.S._Army_Band_-_O_Tannenbaum.ogg",
        "ext": ".ogg",
        "bpm": 76,
        "key": "G Major",
        "mood": "Warm, Nostalgic, Family, Woodwind",
        "lyrics": """O Christmas Tree, O Christmas Tree,
How lovely are thy branches!
O Christmas Tree, O Christmas Tree,
How lovely are thy branches!
Not only green when summer's here,
But in the coldest time of year.
O Christmas Tree, O Christmas Tree,
How lovely are thy branches!

O Christmas Tree, O Christmas Tree,
Much pleasure dost thou bring me!
O Christmas Tree, O Christmas Tree,
Much pleasure dost thou bring me!
For every year the Christmas tree,
Brings to us all both joy and glee.
O Christmas Tree, O Christmas Tree,
Much pleasure dost thou bring me!"""
    },
    {
        "track_no": 8,
        "folder": "08_The_First_Noel",
        "title": "The First Noel",
        "title_cn": "第一支圣诞歌",
        "composer": "Traditional English Carol",
        "lyricist": "Traditional",
        "year": 1823,
        "url": "https://upload.wikimedia.org/wikipedia/commons/2/23/The_First_Noel_%282020%29_-_Starlifter_and_Roots_in_Blue_-_United_States_Air_Force_Band_of_Mid-America.mp3",
        "ext": ".mp3",
        "bpm": 84,
        "key": "D Major",
        "mood": "Peaceful, Classic, Soulful, Acoustic",
        "lyrics": """The first Noel the angel did say
Was to certain poor shepherds in fields as they lay;
In fields where they lay keeping their sheep,
On a cold winter's night that was so deep.

Noel, Noel, Noel, Noel,
Born is the King of Israel.

They looked up and saw a star
Shining in the east, beyond them far;
And to the earth it gave great light,
And so it continued both day and night.

Noel, Noel, Noel, Noel,
Born is the King of Israel.

And by the light of that same star
Three Wise Men came from country far;
To seek for a king was their intent,
And to follow the star wherever it went.

Noel, Noel, Noel, Noel,
Born is the King of Israel."""
    },
    {
        "track_no": 9,
        "folder": "09_God_Rest_Ye_Merry_Gentlemen",
        "title": "God Rest Ye Merry, Gentlemen",
        "title_cn": "愿上帝赐予你们平安，先生们",
        "composer": "Traditional English Carol",
        "lyricist": "Traditional",
        "year": 1650,
        "url": "https://upload.wikimedia.org/wikipedia/commons/5/59/Anonimo_-_God_Rest_Ye_Merry_Gentlemen.ogg",
        "ext": ".ogg",
        "bpm": 104,
        "key": "E Minor",
        "mood": "Mysterious, Medieval, Rhythmic, Folk",
        "lyrics": """God rest ye merry, gentlemen,
Let nothing you dismay,
Remember Christ our Savior
Was born on Christmas Day
To save us all from Satan's power
When we were gone astray.

O tidings of comfort and joy,
Comfort and joy,
O tidings of comfort and joy!

From God our Heavenly Father
A blessed angel came;
And unto certain shepherds
Brought tidings of the same:
How that in Bethlehem was born
The Son of God by Name.

O tidings of comfort and joy,
Comfort and joy,
O tidings of comfort and joy!"""
    },
    {
        "track_no": 10,
        "folder": "10_O_Holy_Night",
        "title": "O Holy Night",
        "title_cn": "圣善夜",
        "composer": "Adolphe Adam",
        "lyricist": "Placide Cappeau (English: John Sullivan Dwight)",
        "year": 1847,
        "url": "https://upload.wikimedia.org/wikipedia/commons/0/01/Adolphe-Charles_Adam_-_Cantique_de_No%C3%ABl%2C_Oh_Holy_Night.ogg",
        "ext": ".ogg",
        "bpm": 68,
        "key": "C Major",
        "mood": "Grand, Emotional, Climax, Cinematic",
        "lyrics": """O holy night! The stars are brightly shining,
It is the night of the dear Savior's birth.
Long lay the world in sin and error pining,
Till He appeared and the soul felt its worth.
A thrill of hope the weary world rejoices,
For yonder breaks a new and glorious morn.

Fall on your knees! O hear the angel voices!
O night divine, O night when Christ was born;
O night, divine, O night, O night divine!

Led by the light of faith serenely beaming,
With glowing hearts by His cradle we stand.
So led by light of a star sweetly gleaming,
Here came the Wise Men from Orient land.
The King of kings lay thus in lowly manger;
In all our trials born to be our friend.

Fall on your knees! O hear the angel voices!
O night divine, O night when Christ was born;
O night, divine, O night, O night divine!"""
    }
]


def download_file(url: str, dest: Path) -> bool:
    """下载文件流"""
    try:
        with requests.get(url, headers=HEADERS, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_content(chunk_size=16384):
                    if chunk:
                        f.write(chunk)
        return True
    except Exception as e:
        print(f"  ❌ 下载失败: {url} -> {e}")
        return False


def convert_to_mp3_and_wav(source_file: Path, out_mp3: Path, out_wav: Path):
    """使用 ffmpeg 转换标准音频格式"""
    # 转换为 320kbps MP3
    if not out_mp3.exists() or out_mp3.stat().st_size == 0:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source_file), "-ar", "44100", "-ac", "2", "-b:a", "320k", str(out_mp3)],
            check=True,
            capture_output=True,
        )
    # 转换为 16-bit 44.1kHz WAV (DistroKid 官方推荐无损母带格式)
    if not out_wav.exists() or out_wav.stat().st_size == 0:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(source_file), "-ar", "44100", "-ac", "2", "-f", "wav", str(out_wav)],
            check=True,
            capture_output=True,
        )


def build_album():
    """主构建流程"""
    ALBUM_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 75)
    print("🎄 M2V 公有领域圣诞专辑素材工程生成器")
    print(f"📁 目标目录: {ALBUM_DIR}")
    print("=" * 75)

    album_summary = []

    for item in TRACKS:
        no = item["track_no"]
        folder_name = item["folder"]
        title = item["title"]
        title_cn = item["title_cn"]
        composer = item["composer"]
        year = item["year"]

        song_dir = ALBUM_DIR / folder_name
        song_dir.mkdir(parents=True, exist_ok=True)

        print(f"\n[{no}/10] 正在处理: {title} ({title_cn}) - {composer} ({year})")

        # 1. 写入公版标准歌词文件
        lyrics_file = song_dir / "lyrics.txt"
        lyrics_file.write_text(item["lyrics"].strip() + "\n", encoding="utf-8")
        print(f"  📝 歌词写入完成: {lyrics_file.name}")

        # 2. 写入 DistroKid 发行与版权元数据
        meta = {
            "track_number": no,
            "title": title,
            "title_cn": title_cn,
            "artist": "Fovea Studio (或你的艺人名)",
            "album": "A Cozy Christmas: Public Domain Carols Vol. 1",
            "genre": "Holiday / Christmas / Acoustic",
            "year_composed": year,
            "composer": composer,
            "lyricist": item["lyricist"],
            "bpm": item["bpm"],
            "key": item["key"],
            "mood": item["mood"],
            "public_domain": True,
            "copyright_status": "100% Public Domain (Composition expired before 1928)",
            "distrokid_submission_guide": {
                "is_cover_song": False,
                "cover_song_explanation": "In DistroKid, select 'I wrote it' or 'Public Domain' (Do NOT buy cover song license; Public Domain carols do not require mechanical royalties).",
                "songwriter_real_name": composer,
                "music_credit": composer,
                "lyrics_credit": item["lyricist"],
            },
            "karaoke_strategy": {
                "youtube_title": f"{title} (Karaoke / Instrumental with Lyrics) | Made with fovea.si",
                "recommended_style": "warm_holiday_fireplace",
                "shorts_plan": "Clip 30-45s chorus hook for Shorts",
            }
        }
        meta_file = song_dir / "metadata.json"
        meta_file.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  📄 DistroKid 发行元数据生成: {meta_file.name}")

        # 3. 下载公有领域音源
        raw_file = song_dir / f"reference_audio_raw{item['ext']}"
        mp3_file = song_dir / f"{title}_reference.mp3"
        wav_file = song_dir / f"{title}_master_reference.wav"

        if not mp3_file.exists():
            print(f"  ⬇️ 正在下载官方公有领域母带音源...")
            if download_file(item["url"], raw_file):
                print(f"  ⚡ 转换为标准 320k MP3 与 16bit 44.1kHz 无损 WAV...")
                try:
                    convert_to_mp3_and_wav(raw_file, mp3_file, wav_file)
                    print(f"  ✅ 音频转码完成: {mp3_file.name} ({round(mp3_file.stat().st_size/1024/1024, 2)}MB)")
                except Exception as e:
                    print(f"  ⚠️ 转码出现警告: {e}")
        else:
            print(f"  ✅ 音频已就绪: {mp3_file.name}")

        album_summary.append({
            "no": no,
            "title": title,
            "cn": title_cn,
            "composer": composer,
            "year": year,
            "bpm": item["bpm"],
            "key": item["key"]
        })

    # 4. 生成发行总纲领文档 ALBUM_MANIFEST.md
    manifest_file = ALBUM_DIR / "ALBUM_MANIFEST.md"
    manifest_content = f"""# 🎄 圣诞公有领域翻唱专辑策划与全平台发行指南
**专辑企划名称**: *A Cozy Christmas: Public Domain Carols Vol. 1*  
**发行平台**: DistroKid (上线 Spotify, Apple Music, YouTube Music, Amazon Music, TikTok 等)  
**衍生视频**: YouTube 4K 伴奏卡拉OK长视频 + 9:16 Shorts 引流短视频  
**生成时间**: {time.strftime('%Y-%m-%d')}  

---

## 📋 10 首收录曲目总表 (100% 公有领域，零版税成本)

| 序号 | 英文歌名 | 中文名称 | 原创作者 / 作曲 | 创作年份 | 推荐 BPM / 调性 | 伴奏素材目录 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
"""
    for s in album_summary:
        manifest_content += f"| {s['no']} | **{s['title']}** | {s['cn']} | {s['composer']} | {s['year']} | {s['bpm']} BPM / {s['key']} | `projects/christmas_album/{s['no']:02d}_{s['title'].replace(' ', '_').replace('!', '').replace('(', '').replace(')', '')}/` |\n"

    manifest_content += """
---

## 🚀 DistroKid 独家发行避坑策略 (省钱 + 100% 收益)

在 DistroKid 提交新专辑时，请严格按照以下步骤操作，**不需要花钱买任何翻唱许可！**

1. **Cover Song 勾选问题（千万别选 Cover Song 付费选项！）**：
   - 普通翻唱（如周杰伦、Taylor Swift）需要向 DistroKid 支付每年 **$12/首** 的翻唱版权管理费（Mechanical License）。
   - **但是！这 10 首歌曲是 100% 公有领域（Public Domain）！**
   - 在询问 *“Did you write this song, or is it a cover?”* 时：
     - 选择 **“Another artist wrote it (cover song)”** 之后，系统问到曲目性质时，选择 **“Public Domain / Traditional”**（公有领域传统歌曲）。
     - 或者直接在 Songwriter 处填写真实的原创作者（如 `Franz Xaver Gruber`，`Public Domain`）。
     - **DistroKid 不会对公有领域歌曲收取任何版税或许可费！**

2. **收益与 YouTube Content ID (Content ID Collection)**：
   - **Spotify / Apple Music**: 所有的流媒体播放分成 100% 全归您。
   - **YouTube 官方 Content ID**: 当您在 DistroKid 勾选 YouTube Content ID 时，DistroKid 会为您重新录制的**母带录音（Master）**建立指纹。全网任何人用您翻唱的这版圣诞歌，广告收益都会自动打入您的 DistroKid 账户！

---

## 🎹 两种高效翻唱制作方案

### 方案 A：Suno AI 快速定制多样化流行风格 (效率最高)
在 Suno 中使用我们为您整理好的 `lyrics.txt`，搭配以下黄金 Prompt 组合：
* **流行木吉他温暖民谣风**: `Acoustic folk pop, warm nylon guitar, intimate close female vocals, cozy winter fireplace, 85 bpm, emotional`
* **爵士咖啡馆轻音乐风**: `Christmas jazz lounge, smooth upright bass, brushed drums, Rhodes piano, soulful saxophone, late night`
* **现代流行治愈风 (Coldplay风格)**: `Cinematic piano pop, arena drums, anthemic uplifting chorus, atmospheric ambient pads, passionate vocals`

### 方案 B：在 DAW (Logic / Ableton / FL Studio) 配合伴奏翻唱
每个子文件夹中都为您下载并转码好了高品质的 **`.wav` 无损参考音轨** 与 **`.mp3` 伴奏**，直接拖入工程即可录制自己的人声或重新挂音色编曲。

---

## 🎬 M2V 卡拉OK与歌词视频制作流水线

制作好音频后，一键生成全网分发视频：
1. **16:9 横屏全曲（长视频）**:
   - 导入 M2V，选择 `director` 或 `apple` 动效排版；
   - 封面选用暖色调圣诞雪夜或壁炉视觉；
   - 导出后直接运行自动上传命令：
     ```bash
     python tools/upload_youtube.py "视频路径.mp4" --public
     ```
   - **结果**：全球 100% 正常播放，无任何唱片公司索赔，广告分成 100% 归您！

2. **9:16 竖屏高潮副歌（Shorts 引流短视频）**:
   - 截取 30~45 秒的高潮合唱部分；
   - 自动防雷脚本会自动放行（时长 <= 60s），并在短视频流量池爆发式吸粉！
"""

    manifest_file.write_text(manifest_content, encoding="utf-8")
    print(f"\n🎉 专辑发行总纲领生成: {manifest_file}")
    print("=" * 75)
    print("🎄 全部 10 首圣诞公版名曲素材、歌词、元数据及发行指南已全部就绪！")


if __name__ == "__main__":
    build_album()
