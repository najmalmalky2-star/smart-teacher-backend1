import os
import json
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from groq import Groq
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="المعلم الذكي - المحرك السحابي")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# قراءة مفاتيح البيئة مع طباعة للتحقق
GROQ_KEY = os.getenv("GROQ_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

print(f"🔍 فحص الإعدادات: GROQ_KEY موجود؟ {bool(GROQ_KEY)} | SUPABASE موجود؟ {bool(SUPABASE_KEY)}")

# تهيئة Groq
groq_client = None
if GROQ_KEY:
    try:
        groq_client = Groq(api_key=GROQ_KEY)
        print("✅ تم الاتصال بـ Groq بنجاح")
    except Exception as e:
        print(f"❌ خطأ تهيئة Groq: {e}")

# تهيئة Supabase
supabase = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ تم الاتصال بـ Supabase بنجاح")
    except Exception as e:
        print(f"❌ خطأ تهيئة Supabase: {e}")

cache_memory = {}

class SignedPayload(BaseModel):
    user_id: str
    base_id: str
    request_text: str


def get_rule_by_id(base_id: str, user_id: str) -> str:
    if base_id in cache_memory:
        return cache_memory[base_id]

    if supabase:
        try:
            response = supabase.table("learning_rules").select("rule_text").eq("base_id", base_id).execute()
            if response.data:
                rule_text = response.data[0]["rule_text"] if isinstance(response.data, list) else response.data["rule_text"]
                cache_memory[base_id] = rule_text
                return rule_text
        except Exception as e:
            print(f"⚠️ فشل الجلب من Supabase (سيتم استخدام الافتراضي): {e}")

    return "أسلوب تعليمي مبسط يعتمد على الشرح المباشر والأمثلة العملية."


def background_smart_analyzer(user_id: str, base_id: str, current_rule: str, query: str, response: str):
    if not groq_client or not supabase:
        return
    try:
        analysis_prompt = f"""
        بصفتك خبيراً سلوكياً تربوياً، ادرس التفاعل التالي واكتب القاعدة المحدثة ومقاييس الطالب الأكاديمية.
        [الملف الحالي]: "{current_rule}"
        [سؤال الطالب]: "{query}"
        [رد المعلم]: "{response}"

        أعطني النتيجة بصيغة JSON حصراً تحتوي على المفاتيح: "updated_rule" و "metrics".
        """
        
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "أنت خبير تحليل سلوكي وترجع المخرجات بصيغة JSON فقط."},
                {"role": "user", "content": analysis_prompt}
            ],
            response_format={"type": "json_object"}
        )
        
        cleaned_text = completion.choices[0].message.content
        data = json.loads(cleaned_text)

        new_rule = data.get("updated_rule", current_rule)
        new_metrics = data.get("metrics", {})

        cache_memory[base_id] = new_rule

        supabase.table("learning_rules").update({
            "rule_text": new_rule,
            "academic_metrics": new_metrics
        }).eq("user_id", user_id).execute()
        print("✅ تم تحديث ملف التعلم في الخلفية بنجاح.")

    except Exception as e:
        print(f"❌ خطأ في تحليل الخلفية: {e}")


@app.post("/api/v1/teacher")
async def smart_teacher_endpoint(payload: SignedPayload, background_tasks: BackgroundTasks):
    print(f"📥 استلام طلب جديد من الطالب: {payload.user_id} | النص: {payload.request_text}")

    if not groq_client:
        print("❌ خطأ: لم يتم العثور على GROQ_API_KEY في السيرفر!")
        raise HTTPException(status_code=500, detail="مفتاح الذكاء الاصطناعي غير معرف على السيرفر.")

    # 1. جلب النمط التعليمي
    user_rule = get_rule_by_id(payload.base_id, payload.user_id)
    print(f"📖 النمط التعليمي المعتمد: {user_rule[:50]}...")

    try:
        # 2. إرسال الطلب إلى الذكاء الاصطناعي
        print("🤖 جاري إرسال الطلب إلى Groq (Llama-3.1)...")
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": f"أنت المعلم الشخصي لهذا الطالب. التزم بالأسلوب التالي: {user_rule}"},
                {"role": "user", "content": payload.request_text}
            ],
            temperature=0.7
        )

        answer_text = completion.choices[0].message.content.strip()
        print(f"💡 تم توليد الإجابة بنجاح! الطول: {len(answer_text)} حرف.")

        # 3. تشغيل تحليل الخلفية
        background_tasks.add_task(
            background_smart_analyzer,
            user_id=payload.user_id,
            base_id=payload.base_id,
            current_rule=user_rule,
            query=payload.request_text,
            response=answer_text
        )

        # 4. إرجاع النتيجة بتنسيق متعدد المفاتيح لضمان قراءته من تطبيق الطالب
        return {
            "status": "success",
            "recipient_student": payload.user_id,
            "answer": answer_text,
            "response": answer_text,
            "text": answer_text
        }

    except Exception as e:
        print(f"❌ خطأ أثناء الاتصال بالذكاء الاصطناعي: {e}")
        raise HTTPException(status_code=500, detail=f"حدث خطأ في محرك الذكاء الاصطناعي: {str(e)}")


@app.get("/")
async def root():
    return {"status": "healthy", "service": "Smart Teacher Backend"}
