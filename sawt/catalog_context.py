"""Read-only bounded retrieval before planning; never selects or mutates an item."""
import re
from .domain import normalize, BRANCHES


def retrieve(menu, text, state):
    normalized=normalize(text)
    caller_words=set(normalized.split())
    name_words=[set(normalize(item['name']).split()) | set(normalize(item['name_en']).split()) for item in menu.items.values()]
    last_question=next((h['content'] for h in reversed(state['history']) if h['role']=='assistant'),'')
    # Short answers such as "دجاج ساندويتش" refer to the dish we just asked
    # about. Prior words aid retrieval only; they never authorize selections.
    if len(normalized.split())<=10 and ('؟' in last_question or '?' in last_question):
        normalized+=' '+normalize(last_question)
    # Name vocabulary only, not option words/categories that could turn a
    # short size answer into a broad unrelated menu search.
    vocabulary={word for item in menu.items.values() for label in (item['name'],item['name_en'])
                for word in normalize(label).split() if len(word)>=3}
    ignored={'with','and','the','بال','بدون','كبير','صغير','عادي','وجبة','وجبه'}
    terms=[]
    for word in normalized.split():
        forms=[word]
        if word.startswith(('و','ب')):forms.append(word[1:])
        if word.startswith('ال'):forms.append(word[2:])
        matched=next((v for v in forms if v in vocabulary and v not in ignored),None)
        if matched and matched not in terms:terms.append(matched)
    result={}
    if terms:
        result['menu_candidates']=menu.search(' '.join(terms),state['branch'],limit=5)
        result['matched_words']=terms
        result['unique_current_name_word']=any(word in caller_words and sum(word in names for names in name_words)==1 for word in terms)
        result['candidate_warning']='Candidates only. Unmatched caller words still matter. This does NOT prove the exact requested dish exists; never silently substitute. Retrieve further if needed.'
    if any(normalize(b['name']).replace('فرع ','') in normalized or
           any(normalize(zone) in normalized for zone in b['zones']) for b in BRANCHES.values()):
        result['branches']=BRANCHES
    return result
