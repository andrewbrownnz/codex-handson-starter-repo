import base64
import csv
import io
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import dotenv
from fastapi import Body, FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openai import OpenAI
from PIL import ExifTags, Image
from pydantic import BaseModel, Field

from .utils import create_image

dotenv.load_dotenv()

BACKEND_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BACKEND_DIR.parent / "frontend"
DATA_DIR = BACKEND_DIR / "data"
IMAGE_DIR = DATA_DIR / "images"
DATA_FILE = DATA_DIR / "cards.csv"

COLUMNS = [
    "id",
    "first_name",
    "last_name",
    "company",
    "company_logo_description",
    "email",
    "phone",
    "address",
    "meeting_context",
    "priorities",
    "personal_notes",
    "captured_at",
    "source_image",
    "summary_image",
    "raw_ocr_json",
]


class CardContext(BaseModel):
    meeting_context: str = Field("", description="What was the context of your meeting?")
    priorities: str = Field("", description="What are the priorities of that person?")
    personal_notes: str = Field("", description="Personal things or small talk cues.")


class CardResponse(BaseModel):
    id: str
    first_name: str
    last_name: str
    company: str
    company_logo_description: str
    email: str
    phone: str
    address: str
    meeting_context: str
    priorities: str
    personal_notes: str
    captured_at: str
    source_image_url: Optional[str] = None
    summary_image_url: Optional[str] = None
    raw_ocr_json: str


client = OpenAI()

app = FastAPI(
    title="Executive Business Card Manager",
    description="Upload business cards, extract contact details, capture meeting context, and generate visual summaries.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

app.mount("/media", StaticFiles(directory=IMAGE_DIR), name="media")
if FRONTEND_DIR.exists():
    app.mount("/app", StaticFiles(directory=FRONTEND_DIR), name="app")


def ensure_data_file() -> None:
    if not DATA_FILE.exists():
        with DATA_FILE.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=COLUMNS)
            writer.writeheader()


def parse_json_blob(text: str) -> Dict[str, str]:
    cleaned = text.strip()
    if "```" in cleaned:
        cleaned = cleaned.split("```")
        if len(cleaned) >= 3:
            cleaned = cleaned[1]
        else:
            cleaned = "".join(cleaned)
    if cleaned.startswith("json"):
        cleaned = cleaned[4:]
    try:
        start = cleaned.index("{")
        end = cleaned.rindex("}") + 1
        cleaned = cleaned[start:end]
    except ValueError:
        pass
    return json.loads(cleaned)


def extract_capture_datetime(image_bytes: bytes) -> str:
    try:
        with Image.open(io.BytesIO(image_bytes)) as img:
            exif_data = img.getexif()
            if exif_data:
                for tag_id, value in exif_data.items():
                    tag = ExifTags.TAGS.get(tag_id, tag_id)
                    if tag in {"DateTimeOriginal", "DateTimeDigitized", "DateTime"}:
                        try:
                            parsed = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                            return parsed.replace(tzinfo=timezone.utc).isoformat()
                        except Exception:
                            continue
    except Exception:
        pass
    return datetime.now(timezone.utc).isoformat()


def extract_card_details(image_bytes: bytes, content_type: Optional[str]) -> Dict[str, str]:
    mime_type = content_type or "image/png"
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    data_url = f"data:{mime_type};base64,{b64}"

    messages = [
        {
            "role": "system",
            "content": (
                "You extract business card details. Respond with JSON only and include the keys: "
                "first_name, last_name, company, company_logo_description, email, phone, address."
            ),
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Extract the contact details from this business card. "
                        "Use empty strings for missing values and keep phone numbers exactly as shown."
                    ),
                },
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        },
    ]

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=messages,
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    return parse_json_blob(content)


def save_image(image_bytes: bytes, filename: str) -> str:
    path = IMAGE_DIR / filename
    with path.open("wb") as f:
        f.write(image_bytes)
    return path.name


def serialize_record(record: Dict[str, str]) -> CardResponse:
    source_image_url = f"/media/{record['source_image']}" if record.get("source_image") else None
    summary_image_url = f"/media/{record['summary_image']}" if record.get("summary_image") else None
    fields = {
        k: record.get(k, "")
        for k in CardResponse.model_fields.keys()
        if k not in {"source_image_url", "summary_image_url", "raw_ocr_json"}
    }
    return CardResponse(
        **fields,
        source_image_url=source_image_url,
        summary_image_url=summary_image_url,
        raw_ocr_json=record.get("raw_ocr_json", "{}"),
    )


def load_records() -> List[Dict[str, str]]:
    ensure_data_file()
    with DATA_FILE.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


def write_records(records: List[Dict[str, str]]) -> None:
    ensure_data_file()
    with DATA_FILE.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        for row in records:
            writer.writerow(row)


def update_record(card_id: str, changes: Dict[str, str]) -> Dict[str, str]:
    records = load_records()
    for row in records:
        if row["id"] == card_id:
            row.update(changes)
            write_records(records)
            return row
    raise HTTPException(status_code=404, detail="Card not found")


def summarize_for_image(record: Dict[str, str], context: CardContext) -> str:
    full_name = f"{record.get('first_name', '').strip()} {record.get('last_name', '').strip()}".strip()
    return (
        f"Create a friendly, professional portrait for {full_name or 'this contact'} who works at {record.get('company','unknown company')}. "
        f"Highlight cues from the business card: phone {record.get('phone','n/a')}, email {record.get('email','n/a')}. "
        f"Meeting context: {context.meeting_context}. Priorities: {context.priorities}. Personal details: {context.personal_notes}. "
        "Style: clean, corporate-ready, subtle background with company color hints, photographic realism."
    )


@app.post("/api/cards", response_model=CardResponse)
async def upload_card(file: UploadFile = File(...)):
    if not file:
        raise HTTPException(status_code=400, detail="No file uploaded.")

    image_bytes = await file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    capture_time = extract_capture_datetime(image_bytes)
    extracted = extract_card_details(image_bytes, file.content_type)

    card_id = str(uuid.uuid4())
    source_ext = Path(file.filename or "card.png").suffix or ".png"
    source_image_name = save_image(image_bytes, f"{card_id}_source{source_ext}")

    record = {
        "id": card_id,
        "first_name": extracted.get("first_name", ""),
        "last_name": extracted.get("last_name", ""),
        "company": extracted.get("company", ""),
        "company_logo_description": extracted.get("company_logo_description", ""),
        "email": extracted.get("email", ""),
        "phone": extracted.get("phone", ""),
        "address": extracted.get("address", ""),
        "meeting_context": "",
        "priorities": "",
        "personal_notes": "",
        "captured_at": capture_time,
        "source_image": source_image_name,
        "summary_image": "",
        "raw_ocr_json": json.dumps(extracted, ensure_ascii=False),
    }

    records = load_records()
    records.append(record)
    write_records(records)

    return serialize_record(record)


@app.post("/api/cards/{card_id}/context", response_model=CardResponse)
async def save_context(card_id: str, payload: CardContext = Body(...)):
    record = update_record(
        card_id,
        {
            "meeting_context": payload.meeting_context,
            "priorities": payload.priorities,
            "personal_notes": payload.personal_notes,
        },
    )

    summary_prompt = summarize_for_image(record, payload)
    summary_bytes = create_image(summary_prompt, size="1024x1024")
    summary_image_name = save_image(summary_bytes, f"{card_id}_summary.png")

    record = update_record(card_id, {"summary_image": summary_image_name})
    return serialize_record(record)


@app.get("/api/cards", response_model=List[CardResponse])
async def list_cards():
    records = load_records()
    return [serialize_record(r) for r in records]


@app.get("/api/cards/{card_id}", response_model=CardResponse)
async def get_card(card_id: str):
    for record in load_records():
        if record["id"] == card_id:
            return serialize_record(record)
    raise HTTPException(status_code=404, detail="Card not found")


@app.get("/", response_class=FileResponse)
async def serve_index():
    index_file = FRONTEND_DIR / "index.html"
    if not index_file.exists():
        raise HTTPException(status_code=404, detail="Frontend not built yet.")
    return FileResponse(index_file)
