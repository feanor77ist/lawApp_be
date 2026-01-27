from langchain_openai import OpenAIEmbeddings
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI
from django.conf import settings
import time, openai, os, asyncio, json
from langchain_chroma import Chroma
from ml_simulator.settings import BASE_DIR
from .llm_utils import embed_model, llm_model
from typing import Sequence, TypedDict, Annotated, List, Optional
from langchain_core.messages import BaseMessage, HumanMessage, AIMessageChunk, AIMessage
from langgraph.graph import StateGraph, END, START
from langgraph.graph.message import add_messages
from langchain_core.runnables import RunnableConfig
from .context_utils import get_scenario_contents
from asgiref.sync import sync_to_async
from rapidfuzz import fuzz
from pydantic import BaseModel, Field, field_validator


# Pydantic modelleri - JSON structured output için
class KPIItem(BaseModel):
    """KPI değerlendirme item'ı"""
    name: str = Field(description="KPI adı", min_length=1)
    max_score: int = Field(description="Maksimum puan", ge=1, le=100)
    score: int = Field(description="Verilen puan", ge=0)
    rationale: str = Field(description="Puanlama gerekçesi", min_length=10)
    performance: str = Field(description="Detaylı performans açıklaması", min_length=10)
    
    @field_validator('score')
    @classmethod
    def score_must_not_exceed_max(cls, v, info):
        if hasattr(info, 'data') and 'max_score' in info.data and v > info.data['max_score']:
            raise ValueError(f'Score ({v}) cannot exceed max_score ({info.data["max_score"]})')
        return v

class EvalJSON(BaseModel):
    """Değerlendirme JSON çıktısı"""
    kpis: List[KPIItem] = Field(description="KPI değerlendirmeleri", min_items=1)
    strengths: List[str] = Field(description="Güçlü yönler", default=[])
    improvements: List[str] = Field(description="Gelişim alanları", default=[])
    
    @field_validator('kpis')
    @classmethod
    def validate_kpis(cls, v):
        if not v:
            raise ValueError('At least one KPI is required')
        return v

# Helper fonksiyonları
def _sum_total(kpis: List[KPIItem]) -> int:
    """KPI puanlarını toplar"""
    return sum(kpi.score for kpi in kpis)

def _lines_for_kpis(kpis: List[KPIItem], translations: Optional[dict] = None) -> str:
    """KPI'ları formatlanmış string'e çevirir"""
    t = translations or _get_translations("tr")
    out = []
    for k in kpis:
        out.append(
            f"**📊 {k.name}**\n"
            f"- {t['kpi_performance']}: {k.performance}\n"
            f"- {t['kpi_score']}: {k.score}/{k.max_score}\n"
            f"- {t['kpi_rationale']}: {k.rationale}\n"
        )
    return "\n".join(out)

# Çok dillilik için basit çeviri sözlüğü
def _get_translations(lang: str) -> dict:
    lang = (lang or "tr").lower()
    translations = {
        "tr": {
            "report_title": "Simülasyon Oturumu Değerlendirme Raporu",
            "scores_title": "Final Değerlendirme Puanları (KPI Bazlı)",
            "strengths_title": "Kullanıcının Güçlü Yönleri",
            "improvements_title": "Gelişim Alanları",
            "total_score": "Toplam Puan",
            "kpi_performance": "Performans",
            "kpi_score": "Puan",
            "kpi_rationale": "Gerekçe",
        },
        "en": {
            "report_title": "Simulation Session Evaluation Report",
            "scores_title": "Final Evaluation Scores (KPI Based)",
            "strengths_title": "User Strengths",
            "improvements_title": "Areas for Improvement",
            "total_score": "Total Score",
            "kpi_performance": "Performance",
            "kpi_score": "Score",
            "kpi_rationale": "Rationale",
        },
        "nl": {
            "report_title": "Evaluatierapport Simulatiesessie",
            "scores_title": "Eindbeoordeling (KPI)",
            "strengths_title": "Sterke Punten",
            "improvements_title": "Verbeterpunten",
            "total_score": "Totaalscore",
            "kpi_performance": "Prestatie",
            "kpi_score": "Score",
            "kpi_rationale": "Toelichting",
        },
        "az": {
            "report_title": "Simulyasiya Sessiyası Qiymətləndirmə Hesabatı",
            "scores_title": "Yekun Qiymətlər (KPI üzrə)",
            "strengths_title": "Güclü Tərəflər",
            "improvements_title": "İnkişaf Sahələri",
            "total_score": "Ümumi Bal",
            "kpi_performance": "Performans",
            "kpi_score": "Bal",
            "kpi_rationale": "İzah",
        },
    }
    return translations.get(lang, translations["tr"])

def measure_time(func):
    async def wrapper(*args, **kwargs):
        start_time = time.time()
        result = await func(*args, **kwargs)
        end_time = time.time()
        response_time = end_time - start_time
        print(f"{func.__name__} fonksiyonunun yanıt süresi: {response_time} saniye")
        return result
    return wrapper

class ChainState(TypedDict):
    """LangGraph state for managing messages and context."""
    messages: Annotated[Sequence[BaseMessage], add_messages]  # Kullanıcı ve sistem mesajları
    chat_history: Sequence[BaseMessage]  # Oturum geçmişi
    scenario: str  # Eğitim senaryosu
    is_feedback: bool  # UI'den gelen feedback talebi
    feedback_category: Optional[str]
    language: str  # Yanıtın üretileceği dil (tr/en/nl/az)
    average_response_time: Optional[float]  # Kullanıcının ortalama yanıt verme süresi (saniye)

class Chatbot:
    def __init__(self, session):
        self.session = session
        # OpenAI API anahtarını ayarla
        openai.api_key = settings.OPENAI_API_KEY

        # OpenAI dil modelini başlat
        self.llm = ChatOpenAI(
            model=llm_model,          
            temperature=0.7,          
            max_tokens=1000,
            streaming=True,
        )

        #iptal edildi
        self.llm_eval = ChatOpenAI(
            model=llm_model,          
            temperature=0.0,          
            max_tokens=1500,
            streaming=True,
        )
        
        # JSON structured output için streaming olmayan LLM
        self.llm_eval_json = ChatOpenAI(
            model=llm_model,
            temperature=0.0,
            max_tokens=1500,
            streaming=False,
        ).with_structured_output(EvalJSON)

    async def check_farewell_node(self, state: ChainState, config: RunnableConfig) -> str:
        """
        Kullanıcının son mesajını analiz eder, farewell tespitine göre graph yönünü belirler.
        """
        message = state["messages"][-1].content.lower()
        farewell_expressions = [
            # TR
            "görüşürüz", "görüşmek üzere", "hoşçakal", "hoşça kal", "hoşçakalın", "kendine iyi bak",
            "bay bay", "raporu ver", "raporu oluştur", "rapor oluştur", "rapor ver", "raporu hazırla",
            # EN
            "bye", "see you", "goodbye", "report please", "give me the report", "prepare the report", "generate report",
            # NL
            "tot ziens", "dag", "rapport graag", "geef het rapport", "rapport voorbereiden", "rapport genereren",
            # AZ
            "sag ol", "sag olun", "gorusuruk", "hesabat ver", "hesabat hazirla", "raporu ver"
        ]

        threshold = 90
        is_farewell = any(fuzz.token_set_ratio(message, phrase) >= threshold for phrase in farewell_expressions)
        
        print(f"[check_farewell_node] Girdi: '{message}' → {'VEDA' if is_farewell else 'DİYALOG'}")
        
        return "IS_FAREWELL" if is_farewell else "NOT_FAREWELL"
    
    async def check_feedback_flag(self, state: ChainState, config: RunnableConfig) -> str:
        """UI'den gelen feedback bayrağına göre yönlendirir."""
        is_feedback = state.get("is_feedback", False)
        category = state.get("feedback_category")
        print(f"[check_feedback_flag] is_feedback={is_feedback}, category={category}")
        return "IS_FEEDBACK" if is_feedback else "NOT_FEEDBACK"
    
    async def rag_chain(self, state: ChainState, config: RunnableConfig):
        """
        RAG Chain işletir
        """
        scenario = state["scenario"]
        language = state.get("language", "tr")
        language_label = {
            "tr": "Türkçe",
            "en": "English",
            "nl": "Dutch",
            "az": "Azerbaijani",
        }.get(language, "Türkçe")
        scenario_context = ""
        scenario_context, _ = await get_scenario_contents(scenario)

        system_prompt = (
            "## ROL TANIMI\n\n"
            "{name} adlı bir simülasyona katılan bir {ai_level} rolündesin. Rolünün tanımı senaryoda belirtilmiştir. "
            "Kullanıcı ise {user_level} rolünde ve simülasyona katılarak bir diyalog başlatıyor. "
            "Senin görevin, senaryoda tanımlanan karakter, davranışsal özellikler ve geçmiş deneyimlerine uygun şekilde gerçekçi yanıtlar vermek.\n\n"
            f"Bu yanıtı {language_label} dilinde ver. Senaryo metni başka dilde olsa bile çıktı dili {language_label} olacak. Dil değiştirme, çeviri yapma.\n\n"

            "## SENARYO BAĞLAMI\n\n"
            "{scenario_context}\n\n"

            "## ETKİLEŞİM KURALLARI\n"
            "1. Kullanıcı yapılandırılmış bir diyalog başlatır.\n"
            "2. Sen karakterine sadık kalarak ve geçmiş deneyimlerini göz önünde bulundurarak yanıtlar ver.\n"
            "3. Konuşma, gerçekçi işyeri dinamiklerini yansıtan doğal ancak yapılandırılmış bir akışı izlemelidir.\n"
            "4. Karakter dışına çıkma. Tutarlılığı koru.\n"
            "5. Kullanıcının tepkisine göre adapte ol. Gerekirse açıklayıcı sorular sor.\n"
            "6. Senin amacın diyalogu sürdürmektir. Sohbet, kullanıcı bitirdiğinde kapanır.\n"
            "7. Senaryo bağlamı dışındaki sorulara cevap verme. Söyleyeceğin her şey senaryo bağlamında olmalıdır.\n\n"
        ).format(
            scenario_context=scenario_context,
            name=scenario.name,
            ai_level=scenario.ai_level,
            user_level=scenario.user_level,
        )

        qa_prompt = ChatPromptTemplate.from_messages(
            [
                ("system", system_prompt),
                MessagesPlaceholder("chat_history"),
                ("human", "{input}"),
            ]
        )

        rag_chain = qa_prompt | self.llm
        response = await rag_chain.ainvoke({
            "input": state["messages"][-1].content,
            "chat_history": state["chat_history"]
        }, config=config)
        
        response_text = response.content
       
        state["messages"] = [AIMessage(content=response_text)]
        print(state)
        return state

    async def _run_evaluation(self, state: ChainState, config: RunnableConfig, feedback_note: Optional[str] = None):
        scenario = state["scenario"]
        language = state.get("language", "tr")
        translations = _get_translations(language)
        language_label = {
            "tr": "Türkçe",
            "en": "English",
            "nl": "Dutch",
            "az": "Azerbaijani",
        }.get(language, "Türkçe")
        _, evaluation_criteria = await get_scenario_contents(scenario)
        filtered_chat_history = [m for m in state["chat_history"] if isinstance(m, HumanMessage)]
        average_response_time = state.get("average_response_time")

        # Debug: chat history ve feedback bilgisi (bu bloğu sonra sileceğiz)
        try:
            history_preview = [
                f"{type(m).__name__}: {getattr(m, 'content', '')[:200]}"
                for m in filtered_chat_history
            ]
            print(f"[evaluation] chat_history_count={len(filtered_chat_history)} preview={history_preview}")
        except Exception as e:
            print(f"[evaluation] chat_history debug error: {e}")

        if average_response_time is not None:
            print(f"[evaluation] average_response_time={average_response_time:.2f} saniye")

        if feedback_note:
            print(f"[evaluation] feedback_note: {feedback_note[:500]}")

        # --- AŞAMA 1: JSON puanlarını çek (stream yok) ---
        json_system = (
            "## ROL TANIMI: DEĞERLENDİRME YAPAN EĞİTİMCİ\n\n"
            "Sen deneyimli bir kurumsal eğitim danışmanısın. Eğitimdeki katılımcıların performansını "
            "yapılandırılmış KPI kriterlerine göre değerlendiriyorsun.\n\n"
            "Sadece katılımcının yazdığı mesajlara (HumanMessage) dayanarak; titiz, tarafsız ve net bir "
            "değerlendirme yapmalısın. KPI kriterleri dışındaki yorumlamalardan kaçın.\n\n"
            
            "⚠️ KRİTİK UYARI: Mesaj analizinde HATA YAPMAK YASAK!\n"
            "Her mesajı kelime kelime, cümle cümle dikkatli oku. Kullanıcının yazdığı her ifadeyi, "
            "her kelimeyi, her cümleyi analiz et. 'takdir', 'teşekkür', 'memnun', 'başarılı' gibi "
            "kelimeleri kaçırma. Mesajın tamamını oku, yarısını değil!\n\n"
            
            "## DEĞERLENDİRME FORMAT TALİMATI\n\n"
            "Her KPI aşağıdaki biçimde tanımlanmıştır:\n"
            "- `# KPI:` ile başlar.\n"
            "- Ardından `- Maksimum Puan: XX` bilgisi gelir.\n"
            "- Devamında `* koşul → puan` biçiminde puanlama kuralları listelenir.\n\n"

            "Değerlendirme sırasında:\n"
            "- Yalnızca belirtilen kurallara göre puan ver.\n"
            "- Her puanın hangi ifadeye ve kurala dayandığını açıkla.\n"
            "- Tam puan sadece tüm koşullar eksiksiz sağlandığında verilebilir.\n"
            "- Katılımcının yazmadığı ifadeleri varsayma ya da tahmin etme.\n"
            "- Cümle benzerliğinden çok kelime eşleşmesi ve bağlam bütünlüğüne dikkat et.\n\n"
            
            "## 🔍 MESAJ ANALİZ TALİMATI\n"
            "Her KPI değerlendirmesi öncesinde:\n"
            "1. İlgili mesajları tekrar oku\n"
            "2. KPI'larda tanımlanmış olan anahtar kelimeleri tespit et (takdir, teşekkür, memnun, başarılı, vs.)\n"
            "3. Mesajın tamamını analiz et, yarısını değil\n"
            "4. Kelime eşleşmelerini kontrol et\n"
            "5. KPI DEĞERLENDİRME RAPORU Bağlamına göre analiz et.\n\n"

            "## KPI DEĞERLENDİRME RAPORU BAĞLAMI\n\n"
            f"{evaluation_criteria}\n\n"
        )
        
        # Ortalama yanıt verme süresi bilgisini ekle
        if average_response_time is not None:
            json_system += (
                f"\n## KULLANICI SÜRE YÖNETİMİ METRİKLERİ\n\n"
                f"- Ortalama Yanıt Verme Süresi: {average_response_time:.2f} saniye\n"
                f"Bu metrik, kullanıcının bir önceki GPT yanıtından sonra ne kadar sürede yanıt verdiğinin ortalamasıdır. "
                f"İlgili senaryo KPI'larında yanıt hızı veya zaman yönetimi gibi kriterler varsa, bu metrik değerlendirmede kullanılabilir.\n\n"
            )
        
        json_system += (
            "🟢 Not: Yalnızca katılımcının performansı değerlendirilecektir. "
            "AI karakterin rol performansı değerlendirme dışıdır.\n\n"

            "## ⚡ SON KONTROL TALİMATI\n"
            "JSON çıktı vermeden önce:\n"
            "1. Tüm mesajları tekrar oku ve analiz et\n"
            "2. Her KPI için kelime/ifade eşleşmelerini kontrol et\n"
            "3. Mesaj analiz hatası yapma!\n\n"

            "Lütfen yukarıdaki yönergeleri takip ederek KPI bazlı puanlama yap; sadece JSON döndür. "
            "Şema: kpis[{{name, max_score, score, rationale, performance}}], strengths[], improvements[]."
        )

        if feedback_note:
            json_system += f"\n{feedback_note}\n"

        # Chat history'yi text olarak birleştir (MessagesPlaceholder stream'e sızdırır)
        history_text = "\n\n".join([
            f"Kullanıcı Mesajı {i+1}: {m.content}" 
            for i, m in enumerate(filtered_chat_history)
        ]) if filtered_chat_history else "Henüz kullanıcı mesajı yok."
        
        json_prompt = ChatPromptTemplate.from_messages([
            ("system", json_system + f"\n\n## KULLANICI MESAJ GEÇMİŞİ\n\n{history_text}\n\nRaporu {language_label} dilinde üret ve dil değiştirme."),
            ("human", "{input}")
        ])
        json_chain = json_prompt | self.llm_eval_json

        try:
            json_resp: EvalJSON = await json_chain.ainvoke({
                "input": state["messages"][-1].content
            }, config=config)
            
            # Field validation kontrolü
            if not json_resp.kpis:
                print("⚠️ Uyarı: KPI listesi boş!")
                # Fallback: En azından bir KPI oluştur
                json_resp.kpis = [KPIItem(name="Genel Değerlendirme", max_score=100, score=0, rationale="Değerlendirme yapılamadı", performance="Sistem hatası nedeniyle performans değerlendirilemedi")]
            
            # KPI validation
            for kpi in json_resp.kpis:
                if kpi.score > kpi.max_score:
                    print(f"⚠️ KPI Hatası: {kpi.name} için puan ({kpi.score}) maksimumdan ({kpi.max_score}) büyük! Düzeltiliyor...")
                    kpi.score = kpi.max_score
                if kpi.score < 0:
                    print(f"⚠️ KPI Hatası: {kpi.name} için puan ({kpi.score}) negatif! Düzeltiliyor...")
                    kpi.score = 0
            
            print(f"✅ JSON başarıyla alındı: {len(json_resp.kpis)} KPI, {len(json_resp.strengths)} güçlü yön, {len(json_resp.improvements)} gelişim alanı")
            
        except Exception as e:
            print(f"❌ JSON parsing hatası: {e}")
            print("🔄 Fallback değerlendirme oluşturuluyor...")
            
            # Fallback EvalJSON oluştur
            json_resp = EvalJSON(
                kpis=[
                    KPIItem(
                        name="Genel Değerlendirme", 
                        max_score=100, 
                        score=50, 
                        rationale="LLM'den JSON alınamadığı için varsayılan puan verildi",
                        performance="Sistem hatası nedeniyle performans değerlendirilemedi"
                    )
                ],
                strengths=["Sistem hatası nedeniyle değerlendirilemedi"],
                improvements=["Tekrar deneyiniz"]
            )

        total = _sum_total(json_resp.kpis)
        print(f"📊 Hesaplanan toplam puan: {total}")

        # --- AŞAMA 2: Python ile rapor oluştur ---
        kpi_block = _lines_for_kpis(json_resp.kpis, translations)
        strengths_block = "\n\n".join([f"✅ {s}" for s in (json_resp.strengths or [])]) or "—"
        improvements_block = "\n\n".join([f"🔴 {s}" for s in (json_resp.improvements or [])]) or "—"

        report_text = (
            f"### {scenario.name} {translations['report_title']}\n\n"
            f"**1️⃣ {translations['scores_title']}**\n\n"
            f"{kpi_block}\n"
            f"**{translations['total_score']}: {total}/100**\n\n"
            "___\n\n"
            f"**2️⃣ {translations['strengths_title']}**\n\n"
            f"{strengths_block}\n\n"
            "___\n\n"
            f"**3️⃣ {translations['improvements_title']}**\n\n"
            f"{improvements_block}\n"
        )

        # Chat history'yi temizle (stream'e sızmasın)
        return {
            "messages": [AIMessage(content=report_text, additional_kwargs={"total_score": total})],
            "chat_history": [],  # Boş liste döndür
            "scenario": scenario
        }

    async def evaluation_node(self, state: ChainState, config: RunnableConfig):
        return await self._run_evaluation(state, config)

    async def feedback_evaluation_node(self, state: ChainState, config: RunnableConfig):
        feedback_category = state.get("feedback_category") or "genel"
        feedback_text = state["messages"][-1].content
        feedback_note = (
            "## FEEDBACK / İTİRAZ BİLGİSİ\n"
            f"- Kategori: {feedback_category}\n"
            f"- Kullanıcı itirazı: {feedback_text}\n"
            "- Yukarıdaki itirazı dikkate alarak KPI puanlarını yeniden değerlendir.\n"
        )
        return await self._run_evaluation(state, config, feedback_note=feedback_note)

    async def build_graph(self):
        """
        Kullanıcı Sorgusunu LangGraph ile işleyip yanıt döndürür.
        """
        graph_builder = StateGraph(ChainState)

        graph_builder.add_node("rag_chain", self.rag_chain)
        graph_builder.add_node("evaluation_node", self.evaluation_node)
        graph_builder.add_node("feedback_evaluation_node", self.feedback_evaluation_node)
        graph_builder.add_node("farewell_router", lambda state, config: state)

        # START → feedback kontrolü → farewell kontrolü
        graph_builder.add_conditional_edges(
            START,                      
            self.check_feedback_flag,  # feedback flag kontrolü
            {
                "IS_FEEDBACK": "feedback_evaluation_node",
                "NOT_FEEDBACK": "farewell_router"
            }
        )

        graph_builder.add_conditional_edges(
            "farewell_router",
            self.check_farewell_node,
            {
                "IS_FAREWELL": "evaluation_node",
                "NOT_FAREWELL": "rag_chain"
            }
        )

        # Diğer uçlar
        graph_builder.add_edge("rag_chain", END)
        graph_builder.add_edge("evaluation_node", END)
        graph_builder.add_edge("feedback_evaluation_node", END)

        return graph_builder.compile()

    async def generate_response(self, question, chat_history, scenario, is_feedback: bool = False, feedback_category: Optional[str] = None, language: str = "tr", average_response_time: Optional[float] = None):
        """LangGraph ile oluşturulmuş olan modeli asenkron şekilde çalıştırarak token bazlı yanıtlar üretir."""
        graph = await self.build_graph()

        state = ChainState(
            messages=[HumanMessage(content=question)],
            chat_history=chat_history,
            scenario=scenario,
            is_feedback=is_feedback,
            feedback_category=feedback_category,
            language=language,
            average_response_time=average_response_time
        )

        total_score = None
        async for message, metadata in graph.astream(state, config=RunnableConfig(), stream_mode="messages"):
            node = metadata.get("langgraph_node", None)
            
            #rag_chain'den dönen yanıtları stream eder
            if isinstance(message, AIMessageChunk) and node == "rag_chain":
                yield {
                    "token": message.content,
                    "node": node
                }
                await asyncio.sleep(0.02)
                
            #evaluation_node ve feedback_evaluation_node'dan dönen yanıtları stream eder
            elif isinstance(message, AIMessage) and node in ("evaluation_node", "feedback_evaluation_node"):
                import re
                # total_score metadata'sını çek
                if isinstance(message, AIMessage):
                    total_score = message.additional_kwargs.get("total_score")
                words = re.split(r'(\s+)', message.content)
                score_sent = False
                for word in words:
                    yield {
                        "token": word,
                        "node": node,
                        "total_score": total_score if not score_sent else None
                    }
                    score_sent = True
                    await asyncio.sleep(0.02)
