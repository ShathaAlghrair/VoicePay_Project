# 🎙️ VoicePay — Voice-Controlled Banking Assistant

![VoicePay Architecture](banner%20(1).png)

**VoicePay** is a voice-first banking assistant that lets users check their balance, transfer money, and pay bills entirely by speaking in **Arabic**. It combines speech recognition, Arabic NLP, and voice biometrics to turn a spoken sentence into a secure, executed transaction — with a spoken confirmation back.

---

## ✨ Features

- 🗣️ **Voice-driven banking** — balance inquiries, peer-to-peer transfers, and bill payments, all by voice
- 🔐 **Voice authentication** — verifies the speaker's identity using voice biometrics before executing sensitive actions
- 🧠 **Arabic Named Entity Recognition** — extracts amounts, recipients, and bill types from natural Arabic speech using a custom-trained spaCy NER model
- 🔊 **Natural spoken responses** — replies are generated dynamically in Arabic via text-to-speech
- 👥 **Contact management** — add and manage saved recipients for transfers
- 📱 **Cross-platform mobile app** — built with Flutter

---

## 🏗️ Architecture

1. **Voice Input** — the mobile app records the user's spoken request.
2. **Speech-to-Text** — audio is transcribed using the Deepgram API.
3. **Arabic NER** — a spaCy-based NER model extracts intent details (amount, recipient, bill type) from the transcribed Arabic text.
4. **Voice ID Check** — the speaker's voice is verified against their enrolled voiceprint using speaker-embedding models before any sensitive action proceeds.
5. **Backend Processing** — a FastAPI backend validates the request against the database (balance checks, recipient lookup, bill status) and executes the transaction.
6. **Spoken Reply** — a natural-language Arabic response is generated and converted to speech to confirm the result to the user.

---

## 🛠️ Tech Stack

| Layer | Technology |
| :--- | :--- |
| **Mobile App** | Flutter (Dart) |
| **Backend API** | FastAPI, SQLAlchemy, SQLite |
| **Speech-to-Text** | Deepgram SDK |
| **Text-to-Speech** | edge-tts (Arabic) |
| **NLP / NER** | spaCy, PyArabic |
| **Voice Biometrics** | Resemblyzer, librosa, pydub |
| **Auth & Security** | bcrypt, passlib |
| **Deployment** | Docker, Hugging Face Spaces |

---

## 📁 Project Structure

```
VoicePay/
├── app/                  # Core application logic
├── backend/               # FastAPI backend (API, DB models, business logic)
├── mobile/                 # Flutter mobile app
├── voicepay_app/            # Flutter mobile app (active/updated version)
├── models/                   # Trained models (NER, voice ID)
├── NER/NERspaCy/               # spaCy Arabic NER training pipeline
├── data/ner/                     # NER training/annotation data
├── research/                       # Experiments and prototyping notebooks
├── temp_test_audio/                  # Sample audio for local testing
├── .github/workflows/                  # CI/CD pipelines
├── Dockerfile                            # Container build for deployment (Hugging Face Spaces)
├── run_backend.sh                          # Local backend launch script
├── debug_ner.py                              # NER debugging utility
├── test_registration_flow.py                   # Registration flow test script
├── tts_responses.md                               # Full catalog of Arabic TTS responses & triggers
└── requirements.txt                                 # Python dependencies
```

---

## 🚀 Getting Started

### Backend

**Requirements:** Python 3.10, `ffmpeg` (for audio processing)

1. Clone the repository and install dependencies:
   ```bash
   pip install -r requirements.txt
   python -m spacy download en_core_web_sm
   ```
2. Run the backend locally:
   ```bash
   ./run_backend.sh
   ```
   This starts the FastAPI server using `app.api.main`.

3. **Docker (recommended for deployment):**
   ```bash
   docker build -t voicepay .
   docker run -p 7860:7860 voicepay
   ```
   The API will be available on port `7860` (matching the Hugging Face Spaces convention this project is configured for).

### Mobile App

1. Navigate to the Flutter app directory (`voicepay_app/`).
2. Install dependencies and run:
   ```bash
   flutter pub get
   flutter run
   ```

---

## 🗣️ Example Voice Interactions

VoicePay understands natural Arabic requests such as:
- *"حوّل ٥٠ دينار لأحمد"* → confirms and executes a transfer to a saved contact
- *"شو رصيدي؟"* → reads back the current balance
- *"ادفع فاتورة الكهرباء"* → checks bill status and confirms payment

The full set of Arabic response templates — covering errors, confirmations, balance replies, transfers, bill payments, and contact management — is documented in [`tts_responses.md`](tts_responses.md).

---

## 🔒 Security Notes

- Passwords are hashed with `bcrypt`/`passlib`.
- Sensitive actions (transfers, bill payments) require successful voice identity verification before execution.
- This project is a prototype/research system — it is **not** production-hardened for handling real financial transactions.

---

## 🔮 Future Work

- Expand NER coverage for more complex, multi-entity Arabic requests
- Add multi-factor confirmation for high-value transfers
- Support additional dialects beyond standard/colloquial Arabic used in training data
