from langchain_core.messages import HumanMessage, AIMessage
from langchain_community.document_loaders import PyPDFLoader, Docx2txtLoader
from asgiref.sync import sync_to_async

@sync_to_async
def get_chat_history(entry):
    """
    Belirli bir entry'ye ait chat geçmişini veritabanından alır.
    Ortalama yanıt verme süresini de hesaplar ve döndürür.
    """
    chat_history = entry.chats.all().order_by('timestamp')[:20]  # Zaman sırasına göre geçmiş
    formatted_history = []
    
    # Ortalama yanıt verme süresi hesaplama
    average_response_time = None
    total_response_time = 0.0
    user_query_count = 0
    last_gpt_response_timestamp = None
    
    for chat in chat_history:
        formatted_history.append(HumanMessage(content=chat.user_query))
        
        # İlk gpt_response'dan itibaren user_query'lerin bir önceki gpt_response'dan 
        # timestamp farkını hesapla
        if last_gpt_response_timestamp is not None:
            # Bu user_query'nin timestamp'i ile bir önceki gpt_response'ın timestamp'i arasındaki fark
            time_diff = (chat.timestamp - last_gpt_response_timestamp).total_seconds()
            total_response_time += time_diff
            user_query_count += 1
        
        if chat.gpt_response:
            formatted_history.append(AIMessage(content=chat.gpt_response))
            # Bir sonraki user_query için referans olarak bu gpt_response'ın timestamp'ini sakla
            last_gpt_response_timestamp = chat.timestamp
    
    # Ortalama süreyi hesapla (saniye cinsinden)
    if user_query_count > 0:
        average_response_time = total_response_time / user_query_count
    elif len(chat_history) > 0:
        # Eğer henüz gpt_response yoksa, None döndür
        average_response_time = None
    else:
        average_response_time = None
        
    return formatted_history, average_response_time

@sync_to_async
def get_scenario_contents(scenario):
    """
    Belirli bir senaryonun içeriğini veritabanından alır.
    """
    scenario_context = ""
    evaluation_criteria = ""
    
    # Senaryo dokümanı için
    if scenario.scenario_document:
        try:
            if scenario.scenario_document.name.lower().endswith('.pdf'):
                loader = PyPDFLoader(scenario.scenario_document.path)
            elif scenario.scenario_document.name.lower().endswith('.docx'):
                loader = Docx2txtLoader(scenario.scenario_document.path)
            else:
                loader = None
            if loader:
                docs = loader.load()
                scenario_context = "\n".join([doc.page_content for doc in docs])
        except Exception as e:
            scenario_context = f"Senaryo dokümanı okunurken hata oluştu: {e}"
    
    # Review dokümanı için (evaluation kriterleri)
    if scenario.review_document:
        try:
            if scenario.review_document.name.lower().endswith('.pdf'):
                loader = PyPDFLoader(scenario.review_document.path)
            elif scenario.review_document.name.lower().endswith('.docx'):
                loader = Docx2txtLoader(scenario.review_document.path)
            else:
                loader = None
            if loader:
                docs = loader.load()
                evaluation_criteria = "\n".join([doc.page_content for doc in docs])
        except Exception as e:
            evaluation_criteria = f"Review dokümanı okunurken hata oluştu: {e}"
    
    return scenario_context, evaluation_criteria
