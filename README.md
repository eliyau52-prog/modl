# מתמלל מקומי

אפליקציית דסקטופ (Windows) לתמלול הקלטות: faster-whisper מתמלל, ו-Qwen 2.5 Instruct (קובץ GGUF) מנקה או מסכם. הכול נטען ישירות בתוך התוכנה, בלי שרת ובלי כתובות.

## הרצה מקומית
```
pip install -r requirements.txt
python app.py
```

## בנייה ל-EXE דרך GitHub
דחיפה ל-`main` מפעילה את `.github/workflows/build.yml`. הקובץ `Transcriber-windows.zip` מופיע ב-Actions תחת Artifacts. דחיפת תג `v1.0.0` מפרסמת אותו גם ב-Releases.

## מודלים (לא נכללים ב-EXE)
- **Whisper**: בשדה "מודל תמלול" מזינים `large-v3` / `medium` / `small`. המודל יורד פעם אחת מ-Hugging Face בהרצה הראשונה, או שבוחרים תיקיית מודל CTranslate2 מקומית.
- **Qwen 2.5 Instruct**: מורידים קובץ `.gguf` (למשל `qwen2.5-7b-instruct-q4_k_m.gguf`) ובוחרים אותו בהגדרות.

ההגדרות נשמרות ב-`config.json` ליד ה-EXE.
