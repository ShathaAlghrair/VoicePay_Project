from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session
import bcrypt
import json
import os
import random
import re
from datetime import datetime, timedelta
from typing import List

# Relative imports
from app.db.database import SessionLocal
from app.db.models import PersonAccount, AllowedRecipient, Bill
from app.core.biometrics.challenge import generate_challenge
from app.core.biometrics.verifier import SpeakerVerifier

router = APIRouter(tags=["User Management"])
speaker_verifier = SpeakerVerifier()

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# --- Pydantic Models ---
class LoginRequest(BaseModel):
    email: str
    password: str

class RegisterRequest(BaseModel):
    full_name: str
    email: str
    password: str
    phone_number: str
    bank_name: str

class AddRecipientRequest(BaseModel):
    user_pid: int
    nickname: str
    bank_name: str
    reference_number: str
    phone_number: str

class UpdateRecipientRequest(BaseModel):
    id: int # The AllowedRecipient.id
    nickname: str
    bank_name: str
    reference_number: str
    phone_number: str

class RemoveRecipientRequest(BaseModel):
    user_pid: int
    recipient_pid: int # We'll use the ID of the record

class VerifyResetCodeRequest(BaseModel):
    user_pid: int
    code: str

# --- Management Endpoints ---

@router.post("/register")
async def register(request: RegisterRequest, db: Session = Depends(get_db)):
    # 1. Check if email already exists
    existing_user = db.query(PersonAccount).filter(PersonAccount.email == request.email).first()
    if existing_user:
        raise HTTPException(status_code=400, detail="البريد الإلكتروني مسجل بالفعل.")
    
    # 2. Generate unique reference number
    ref_num = f"VP-{random.randint(100000, 999999)}"
    while db.query(PersonAccount).filter(PersonAccount.reference_number == ref_num).first():
        ref_num = f"VP-{random.randint(100000, 999999)}"
    
    # 3. Hash password
    hashed_pw = bcrypt.hashpw(request.password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # 4. Create user
    new_user = PersonAccount(
        full_name=request.full_name,
        email=request.email,
        password=hashed_pw,
        phone_number=request.phone_number,
        bank_name=request.bank_name,
        reference_number=ref_num,
        balance=1000.0
    )
    
    try:
        db.add(new_user)
        db.commit()
        db.refresh(new_user)
        return {
            "status": "success",
            "message": "تم إنشاء الحساب بنجاح. يرجى إكمال تسجيل الصوت.",
            "user_id": new_user.PID
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/enrollment-challenges")
async def get_enrollment_challenges():
    challenges = [generate_challenge() for _ in range(6)]
    return challenges

@router.post("/enroll-voice")
async def enroll_voice(user_id: int, files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    if len(files) != 6:
        raise HTTPException(status_code=400, detail="يجب تقديم 6 عينات صوتية بالضبط.")
    
    user = db.query(PersonAccount).filter(PersonAccount.PID == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود.")
    
    audio_samples = []
    for file in files:
        content = await file.read()
        audio_samples.append(content)
    
    result = speaker_verifier.enroll(audio_samples)
    if result["status"] == "success":
        user.voiceprint = json.dumps(result["voiceprint"])
        db.commit()
        return {"status": "success", "message": "تم تسجيل بصمة الصوت بنجاح!"}
    else:
        raise HTTPException(status_code=400, detail=result["message"])

@router.get("/user/{user_pid}")
async def get_user_details(user_pid: int, db: Session = Depends(get_db)):
    user = db.query(PersonAccount).filter(PersonAccount.PID == user_pid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return {
        "pid": user.PID,
        "full_name": user.full_name,
        "email": user.email,
        "balance": user.balance,
        "bank_name": user.bank_name,
        "reference_number": user.reference_number
    }

@router.post("/login")
async def api_login(request: LoginRequest, db: Session = Depends(get_db)):
    try:
        user = db.query(PersonAccount).filter(PersonAccount.email == request.email).first()
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        
        # Verify password using direct bcrypt call (passlib is broken with bcrypt 5.0.0)
        password_bytes = request.password.encode('utf-8')
        hash_bytes = user.password.encode('utf-8')
        if not bcrypt.checkpw(password_bytes, hash_bytes):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password")
        
        # Check if voiceprint exists
        if not user.voiceprint:
            return {
                "status": "needs_enrollment",
                "message": "يرجى إكمال تسجيل بصمة الصوت أولاً.",
                "user": {
                    "pid": user.PID,
                    "full_name": user.full_name,
                    "email": user.email
                }
            }

        # New: Instead of success, return needs_challenge for 2FA
        challenge = generate_challenge()
        return {
            "status": "needs_challenge",
            "message": "يرجى تأكيد هويتك من خلال التحدث بالأرقام الظاهرة.",
            "challenge": challenge,
            "user_pid": user.PID
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/verify-login-challenge")
async def verify_login_challenge(
    request: Request,
    user_pid: int,
    challenge_code: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Verifies both voiceprint and the spoken digits for login."""
    try:
        audio_data = await file.read()
        user = db.query(PersonAccount).filter(PersonAccount.PID == user_pid).first()
        if not user or not user.voiceprint:
            raise HTTPException(status_code=404, detail="User not found or not enrolled")

        # 1. Verify Voiceprint (Speaker Verification)
        # We use the pipeline from app.state
        pipeline = request.app.state.pipeline
        voice_result = pipeline.speaker_verifier.verify(user_pid, audio_data, db_voiceprint=user.voiceprint)
        
        if voice_result["status"] != "success":
            return {
                "status": "failed",
                "reason": "voice_mismatch",
                "message": "بصمة الصوت غير متطابقة. يرجى المحاولة مرة أخرى."
            }

        # 2. Verify Challenge Content (STT)
        stt_client = request.app.state.stt_client
        response = stt_client.listen.v1.media.transcribe_file(
            request={'buffer': audio_data},
            model="nova-2",
            language="ar",
            smart_format=True,
        )
        transcribed_text = response.results.channels[0].alternatives[0].transcript.strip()
        print(f"DEBUG: Challenge Code: {challenge_code}")
        print(f"DEBUG: Transcribed Text: '{transcribed_text}'")
        
        # 1. Direct Digit Extraction
        digits_found = re.findall(r'\d', transcribed_text)
        found_code = "".join(digits_found)
        print(f"DEBUG: Found Digits: {found_code}")
        
        is_challenge_ok = (found_code == challenge_code)
        
        # 2. Fallback: Word-based checking (Very common for Arabic)
        if not is_challenge_ok:
            from app.core.biometrics.challenge import DIGITS_AR
            ALT_DIGITS_AR = {
                "0": ["صفر", "زيرو"],
                "1": ["واحد", "واحد"],
                "2": ["اثنان", "اثنين", "تنين"],
                "3": ["ثلاثة", "تلاتة", "تلات"],
                "4": ["أربعة", "اربعة", "اربع"],
                "5": ["خمسة", "خمسة", "خمس"],
                "6": ["ستة", "ستة", "ست"],
                "7": ["سبعة", "سبعة", "سبع"],
                "8": ["ثمانية", "تمانية", "تمان"],
                "9": ["تسعة", "تسعة", "تسع"],
            }
            
            matches = 0
            # Normalize transcribed text for word matching
            norm_text = transcribed_text.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
            
            for digit in challenge_code:
                # Check standard word
                standard_word = DIGITS_AR[digit].replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
                if standard_word in norm_text:
                    matches += 1
                    continue
                
                # Check alternative words (common dialects/variations)
                if digit in ALT_DIGITS_AR:
                    found_alt = False
                    for alt in ALT_DIGITS_AR[digit]:
                        alt_norm = alt.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")
                        if alt_norm in norm_text:
                            found_alt = True
                            break
                    if found_alt:
                        matches += 1

            # If at least 5 out of 6 digits match, we consider it valid (noise tolerance)
            if matches >= (len(challenge_code) - 1): 
                is_challenge_ok = True

        if not is_challenge_ok:
            # If still failing, check if the transcript is simply empty
            error_msg = f"الأرقام المنطوقة غير صحيحة. (سمعت: {transcribed_text if transcribed_text else 'لا شيء'})"
            if not transcribed_text:
                error_msg = "لم أستطع سماع الأرقام بوضوح، يرجى رفع صوتك أو الاقتراب من الميكروفون."
            
            return {
                "status": "failed",
                "reason": "challenge_mismatch",
                "message": error_msg,
                "transcribed": transcribed_text
            }

        # 3. If both OK, return success with user data
        return {
            "status": "success",
            "message": "تم التحقق من الهوية بنجاح.",
            "user": {
                "pid": user.PID,
                "full_name": user.full_name,
                "email": user.email,
                "balance": user.balance,
                "bank_name": user.bank_name,
                "reference_number": user.reference_number
            }
        }
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

MAIL_USERNAME = os.getenv("MAIL_USERNAME")
MAIL_PASSWORD = os.getenv("MAIL_PASSWORD")
MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
MAIL_PORT = int(os.getenv("MAIL_PORT", 587))

def send_actual_email(to_email: str, subject: str, body: str):
    try:
        msg = MIMEMultipart()
        msg['From'] = MAIL_USERNAME
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(MAIL_SERVER, MAIL_PORT)
        server.starttls()
        server.login(MAIL_USERNAME, MAIL_PASSWORD)
        text = msg.as_string()
        server.sendmail(MAIL_USERNAME, to_email, text)
        server.quit()
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

@router.post("/send-reset-code")
async def send_reset_code(user_pid: int, db: Session = Depends(get_db)):
    user = db.query(PersonAccount).filter(PersonAccount.PID == user_pid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate 6-digit OTP
    code = "".join([str(random.randint(0, 9)) for _ in range(6)])
    user.reset_code = code
    user.reset_code_expires = datetime.utcnow() + timedelta(minutes=15)
    
    db.commit()
    
    # Send actual email
    subject = "VoicePay - Verification Code"
    body = f"Hello {user.full_name},\n\nYour verification code is: {code}\n\nThis code will expire in 15 minutes."
    
    email_sent = send_actual_email(user.email, subject, body)
    
    if email_sent:
        return {"status": "success", "message": "تم إرسال رمز التفعيل إلى بريدك الإلكتروني."}
    else:
        # Fallback to simulation if email fails so user can still test
        print(f"\n[EMAIL FAILED - SIMULATION] To: {user.email}")
        print(f"[EMAIL SIMULATION] Code: {code}\n")
        return {"status": "warning", "message": "فشل إرسال البريد الإلكتروني. تم طباعة الرمز في سجلات الخادم."}

@router.post("/verify-reset-code")
async def verify_reset_code(request: VerifyResetCodeRequest, db: Session = Depends(get_db)):
    user = db.query(PersonAccount).filter(PersonAccount.PID == request.user_pid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if not user.reset_code or user.reset_code != request.code:
        return {"status": "error", "message": "رمز التفعيل غير صحيح."}
    
    if user.reset_code_expires < datetime.utcnow():
        return {"status": "error", "message": "انتهت صلاحية رمز التفعيل."}
    
    # Clear voiceprint and reset code
    user.voiceprint = None
    user.reset_code = None
    user.reset_code_expires = None
    
    db.commit()
    
    return {
        "status": "needs_enrollment", 
        "message": "تم التحقق بنجاح. يرجى إعادة تسجيل بصمة الصوت.",
        "user_id": user.PID
    }

@router.post("/user/update-reference")
async def update_reference_number(user_pid: int, db: Session = Depends(get_db)):
    user = db.query(PersonAccount).filter(PersonAccount.PID == user_pid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Generate new unique reference number
    ref_num = f"VP-{random.randint(100000, 999999)}"
    while db.query(PersonAccount).filter(PersonAccount.reference_number == ref_num).first():
        ref_num = f"VP-{random.randint(100000, 999999)}"
    
    user.reference_number = ref_num
    db.commit()
    return {"status": "success", "message": "تم تحديث رقم المرجع بنجاح.", "reference_number": ref_num}

@router.get("/recipients/{user_pid}")
async def get_recipients(user_pid: int, db: Session = Depends(get_db)):
    user = db.query(PersonAccount).filter(PersonAccount.PID == user_pid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return [
        {
            "id": r.id,
            "pid": r.recipient_pid,
            "nickname": r.nickname,
            "bank_name": r.bank_name,
            "reference_number": r.reference_number,
            "phone_number": r.phone_number
        } 
        for r in user.allowed_contacts
    ]

@router.get("/bills/{user_pid}")
async def get_bills(user_pid: int, db: Session = Depends(get_db)):
    user = db.query(PersonAccount).filter(PersonAccount.PID == user_pid).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    return [
        {
            "id": b.bill_id,
            "name": b.bills_name,
            "cost": b.bills_cost,
            "serves": b.serves,
            "due_date": b.due_date,
            "status": b.paid_status
        }
        for b in user.bills
    ]

@router.post("/recipients/add")
async def add_recipient(request: AddRecipientRequest, db: Session = Depends(get_db)):
    # 1. Check if recipient exists in the main system by reference number
    recipient = db.query(PersonAccount).filter(PersonAccount.reference_number == request.reference_number).first()
    
    if not recipient:
        return {
            "status": "error", 
            "message": "عذراً، لا يوجد مستخدم مسجل بهذا الرقم المرجعي. يرجى التأكد من الرقم والمحاولة مرة أخرى."
        }
    
    # 2. Check if already in the allowed list for this user
    existing = db.query(AllowedRecipient).filter(
        AllowedRecipient.user_pid == request.user_pid,
        AllowedRecipient.reference_number == request.reference_number
    ).first()
    
    if existing:
        return {
            "status": "error",
            "message": "هذا المستلم موجود بالفعل في قائمة جهات الاتصال الخاصة بك."
        }

    new_contact = AllowedRecipient(
        user_pid=request.user_pid,
        recipient_pid=recipient.PID,
        nickname=request.nickname,
        bank_name=request.bank_name,
        reference_number=request.reference_number,
        phone_number=request.phone_number
    )
    
    db.add(new_contact)
    db.commit()
    return {"status": "success", "message": f"تمت إضافة المستلم '{request.nickname}' بنجاح!"}

@router.post("/recipients/update")
async def update_recipient(request: UpdateRecipientRequest, db: Session = Depends(get_db)):
    contact = db.query(AllowedRecipient).filter(AllowedRecipient.id == request.id).first()
    if not contact:
        raise HTTPException(status_code=404, detail="Recipient not found")
    
    contact.nickname = request.nickname
    contact.bank_name = request.bank_name
    contact.reference_number = request.reference_number
    contact.phone_number = request.phone_number
    
    db.commit()
    return {"status": "success", "message": f"تم تحديث المستلم '{request.nickname}' بنجاح!"}

@router.post("/recipients/remove")
async def remove_recipient(request: RemoveRecipientRequest, db: Session = Depends(get_db)):
    contact = db.query(AllowedRecipient).filter(
        AllowedRecipient.user_pid == request.user_pid,
        AllowedRecipient.recipient_pid == request.recipient_pid
    ).first()

    if not contact:
        # Try finding by ID if pid lookup fails
        contact = db.query(AllowedRecipient).filter(AllowedRecipient.id == request.recipient_pid).first()

    if not contact:
        raise HTTPException(status_code=404, detail="المستلم غير موجود")

    db.delete(contact)
    db.commit()
    return {"status": "success", "message": "تم حذف المستلم بنجاح!"}
