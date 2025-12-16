import os, json, datetime
from googleapiclient.discovery import build
import isodate
from openai import OpenAI

SKIP_SUMMARY = True
YOUTUBE_API_KEY = os.environ["YOUTUBE_API_KEY"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

KEYWORDS = [
  "LLM podcast", "large language model podcast", "AI podcast LLM",
  "大模型 播客", "GPT podcast", "RAG podcast", "AI agents podcast"
]

MIN_DURATION_SECONDS = 10 * 60
MAX_PER_KEYWORD = 8

client = OpenAI(api_key=OPENAI_API_KEY)

def iso_day_range_utc(day: datetime.date):
    start = datetime.datetime(day.year, day.month, day.day, tzinfo=datetime.timezone.utc)
    end = start + datetime.timedelta(days=1)
    return start.isoformat().replace("+00:00", "Z"), end.isoformat().replace("+00:00", "Z")

def yt():
    return build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

def search_videos(service, published_after, published_before):
    video_ids = set()
    for q in KEYWORDS:
        req = service.search().list(
            q=q,
            part="id",
            type="video",
            maxResults=MAX_PER_KEYWORD,
            order="date",
            publishedAfter=published_after,
            publishedBefore=published_before
        )
        resp = req.execute()
        for item in resp.get("items", []):
            video_ids.add(item["id"]["videoId"])
    return list(video_ids)

def get_video_details(service, video_ids):
    if not video_ids:
        return []
    req = service.videos().list(
        part="snippet,contentDetails",
        id=",".join(video_ids),
        maxResults=50
    )
    resp = req.execute()
    out = []
    for v in resp.get("items", []):
        duration = isodate.parse_duration(v["contentDetails"]["duration"]).total_seconds()
        out.append({
            "video_id": v["id"],
            "title": v["snippet"]["title"],
            "description": v["snippet"].get("description", ""),
            "channel_title": v["snippet"]["channelTitle"],
            "published_at": v["snippet"]["publishedAt"],
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "duration_seconds": int(duration),
        })
    return out

def summarize_to_json(title, description):
    prompt = f"""
你是技术播客速读编辑。请输出严格 JSON：
{{
  "summary": "不超过120字中文摘要",
  "bullets": ["3-5条要点，每条<=20字"],
  "score": 0.0
}}
score含义：与大模型/LLM相关性(0-1)

标题：{title}
简介：{description[:2000]}
"""

    resp = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "你只输出严格JSON，不要输出任何额外文字。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )

    text = resp.choices[0].message.content.strip()
    return json.loads(text)

def load_existing(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)

def save(path, items):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)

def main():
    service = yt()
    day = datetime.datetime.now(datetime.timezone.utc).date()
    published_after, published_before = iso_day_range_utc(day)

    existing = load_existing("data/items.json")
    existing_ids = set(x["video_id"] for x in existing)

    video_ids = search_videos(service, published_after, published_before)
    details = get_video_details(service, video_ids)

    new_items = []
    for d in details:
        if d["video_id"] in existing_ids:
            continue
        if d["duration_seconds"] < MIN_DURATION_SECONDS:
            continue

        s = summarize_to_json(d["title"], d["description"])
        if SKIP_SUMMARY:
            d["summary"] = ""
            d["bullets"] = []
            d["score"] = 0.8  # 先给个默认值，保证能入库
        else:
            s = summarize_to_json(d["title"], d["description"])
            if float(s.get("score", 0)) < 0.55:
                continue
            d["summary"] = s.get("summary", "")
            d["bullets"] = s.get("bullets", [])
            d["score"] = float(s.get("score", 0))

    merged = new_items + existing
    merged.sort(key=lambda x: x["published_at"], reverse=True)
    save("data/items.json", merged[:300])

    print(f"added={len(new_items)} total={len(merged)}")

if __name__ == "__main__":
    main()
