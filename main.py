import os
import json
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client
from groq import Groq
from dotenv import load_dotenv

# تحميل متغيرات البيئة المحلية إن وجدت
load_dotenv()

# الاتصال بقاعدة البيانات وخدمة الذكاء الاصطناعي عبر Groq
try:
    supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))
    groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
except Exception as e:
    print(f"⚠️ تحذير: تعذر الاتصال المبدئي بالخدمات: {e}")

app = FastAPI(title="المعلم الذكي - المحرك السحابي")

# السماح بالاتصالات الخارجية
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# كاش مؤقت لتسريع الأداء وتقليل الاستعلامات
cache_memory = {}

class SignedPayload(BaseModel):
    user_id: str
    base_id: str
    request_text: str


def get_rule_by_id(base_id: str, user_id: str) -> str:
    if base_id in cache_memory:
        return cache_memory[base_id]

    try:
        response = supabase.table("learning_rules").select("rule_text").eq("base_id", base_id).execute()
        if response.data:
            rule_text = response.data[0]["rule_text"] if isinstance(response.data, list) else response.data["rule_text"]
            cache_memory[base_id] = rule_text
            return rule_text
    except Exception as e:
        print(f"⚠️ تنبيه Supabase: {e}")

    return "أسلوب تعليمي افتراضي يعتمد التبسيط وضرب الأمثلة والقصص."


def background_smart_analyzer(user_id: str, base_id: str, current_rule: str, query: str, response: str):
    try:
        analysis_prompt = f"""
        بصفتك خبيراً سلوكياً تربوياً، ادرس التفاعل التالي وقص القاعدة المحدثة ومقاييس الطالب الأكاديمية.
        [الملف الحالي]: "{current_rule}"
        [سؤال الطالب]: "{query}"
        [رد المعلم]: "{response}"

        أعطني النتيجة بصيغة JSON حصراً تحتوي على المفاتيح التالية:
        1. "updated_rule": نص ملف التعلم الجديد مدمجاً به التطور السلوكي للطالب.
        2. "metrics": تحديث نقاط القوة، الضعف، والتقدم (قاموس JSON).
        """
        
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": "أنت خبير تحليل سلوكي تربوي وترجع المخرجات بأسلوب JSON فقط."},
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

    except Exception as e:
        print(f"❌ خطأ المحلل الذكي: {e}")


@app.post("/api/v1/teacher")
async def smart_teacher_endpoint(payload: SignedPayload, background_tasks: BackgroundTasks):
    user_rule = get_rule_by_id(payload.base_id, payload.user_id)

    try:
        # استدعاء نموذج الذكاء الاصطناعي عبر Groq
        completion = groq_client.chat.completions.create(
            model="llama-3.1-8b-instant",
            messages=[
                {"role": "system", "content": f"أنت المعلم الشخصي لهذا الطالب. التزم الصرامة التامة بملف تعلمه التالي: {user_rule}"},
                {"role": "user", "content": payload.request_text}
            ],
            temperature=0.7
        )

        answer_text = completion.choices[0].message.content.strip()

        # إطلاق عملية التحليل السلوكي في الخلفية
        background_tasks.add_task(
            background_smart_analyzer,
            user_id=payload.user_id,
            base_id=payload.base_id,
            current_rule=user_rule,
            query=payload.request_text,
            response=answer_text
        )

        return {
            "status": "success",
            "recipient_student": payload.user_id,
            "answer": answer_text
        }

    except Exception as e:
        print(f"❌ خطأ الذكاء الاصطناعي عبر Groq: {e}")
        raise HTTPException(status_code=500, detail=f"حدث خطأ أثناء توليد الإجابة: {str(e)}")


@app.get("/")
async def root():
    return {"status": "healthy", "service": "Smart Teacher Backend with Groq"}
